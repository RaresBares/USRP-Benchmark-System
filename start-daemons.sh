#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
DAEMON_DIR="${SCRIPT_DIR}/usrp_testbed_library"
PID_DIR="${SCRIPT_DIR}/.daemon_pids"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: .venv not found. Run ./setup-daemons.sh first."
    exit 1
fi

if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

USRP_TX_ADDR="${USRP_TX_ADDR:-192.168.10.2}"
USRP_RX_ADDR="${USRP_RX_ADDR:-192.168.10.2}"
MCR="${MASTER_CLOCK_RATE:-250000000}"
BUFFER_SCALE="${DAEMON_BUFFER_SCALE:-1.0}"
SIGNAL_DIR_HOST="${SIGNAL_DIR_HOST:-${SCRIPT_DIR}/data/signals}"

mkdir -p "$PID_DIR"
mkdir -p "$SIGNAL_DIR_HOST"

PYTHON="${VENV_DIR}/bin/python"

echo "=========================================="
echo "  Starting USRP Daemons"
echo "=========================================="
echo "  TX USRP: ${USRP_TX_ADDR}"
echo "  RX USRP: ${USRP_RX_ADDR}"
echo "  MCR:     ${MCR} Hz"
echo "  Buffer:  ${BUFFER_SCALE}x"
echo "  Signals: ${SIGNAL_DIR_HOST}"
echo "=========================================="

if [ -f "${PID_DIR}/tx.pid" ] && kill -0 "$(cat ${PID_DIR}/tx.pid)" 2>/dev/null; then
    echo "TX daemon already running (PID $(cat ${PID_DIR}/tx.pid))"
else
    echo "Starting TX daemon ..."
    sudo taskset -c 2 chrt -f 80 \
        "$PYTHON" "${DAEMON_DIR}/tx_daemon.py" \
        --usrp-addr "$USRP_TX_ADDR" \
        --mcr "$MCR" \
        --buffer-scale "$BUFFER_SCALE" \
        > "${SCRIPT_DIR}/logs/tx_daemon.log" 2>&1 &
    TX_PID=$!
    echo "$TX_PID" > "${PID_DIR}/tx.pid"
    echo "TX daemon started (PID ${TX_PID})"
fi

if [ -f "${PID_DIR}/rx.pid" ] && kill -0 "$(cat ${PID_DIR}/rx.pid)" 2>/dev/null; then
    echo "RX daemon already running (PID $(cat ${PID_DIR}/rx.pid))"
else
    echo "Starting RX daemon ..."
    sudo taskset -c 3 chrt -f 80 \
        "$PYTHON" "${DAEMON_DIR}/rx_daemon.py" \
        --usrp-addr "$USRP_RX_ADDR" \
        --mcr "$MCR" \
        --buffer-scale "$BUFFER_SCALE" \
        > "${SCRIPT_DIR}/logs/rx_daemon.log" 2>&1 &
    RX_PID=$!
    echo "$RX_PID" > "${PID_DIR}/rx.pid"
    echo "RX daemon started (PID ${RX_PID})"
fi

echo ""
echo "Logs: ${SCRIPT_DIR}/logs/tx_daemon.log"
echo "       ${SCRIPT_DIR}/logs/rx_daemon.log"
echo ""
echo "Stop with: ./stop-daemons.sh"
