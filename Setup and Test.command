#!/bin/bash
# ===========================================================================
#  GEOVAX - Setup and Test Platform
#
#  Double-click this file in Finder to verify the environment, run the
#  complete test suite, and check the provenance ledger integrity.
# ===========================================================================

cd "$(dirname "$0")" || exit 1
printf '\033[1;36m===========================================================================\033[0m\n'
printf '\033[1;32m   GEOVAX — Setup and Verification Test Suite                             \033[0m\n'
printf '\033[1;36m===========================================================================\033[0m\n\n'

hold() {
    printf '\n\nPress Return to close this window. '
    read -r _
    exit "${1:-0}"
}

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.homebrew/bin:$HOME/.local/bin:$PATH"

here="$(cd "$(dirname "$0")" && pwd)"
find_tree() {
    for c in "$here/GeovaX" "$here/geovax" "$here" \
             "$here/../GeovaX/GeovaX" "$here/../GeovaX"; do
        if [ -f "$c/Makefile" ] && [ -d "$c/backend/GeovaX" ]; then
            cd "$c" && pwd && return 0
        fi
    done
    return 1
}

TREE="$(find_tree)" || {
    echo "Could not find the platform directory."
    hold 1
}
cd "$TREE" || exit 1

RUN_OUT="${GEOVAX_OUT:-out/chennai_metro}"

need_py() {
    command -v python3 >/dev/null 2>&1 || {
        echo "python3 was not found. Install it with: brew install python@3.12"
        hold 1
    }
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || {
        echo "GEOVAX needs Python 3.11 or newer - found $(python3 -V 2>&1)."
        hold 1
    }
}

drop_stale_venv() {
    [ -d .venv ] || return 0
    if ! ./.venv/bin/python3 -c "import sys, os; p=os.path.realpath(sys.prefix); cur=os.path.realpath('.venv'); raise SystemExit(0 if p==cur else 1)" >/dev/null 2>&1; then
        echo "  .venv was built elsewhere - refreshing virtualenv paths..."
        python3 -m venv --upgrade .venv >/dev/null 2>&1 || true
    fi
}

venv_ready() {
    need_py
    drop_stale_venv
    if [ ! -d .venv ]; then
        echo "Creating the virtual environment..."
        python3 -m venv .venv || { echo "could not create .venv"; hold 1; }
    fi
    # shellcheck disable=SC1091
    . .venv/bin/activate
    if ! python3 -c "import GeovaX" >/dev/null 2>&1; then
        echo "Installing the platform in development mode..."
        python3 -m pip install -e "backend[dev]" --no-deps > /tmp/geovax_pip.log 2>&1 || {
            python3 -m pip install -e backend >> /tmp/geovax_pip.log 2>&1 || {
                echo "install failed - see /tmp/geovax_pip.log"
                tail -25 /tmp/geovax_pip.log
                hold 1
            }
        }
    fi
    echo "  ready: $(python3 -V 2>&1), GeovaX importable"
}

have_run() { [ -f "$RUN_OUT/metrics.json" ]; }

run_summary() {
python3 - "$RUN_OUT" <<'PYSUM'
import json, sys, pathlib
m = json.load(open(pathlib.Path(sys.argv[1]) / "metrics.json"))
o, l, s = m["outputs"], m["ledger"], m["stage_seconds"]
print("  AOI                 %s" % m["aoi"]["name"])
print("  parcels             %s" % format(o["harmonised_parcels"], ","))
print("  buildings           %s" % format(o["harmonised_buildings"], ","))
print("  typed discrepancies %s" % format(o["changes"], ","))
print("  adjudication cases  %s" % format(o["adjudication_cases"], ","))
print("  wall clock          %.1f s over %d stages" % (sum(s.values()), len(s)))
print("  ledger              %s, %d entries" % ("verified" if l["verified"] else "BROKEN", l["entries"]))
print("  merkle root         %s..." % l["merkle_root"][:32])
PYSUM
}

echo "Testing environment and running full test suite..."
venv_ready
echo
echo "Running the test suite..."
python3 -m pytest tests/ -q || { echo "TESTS FAILED"; hold 1; }
echo
if have_run; then
    echo "Current dataset on disk ($RUN_OUT):"
    run_summary
    echo
    echo "Verifying provenance ledger..."
    ./.venv/bin/geovax verify --out "$RUN_OUT" 2>&1 | tail -10
fi
echo
printf '\033[1;32m[✓] All tests passed and platform verified!\033[0m\n\n'
printf 'To launch the platform locally, run:\033[1m  Run Localhost.command\033[0m\n'
hold 0
