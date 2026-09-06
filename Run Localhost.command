#!/bin/bash
# ===========================================================================
#  GEOVAX - Run Localhost Platform
#
#  Double-click this file in Finder to launch the GeovaX platform on localhost.
#  Starts both:
#    1. GeovaX Enterprise Web-GIS (Next.js)      -> http://localhost:3000
#    2. GeovaX Backend API & Harmonisation Map   -> http://127.0.0.1:8000
# ===========================================================================

set -e
cd "$(dirname "$0")" || exit 1

printf '\033[1;36m===========================================================================\033[0m\n'
printf '\033[1;32m   GEOVAX — National Geospatial Land Harmonisation System (Localhost)     \033[0m\n'
printf '\033[1;36m===========================================================================\033[0m\n\n'

hold() {
    printf '\n\nPress Return to close this window. '
    read -r _
    exit "${1:-0}"
}

# Ensure standard system tools, Homebrew, and pyenv are on PATH
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
    echo "[!] Could not locate the GeovaX platform directory."
    echo "    Make sure this launcher is placed in the project root."
    hold 1
}
cd "$TREE" || exit 1

# Check Python 3.11+
if ! command -v python3 >/dev/null 2>&1; then
    echo "[X] python3 was not found. Please install Python 3.11 or newer:"
    echo "    brew install python@3.12"
    hold 1
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || {
    echo "[X] GeovaX requires Python 3.11 or newer (found $(python3 -V 2>&1))."
    hold 1
}

# Check Node.js and npm
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "[!] Warning: Node.js or npm not found in PATH."
    echo "    Install Node.js with: brew install node"
fi

# Detect moved/stale virtual environment
drop_stale_venv() {
    [ -d .venv ] || return 0
    if ! ./.venv/bin/python3 -c "import sys, os; p=os.path.realpath(sys.prefix); cur=os.path.realpath('.venv'); raise SystemExit(0 if p==cur else 1)" >/dev/null 2>&1; then
        echo "  [*] Detected moved/renamed environment — refreshing virtualenv paths..."
        python3 -m venv --upgrade .venv >/dev/null 2>&1 || true
        # Update shebangs in bin/ if needed
        python3 -c '
import os, glob, sys
venv = os.path.realpath(".venv")
cur_py = os.path.join(venv, "bin", "python")
for f in glob.glob(os.path.join(venv, "bin", "*")):
    if os.path.isfile(f) and not os.path.islink(f):
        try:
            with open(f, "rb") as fh:
                data = fh.read()
            if data.startswith(b"#!"):
                lines = data.split(b"\n", 1)
                new_data = b"#!" + cur_py.encode() + b"\n" + (lines[1] if len(lines) > 1 else b"")
                with open(f, "wb") as fh:
                    fh.write(new_data)
        except Exception:
            pass
' >/dev/null 2>&1 || true
    fi
}

venv_ready() {
    drop_stale_venv
    if [ ! -d .venv ]; then
        echo "  [*] Creating Python virtual environment..."
        python3 -m venv .venv || { echo "[X] Failed to create .venv"; hold 1; }
    fi
    # shellcheck disable=SC1091
    . .venv/bin/activate

    if ! python3 -c "import GeovaX" >/dev/null 2>&1; then
        echo "  [*] Installing backend platform in development mode..."
        python3 -m pip install -e "backend[dev]" --no-deps > /tmp/geovax_backend_install.log 2>&1 || {
            python3 -m pip install -e backend >> /tmp/geovax_backend_install.log 2>&1 || {
                echo "[X] Installation failed. Log:"
                tail -n 20 /tmp/geovax_backend_install.log
                hold 1
            }
        }
    fi
}

echo "Step 1/3: Checking Python environment..."
venv_ready
echo "  [✓] Python environment ready ($(python3 -V 2>&1))"

RUN_OUT="${GEOVAX_OUT:-out/chennai_metro}"
if [ ! -f "$RUN_OUT/metrics.json" ]; then
    echo "[!] Warning: No run record found in $RUN_OUT."
    echo "    Backend will start in empty store mode."
fi

# Ensure web-gis dependencies
if [ -d "web-gis" ] && command -v npm >/dev/null 2>&1; then
    echo "Step 2/3: Checking Web-GIS frontend..."
    if [ ! -d "web-gis/node_modules" ]; then
        echo "  [*] Installing Web-GIS npm dependencies..."
        (cd web-gis && npm install --silent) || echo "  [!] npm install encountered warnings."
    fi
    echo "  [✓] Web-GIS frontend ready"
fi

echo "Step 3/3: Starting GeovaX services..."

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    printf '\n\n\033[1;33m[!] Shutting down GeovaX services...\033[0m\n'
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    # Also clean up any lingering uvicorn / next processes started on ports 8000 / 3000
    pkill -f "uvicorn GeovaX.api.app:app" 2>/dev/null || true
    pkill -f "next dev -p 3000" 2>/dev/null || true
    echo "All services stopped."
    exit 0
}

trap cleanup INT TERM EXIT

# Start Backend API
echo "  [*] Starting FastAPI Backend on http://127.0.0.1:8000 ..."
env GEOVAX_OUT="$RUN_OUT" ./.venv/bin/python -m uvicorn GeovaX.api.app:app \
    --app-dir backend --host 127.0.0.1 --port 8000 \
    > /tmp/geovax_backend.log 2>&1 &
BACKEND_PID=$!

# Start Web-GIS Frontend if available
if [ -d "web-gis" ] && command -v npm >/dev/null 2>&1; then
    echo "  [*] Starting Next.js Web-GIS on http://localhost:3000 ..."
    (cd web-gis && npm run dev > /tmp/geovax_frontend.log 2>&1) &
    FRONTEND_PID=$!
fi

# Wait for backend to be healthy
echo "  [*] Waiting for services to initialize..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

printf '\n\033[1;32m===========================================================================\033[0m\n'
printf '\033[1;32m   GEOVAX PLATFORM IS LIVE ON LOCALHOST!                                  \033[0m\n'
printf '\033[1;32m===========================================================================\033[0m\n\n'

printf '  \033[1;34m🌐 Web-GIS Enterprise App:\033[0m   \033[1;37mhttp://localhost:3000\033[0m\n'
printf '  \033[1;34m🗺️  Harmonisation Console:\033[0m    \033[1;37mhttp://127.0.0.1:8000/map\033[0m\n'
printf '  \033[1;34m🇮🇳 Pan-India MVT Console:\033[0m    \033[1;37mhttp://127.0.0.1:8000/map-india\033[0m\n'
printf '  \033[1;34m📖 Interactive API Docs:\033[0m     \033[1;37mhttp://127.0.0.1:8000/docs\033[0m\n'
printf '  \033[1;34m🏥 Health Endpoint:\033[0m          \033[1;37mhttp://127.0.0.1:8000/health\033[0m\n\n'

# Display loaded data summary
if [ -f "$RUN_OUT/metrics.json" ]; then
    printf '\033[1mLoaded Dataset Statistics:\033[0m\n'
    python3 - "$RUN_OUT" <<'PYSUM'
import json, sys, pathlib
try:
    m = json.load(open(pathlib.Path(sys.argv[1]) / "metrics.json"))
    o = m.get("outputs", {})
    print("   • Area of Interest:   %s" % m.get("aoi", {}).get("name", "Chennai"))
    print("   • Harmonised Parcels: %s" % format(o.get("harmonised_parcels", 0), ","))
    print("   • Buildings:          %s" % format(o.get("harmonised_buildings", 0), ","))
    print("   • Adjudication Cases: %s" % format(o.get("adjudication_cases", 0), ","))
except Exception:
    pass
PYSUM
fi

printf '\n\033[1;33mOpening browser to http://localhost:3000 ...\033[0m\n'
if command -v open >/dev/null 2>&1; then
    open "http://localhost:3000" 2>/dev/null || open "http://127.0.0.1:8000/map" 2>/dev/null || true
fi

printf '\n\033[1m[i] Both servers are running in the background.\033[0m\n'
printf '\033[1m    Press Ctrl+C in this window at any time to stop all services.\033[0m\n\n'

# Wait indefinitely until user cancels
wait
