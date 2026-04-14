TTGO T-Display Hermes Satellite — enhancements notes

This document captures proposed low-effort/high-value improvements for the TTGO T-Display firmware + the Python bridge daemon.

1) Heartbeat packet (high value)
- Problem: Firmware considers a device "connected" / "fresh" based on incoming valid JSON lines. However, the bridge does not currently send an explicit heartbeat packet.
- Proposed change:
  - Bridge sends a newline-delimited JSON message periodically, e.g.
    {"type":"heartbeat","ts":<unix_or_monotonic_ms>}
  - Firmware updates its last-received timestamp / connected state on any valid JSON line (or explicitly on type=heartbeat), without requiring the active mode payload.
- Benefits:
  - Prevents stale data displays during periods when a particular mode (e.g., weather or stats) does not change.
  - Allows longer push intervals for heavy payloads (especially image/webcam) without showing stale gaps.
- Suggested follow-ups:
  - Update bridge unit/integration tests (if any) to assert heartbeat emission.

2) Reduce webcam/image push cost (safe win)
- Problem: Image mode is heavy due to capture + JPEG encode + base64 transfer over serial.
- Proposed changes (in order of easiest):
  1. Lower JPEG quality / encoder settings in bridge webcam collector (while visually re-checking).
  2. Cap maximum JPEG size (if base64 payload exceeds TTGO/serial limits, re-encode with lower quality until it fits).
  3. With heartbeat implemented, increase image push interval (e.g., from ~30s to ~45–60s) since "freshness" no longer depends solely on image packets.
- Benefits:
  - Lower CPU load on the Raspberry Pi.
  - Lower serial bandwidth usage.
  - Fewer opportunities for serial framing / timeouts.

3) Reduce reliance on the src -> firmware symlink (portability)
- Current approach: repo uses symlink ./src -> ./firmware so PlatformIO and IDEs work with default expectations.
- Proposed improvements:
  - Document the symlink requirement more explicitly in README.
  - Optionally add a pre-build script that creates the symlink automatically when missing (developer experience).
  - (Bigger alternative) adjust PlatformIO configuration so it doesn’t require the symlink, but this can be less portable across tools.

4) Protocol contract refinement (bigger win, optional)
- Current behavior (conceptually): firmware draws only when a packet matches the active mode type.
- Proposed refinement:
  - Firmware stores latest payload per mode in memory.
  - Bridge can push only active mode, or only changed data, while firmware stays responsive.
- Benefits:
  - Less serial traffic.
  - Easier to tune update frequencies per mode.

Suggested next step
Implement #1 (heartbeat) first, then re-tune image intervals and JPEG quality for #2.
