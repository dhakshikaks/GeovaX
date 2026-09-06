# GeovaX Dataset URLs and Real-Data Policy

This file is the complete URL inventory for the datasets declared in
`data_acquisition/sources.py`. The production pipeline uses downloaded or live-fetched
real data only. No generated, fabricated, or synthetic feature layer is used as a
runtime input.

## Downloadable and live data sources

| Key | Dataset | URL | Provenance |
|---|---|---|---|
| `tngis_cadastre` | Tamil Nadu cadastral parcels | https://github.com/ramSeraph/indian_cadastrals/releases/download/tamil-nadu/TNGIS_TN_Cadastrals.geojsonl.7z | Real Tamil Nadu cadastral data; mirror of TNGIS |
| `ncscm_cadastre` | Coastal Tamil Nadu cadastral parcels | https://github.com/ramSeraph/indian_cadastrals/releases/download/tamil-nadu/NCSCM_TN_Cadastrals.geojsonl.7z | Real NCSCM cadastral compilation; mirror |
| `gcc_buildings` | Greater Chennai Corporation building footprints | https://github.com/ramSeraph/indian_buildings/releases/download/urban/TNGIS_GCC_Chennai_Buildings.geojsonl.7z | Real municipal GIS data; mirror |
| `amrut_buildings` | AMRUT urban building footprints, Tamil Nadu | https://github.com/ramSeraph/indian_buildings/releases/download/urban/TN_AMRUT_Buildings.geojsonl.7z | Real Bhuvan/AMRUT data; mirror |
| `google_open_buildings` | Google Open Buildings V3, S2 cell 3a5 | https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/3a5_buildings.csv.gz | Real Google Research ML extraction |
| `lgd_india` | Local Government Directory village boundaries | https://github.com/ramSeraph/indian_admin_boundaries/releases/download/villages/LGD_Villages.geojsonl.7z | Real LGD-derived administrative data; mirror |
| `gcc_wards` | Greater Chennai Corporation ward boundaries | https://raw.githubusercontent.com/yashveeeeeeer/india-geodata/main/data/urban/municipal-boundaries/chennai/Wards.geojson | Real GCC/DataMeet municipal data; mirror |
| `gcc_zones` | Greater Chennai Corporation zone boundaries | https://raw.githubusercontent.com/yashveeeeeeer/india-geodata/main/data/urban/municipal-boundaries/chennai/Zones.geojson | Real GCC/DataMeet municipal data; mirror |
| `cma_boundary` | Chennai Metropolitan Area boundary | https://raw.githubusercontent.com/yashveeeeeeer/india-geodata/main/data/urban/municipal-boundaries/chennai/CMA.geojson | Real CMDA/DataMeet planning boundary; mirror |
| `uav_ori_odm` | OpenDroneMap UAV orthorectified imagery | https://github.com/OpenDroneMap/UAVArena.git#data/odm-3.0.0 | Real public UAV photogrammetry corpus; proxy for Indian NAKSHA imagery |
| `uav_ori_pix4d` | Pix4D UAV orthorectified imagery | https://github.com/OpenDroneMap/UAVArena.git#data/pix4d-4.4.10 | Real public UAV photogrammetry corpus; proxy |
| `uav_dsm_odm` | OpenDroneMap UAV digital surface model | https://github.com/OpenDroneMap/UAVArena.git#data/odm-3.0.0/*/dsm | Real public UAV DSM; proxy |
| `svamitva_drone_villages` | SVAMITVA drone-surveyed village metadata | https://www.data.gov.in/resource/drone-flown-villages | Real official Government of India metadata; API credentials required |
| `ncscm_czmp_tn` | Tamil Nadu Coastal Zone Management Plan | https://ncscm.res.in/wp-content/uploads/pdf/TN_CZMP.pdf | Real official NCSCM publication |
| `njdg_ecourts` | NJDG/e-Courts property dispute linkage | https://napix.gov.in | Real official NAPIX service; department credentials required |
| `tn_registration_ec` | Tamil Nadu Registration Department EC service | https://tnreginet.gov.in/ | Real official government service; user verification required |
| `tn_patta_chitta` | Tamil Nadu Patta/Chitta/FMB/A-Register | https://eservices.tn.gov.in/ | Real official government service; CAPTCHA/OTP required |
| `tn_ogd_panchayats` | Tamil Nadu blocks, habitations and village panchayats | https://tn.data.gov.in/catalog/details-blocks-habitations-and-village-panchayats-tamil-nadu | Real official OGD catalogue; API credentials required |
| `gcc_opencity_wards` | GCC Ward Map / Zone Map 2022 | https://data.opencity.in/dataset/gcc-ward-information | Real GCC-attributed dataset via OpenCity CKAN; mirror |
| `chennai_metrowater_transmission` | Chennai Water Transmission Network | https://data.opencity.in/dataset/chennai-water-transmission-network | Real CMWSSB-attributed utility data via OpenCity CKAN; mirror |
| `ms_building_footprints_tn` | Microsoft Global ML Building Footprints, India quadkey 123312203 | https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl/RegionName=India/quadkey=123312203/part-00159-4feead82-d499-422b-94cb-c036c212127a.c000.csv.gz | Real Microsoft open ML extraction |
| `bhuvan_cartodem` | ISRO/NRSC CartoDEM v3 | https://bhuvan-app3.nrsc.gov.in/data/download/ | Real official Bhuvan elevation data; account required |
| `soi_cors_rinex` | Survey of India CORS / virtual RINEX | https://cors.surveyofindia.gov.in/ | Real official GNSS service; registration/subscription required |
| `noaa_cors_rinex_proxy` | NOAA/NGS CORS RINEX observation, station AB02 | https://noaa-cors-pds.s3.amazonaws.com/rinex/2024/001/ab02/ab020010.24o.gz | Real NOAA/UNAVCO observation; proxy for credential-gated Indian CORS |
| `osm_buildings_gt` | OpenStreetMap Chennai building ground-truth reference | https://overpass.kumi.systems/api/interpreter | Real live OSM community data; proxy, not official government GT |
| `naksha_dolr` | NAKSHA National Cadastral Mapping Platform | https://naksha.dolr.gov.in/NakshaPortal/ | Real official DoLR platform; departmental credentials required |
| `soi_open_series_maps` | Survey of India Open Series Maps | https://onlinemaps.surveyofindia.gov.in/ | Real official Survey of India service; login required |

## Related official service endpoints

These are the actual service endpoints used by connectors, rather than separate
bulk-download datasets:

- TNGIS GeoServer WFS/WMS probe: https://tngis.tn.gov.in/geoserver/tngis/ows
- NAKSHA ArcGIS service: https://nakshagis.dolr.gov.in/utm44/rest/services/Naksha_44/Naksha_tn_33_44/FeatureServer
- NAKSHA token service: https://nakshagis.dolr.gov.in/portal/sharing/rest/generateToken
- TamilNilam revenue service: https://tamilnilam.tn.gov.in/egovService/
- Survey of India CORS portal: https://cors.surveyofindia.gov.in/
- Overpass API: https://overpass.kumi.systems/api/interpreter
- OpenCity CKAN API: https://data.opencity.in/api/3/action/package_show
- LGD official directory: https://lgdirectory.gov.in/
- Google Open Buildings catalogue: https://sites.research.google/open-buildings/
- Microsoft building dataset index: https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv

## No-synthetic-data guarantee

- `data/aoi/` and `data/aoi_msproof/` contain clipped outputs from the real sources above.
- `backend/GeovaX/pipeline/presets.py` includes only real-source layers and skips a source
  when its real file is absent; it does not substitute generated features.
- Proxy means real external data used where the Indian authoritative source is gated or
  unavailable. It does not mean synthetic.
- The OpenDroneMap, NOAA, and OSM entries are explicitly labelled proxy and are never
  presented as Indian government data.
- Test files may use small in-memory geometries or mocked HTTP responses to test isolated
  algorithms and authentication failure paths. These are test fixtures only and are not
  loaded by the API, demo, data acquisition, or production pipeline.
- The API reads published pipeline output from `GEOVAX_OUT`; synthetic feature generators
  were removed from the runtime path.

For the authoritative metadata, licence, source tier, access requirements, and local
filename for every entry, see `data_acquisition/sources.py`.
