#!/usr/bin/env bash
# flash_ota.sh — Build and upload firmware to TTGO over WiFi (OTA).
#
# Usage:
#   ./scripts/flash_ota.sh             # uses ttgo-display.local (mDNS)
#   ./scripts/flash_ota.sh 192.168.1.X # use IP directly if mDNS doesn't work
#
# Requirements:
#   - TTGO must be powered on and connected to WiFi
#   - OTA password in firmware/wifi_config.h must match --auth flag in platformio.ini
#   - First-ever flash must still be done via USB

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

TARGET="${1:-ttgo-display.local}"

echo "==> Building and flashing OTA to $TARGET ..."

# If a custom IP/host was given, override the upload_port on the fly
if [ "$TARGET" != "ttgo-display.local" ]; then
    pio run --target upload --environment ota \
        --upload-port "$TARGET"
else
    pio run --target upload --environment ota
fi

echo "==> OTA flash complete!"
