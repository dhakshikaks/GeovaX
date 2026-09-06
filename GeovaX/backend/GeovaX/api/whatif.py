"""What-If Land Impact Analysis.

A real spatial simulation against this run's published collections — never against an
authoritative store, and nothing here writes anything. Given a proposed geometry (a
GeoJSON polygon an officer is considering: a redrawn parcel boundary, a footprint pending
acceptance, a candidate right-of-way), this computes which real parcels, buildings,
utility segments and open adjudication cases it would actually overlap or sit near, using
the same geometry engine (shapely) and the same "reproject only what's needed to a local
metric CRS" pattern already used elsewhere in this codebase (``crs/engine.py``,
``change/vector_change.py``'s encroachment check, ``matching/features.py``'s STRtree
blocking) — not a second, ad hoc spatial engine.

Overlap areas are reported in real square metres, not degrees-as-metres: only the small set
of candidates an ``STRtree`` bbox query actually returns are reprojected to the appropriate
local UTM zone (``CrsEngine.metric_crs_for``) before computing intersection area — reprojecting
every candidate feature in a 218k-parcel/1.4M-building collection up front would be wasteful
and is never necessary, since a single proposed geometry can only ever intersect a tiny,
geographically local subset of them.

Before any shapely geometry is built, every collection is narrowed by a raw-coordinate
bounding-box prefilter (no shapely object constructed at all for a rejected feature) — this
is what makes a request against 1.4M buildings affordable. That prefilter's own per-feature
bounds are cached in-process, keyed by the stable identity of the collection list
``FeatureStore``/``PostgisStore`` already caches — so the one real cost of walking 1.4M
buildings' coordinates is paid once per server process (measured ~8s on the full
``chennai_metro`` run), not once per request (measured ~0.2-0.3s once warm).
"""
from __future__ import annotations

from typing import Any

from shapely.geometry import shape as _shapely_shape
from shapely.strtree import STRtree

from ..attributes.canonical import BUILDING_SCHEMA, PARCEL_SCHEMA, redact_pii
from ..crs.engine import CrsEngine, haversine_m

UTILITY_PROXIMITY_M = 50.0
"""A proposed change within this distance of a real utility segment is flagged for
awareness — matches the proximity threshold api/twin.py::digital_twin already uses for a
parcel's own utility linkage (there, 75 m for a whole parcel; here, tighter, since a
what-if proposal is usually a single boundary edit, not a whole-parcel query)."""

MAX_ITEMS_PER_CATEGORY = 100

BBOX_PAD_DEGREES = 0.001
"""~110 m at the equator, generous enough that no genuinely overlapping feature is ever
excluded by the cheap prefilter below, while still being tight enough to reject nearly all
of a full run's collection before any shapely geometry is built."""


def _raw_bounds(geometry: dict[str, Any] | None) -> tuple[float, float, float, float] | None:
    """Bounding box straight from GeoJSON coordinates, no shapely object constructed —
    this is what makes prefiltering 1.4M buildings per what-if request affordable at all.
    """
    if not geometry:
        return None
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords: Any) -> None:
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for c in coords:
                walk(c)

    try:
        walk(geometry.get("coordinates", []))
    except (TypeError, IndexError):
        return None
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


# Precomputed (bounds, feature) pairs, keyed by id() of the collection list `store.collections`
# returns — that list is loaded and cached once by FeatureStore/PostgisStore and the same
# object is returned on every access for the life of the process, so this key is stable.
# Walking 1.4M buildings' raw coordinates to get a bbox is a few seconds of pure Python; doing
# it on every /api/whatif/simulate call (a different proposed geometry each time, but the same
# underlying collection) would repeat that cost for no reason. This cache pays it once.
_bounds_cache: dict[int, list[tuple[tuple[float, float, float, float], dict[str, Any]]]] = {}


def _bounds_index(features: list[dict[str, Any]]) -> list[tuple[tuple[float, float, float, float], dict[str, Any]]]:
    key = id(features)
    cached = _bounds_cache.get(key)
    if cached is not None:
        return cached
    indexed = []
    for f in features:
        b = _raw_bounds(f.get("geometry"))
        if b is not None:
            indexed.append((b, f))
    _bounds_cache[key] = indexed
    return indexed


def _prefilter_by_bbox(
    features: list[dict[str, Any]], proposed_bounds: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    padded = (
        proposed_bounds[0] - BBOX_PAD_DEGREES, proposed_bounds[1] - BBOX_PAD_DEGREES,
        proposed_bounds[2] + BBOX_PAD_DEGREES, proposed_bounds[3] + BBOX_PAD_DEGREES,
    )
    return [f for b, f in _bounds_index(features) if _bbox_overlaps(b, padded)]


def _index(features: list[dict[str, Any]]) -> tuple[Any, list[Any], list[dict[str, Any]]]:
    geoms: list[Any] = []
    valid: list[dict[str, Any]] = []
    for f in features:
        geometry = f.get("geometry")
        if not geometry:
            continue
        try:
            g = _shapely_shape(geometry)
        except Exception:
            continue
        if g.is_empty:
            continue
        geoms.append(g)
        valid.append(f)
    if not geoms:
        return None, [], []
    return STRtree(geoms), geoms, valid


def _overlaps(
    proposed: Any,
    proposed_metric: Any,
    metric_crs: str,
    features: list[dict[str, Any]],
    *,
    proposed_bounds: tuple[float, float, float, float],
    engine: CrsEngine,
    schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Reject nearly all of a full run's collection by raw coordinate bounds before
    # constructing a single shapely geometry — this is what keeps a what-if request
    # affordable against 1.4M buildings (see BBOX_PAD_DEGREES).
    candidates = _prefilter_by_bbox(features, proposed_bounds)
    tree, geoms, valid = _index(candidates)
    if tree is None:
        return []
    hits = []
    for idx in tree.query(proposed):
        g = geoms[idx]
        if not g.intersects(proposed):
            continue
        feature = valid[idx]
        props = feature.get("properties", {})
        try:
            g_metric = engine.transform_geometry(g, "EPSG:4326", metric_crs)
            intersection_area_m2 = g_metric.intersection(proposed_metric).area
            existing_area_m2 = g_metric.area
        except Exception:
            intersection_area_m2 = None
            existing_area_m2 = None
        hits.append({
            "entity_id": props.get("entity_id") or props.get("case_id"),
            "ulpin": props.get("ulpin"),
            "overlap_area_m2": round(intersection_area_m2, 2) if intersection_area_m2 is not None else None,
            "existing_feature_area_m2": round(existing_area_m2, 2) if existing_area_m2 is not None else None,
            "overlap_fraction_of_existing": (
                round(intersection_area_m2 / existing_area_m2, 4)
                if intersection_area_m2 is not None and existing_area_m2
                else None
            ),
            "properties": redact_pii(props, schema) if schema else props,
        })
    hits.sort(key=lambda h: h["overlap_area_m2"] or 0.0, reverse=True)
    return hits


def simulate(
    store: Any, proposed_geometry: dict[str, Any], *, feature_class: str = "parcel"
) -> dict[str, Any]:
    """Evaluate a proposed geometry against this run's real, published collections.

    Returns a dict with an ``"error"`` key (and nothing else) if the geometry is unusable,
    so callers can 400 without this module knowing about HTTP.
    """
    try:
        proposed = _shapely_shape(proposed_geometry)
    except Exception as exc:
        return {"error": f"invalid GeoJSON geometry: {exc}"}
    if proposed.is_empty:
        return {"error": "proposed geometry is empty"}
    if not proposed.is_valid:
        return {"error": "proposed geometry is not topologically valid (self-intersecting or malformed)"}

    centroid = proposed.centroid
    try:
        metric_crs = CrsEngine.metric_crs_for(centroid.x, centroid.y)
    except ValueError as exc:
        return {"error": f"proposed geometry centroid out of range: {exc}"}

    engine = CrsEngine()
    proposed_metric = engine.transform_geometry(proposed, "EPSG:4326", metric_crs)
    proposed_bounds = proposed.bounds

    parcels = store.collections.get("parcels", [])
    buildings = store.collections.get("buildings", [])
    utilities = store.collections.get("utilities", [])
    adjudication = store.collections.get("adjudication", [])

    affected_parcels = _overlaps(proposed, proposed_metric, metric_crs, parcels,
                                  proposed_bounds=proposed_bounds, engine=engine, schema=PARCEL_SCHEMA)
    affected_buildings = _overlaps(proposed, proposed_metric, metric_crs, buildings,
                                    proposed_bounds=proposed_bounds, engine=engine, schema=BUILDING_SCHEMA)
    affected_adjudication = _overlaps(proposed, proposed_metric, metric_crs, adjudication,
                                       proposed_bounds=proposed_bounds, engine=engine)

    # Utility proximity search widens the bbox by the proximity radius (in degrees, coarse
    # but generous) before the exact haversine check, for the same reason as _overlaps above.
    utility_pad = UTILITY_PROXIMITY_M / 100_000.0 + BBOX_PAD_DEGREES
    padded_bounds = (proposed_bounds[0] - utility_pad, proposed_bounds[1] - utility_pad,
                      proposed_bounds[2] + utility_pad, proposed_bounds[3] + utility_pad)
    nearby_utilities = []
    for u in _prefilter_by_bbox(utilities, padded_bounds):
        geometry = u.get("geometry")
        try:
            ug = _shapely_shape(geometry)
        except Exception:
            continue
        uc = ug.centroid
        distance_m = haversine_m(centroid.x, centroid.y, uc.x, uc.y)
        if distance_m <= UTILITY_PROXIMITY_M:
            props = u.get("properties", {})
            nearby_utilities.append({
                "feature": props.get("name") or props.get("id") or props.get("asset_id") or "unnamed segment",
                "approx_distance_m": round(distance_m, 1),
            })
    nearby_utilities.sort(key=lambda u: u["approx_distance_m"])

    return {
        "simulation": True,
        "authoritative_change_applied": False,
        "feature_class_evaluated": feature_class,
        "metric_crs_used": metric_crs,
        "proposed_geometry_area_m2": round(proposed_metric.area, 2),
        "affected_parcels": {
            "count": len(affected_parcels),
            "items": affected_parcels[:MAX_ITEMS_PER_CATEGORY],
            "truncated": len(affected_parcels) > MAX_ITEMS_PER_CATEGORY,
        },
        "affected_buildings": {
            "count": len(affected_buildings),
            "items": affected_buildings[:MAX_ITEMS_PER_CATEGORY],
            "truncated": len(affected_buildings) > MAX_ITEMS_PER_CATEGORY,
        },
        "affected_open_adjudication_cases": {
            "count": len(affected_adjudication),
            "items": affected_adjudication[:20],
        },
        "nearby_utilities": nearby_utilities[:20],
        "note": (
            "This is a simulation over this run's published collections only. No parcel, "
            "building, utility, or adjudication record was created, modified, or deleted. "
            "Overlap areas are computed by reprojecting only the intersecting candidates to "
            f"the appropriate local UTM zone ({metric_crs}) — a real metric area, not a "
            "degrees-as-metres approximation."
        ),
    }
