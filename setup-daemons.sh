#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

echo "=========================================="
echo "  USRP Daemon Setup"
echo "=========================================="

if [ -d "$VENV_DIR" ]; then
    echo "Existing .venv found at ${VENV_DIR}"
    read -p "Recreate? [y/N] " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        rm -rf "$VENV_DIR"
    else
        echo "Keeping existing .venv"
        source "${VENV_DIR}/bin/activate"
        pip install --upgrade -e "${SCRIPT_DIR}/usrp_testbed_library"
        echo "Done (updated testbed library)"
        exit 0
    fi
fi

echo "Creating .venv at ${VENV_DIR} ..."
python3 -m venv "$VENV_DIR"
source "${VENV_DIR}/bin/activate"

echo "Installing usrp_testbed_library ..."
pip install --upgrade pip
pip install -e "${SCRIPT_DIR}/usrp_testbed_library"

echo ""
echo "=========================================="
echo "  Setup complete"
echo "=========================================="
echo ""
echo "The .venv is at: ${VENV_DIR}"
echo ""
echo "NOTE: UHD (uhd python bindings) must be installed separately."
echo "On zubat, install via conda or system package:"
echo "  pip install uhd"
echo "  # or: conda install -c conda-forge uhd"
echo ""
echo "Next steps:"
echo "  1. Install UHD if not already present"
echo "  2. Copy .env and set USE_REAL_USRP=true"
echo "  3. Run: ./start-daemons.sh"
echo "  4. Run: docker compose -f docker-compose.prod.yml up -d"
echo ""
