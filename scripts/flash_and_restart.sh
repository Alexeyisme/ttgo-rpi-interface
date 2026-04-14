#!/usr/bin/env bash
# flash_and_restart.sh — Build, upload, restart bridge, tail logs.
# One command for a full TTGO development cycle.
set -euo pipefail

PROJECT_DIR="/home/homunculus/.hermes/hermes-agent/ttgo-display"
PIO="/home/homunculus/.hermes/hermes-agent/venv/bin/pio"
SERVICE="ttgo-bridge.service"
SERIAL_PORT="/dev/ttyACM0"
LOG_SECONDS=10
BUILD_ONLY=false
SKIP_BUILD=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)     BUILD_ONLY=true; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --logs)      LOG_SECONDS="${2:-10}"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--build] [--skip-build] [--logs N]"
            echo "  --build       Build only, don't upload or restart"
            echo "  --skip-build  Upload last build, skip compile"
            echo "  --logs N      Tail journal for N seconds (default: 10)"
            exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo -e "\033[1;36m>> $*\033[0m"; }
ok()   { echo -e "\033[1;32m✓  $*\033[0m"; }
fail() { echo -e "\033[1;31m✗  $*\033[0m"; exit 1; }

elapsed() {
    local s=$1
    printf "%dm%02ds" $((s/60)) $((s%60))
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────
[[ -f "$PIO" ]] || fail "PlatformIO not found at $PIO"
[[ -d "$PROJECT_DIR/firmware" ]] || fail "Firmware dir missing: $PROJECT_DIR/firmware"

# ── Step 1: Stop bridge (releases serial port) ───────────────────────────────
if ! $BUILD_ONLY; then
    if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
        log "Stopping $SERVICE..."
        sudo systemctl stop "$SERVICE"
        sleep 0.5
        ok "Bridge stopped"
    fi
fi

# ── Step 2: Build ─────────────────────────────────────────────────────────────
if ! $SKIP_BUILD; then
    log "Building firmware..."
    t0=$SECONDS
    if "$PIO" run -d "$PROJECT_DIR" 2>&1; then
        ok "Build succeeded in $(elapsed $((SECONDS - t0)))"
    else
        fail "Build failed after $(elapsed $((SECONDS - t0)))"
    fi
fi

if $BUILD_ONLY; then
    ok "Build-only mode — done."
    exit 0
fi

# ── Step 3: Upload ────────────────────────────────────────────────────────────
[[ -e "$SERIAL_PORT" ]] || fail "Serial port $SERIAL_PORT not found"
log "Uploading firmware to $SERIAL_PORT..."
t0=$SECONDS
if "$PIO" run -d "$PROJECT_DIR" -t upload 2>&1; then
    ok "Upload succeeded in $(elapsed $((SECONDS - t0)))"
else
    fail "Upload failed after $(elapsed $((SECONDS - t0)))"
fi

# ── Step 4: Wait for ESP32 reboot ─────────────────────────────────────────────
log "Waiting 3s for ESP32 to boot..."
sleep 3
ok "ESP32 should be ready"

# ── Step 5: Restart bridge ─────────────────────────────────────────────────────
if ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    log "Restarting $SERVICE..."
    sudo systemctl start "$SERVICE" || true
    sleep 1
fi

if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    ok "Bridge is running"
else
    fail "Bridge failed to start — check: journalctl -u $SERVICE -n 30"
fi

# ── Step 6: Tail logs ───────────────────────────────────────────────────────────
log "Tailing bridge logs for ${LOG_SECONDS}s (Ctrl+C to stop)..."
echo "─────────────────────────────────────────────────────────────"

timeout "${LOG_SECONDS}" journalctl -u "$SERVICE" -f --no-pager --output=short-iso 2>/dev/null || true

echo "─────────────────────────────────────────────────────────────"
ok "Done! Full cycle complete."
