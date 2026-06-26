"""
data_collectors.py — Data sources for each TTGO display mode.

Each collector implements collect() -> dict, which returns a JSON-serializable
dict ready to send over serial. All collectors are designed to fail gracefully:
they catch exceptions and return the last known good data (or a sensible default).
"""

import base64
import io
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# RPi System Stats
# ─────────────────────────────────────────────────────────────────────────────
class StatsCollector:
    def __init__(self):
        # Prime psutil.cpu_percent so the first non-blocking call has a delta
        # to work with (otherwise it returns 0.0).
        try:
            import psutil
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def collect(self) -> dict:
        try:
            import psutil

            # Non-blocking: returns CPU% since the previous call. The push
            # loop runs every 500 ms so the delta window is always fresh.
            # NEVER use interval=0.5 here — it would block the push loop.
            cpu     = psutil.cpu_percent(interval=None)
            vm      = psutil.virtual_memory()
            ram_free = vm.available / 1024 / 1024          # MB
            ram_tot  = vm.total     / 1024 / 1024          # MB
            disk    = psutil.disk_usage("/")
            disk_gb = disk.free  / 1024 / 1024 / 1024      # GB

            temp = 0.0
            try:
                # RPi thermal zone
                raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
                temp = int(raw) / 1000.0
            except Exception:
                try:
                    temps = psutil.sensors_temperatures()
                    if temps:
                        first = next(iter(temps.values()))
                        if first:
                            temp = first[0].current
                except Exception:
                    pass

            # Uptime + load (nice-to-have for the display)
            uptime_sec = 0
            try:
                import psutil
                boot = psutil.boot_time()
                uptime_sec = int(time.time() - boot)
            except Exception:
                uptime_sec = 0

            load1 = load5 = load15 = 0.0
            try:
                load1, load5, load15 = os.getloadavg()  # type: ignore[attr-defined]
            except Exception:
                pass

            return {
                "type":      "stats",
                "cpu":       round(cpu, 1),
                "ram":       round(ram_free, 0),
                "ram_total": round(ram_tot, 0),
                "temp":      round(temp, 1),
                "disk":      round(disk_gb, 1),
                "uptime_sec": int(uptime_sec),
                "load1":     float(load1),
                "load5":     float(load5),
                "load15":    float(load15),
            }
        except Exception as e:
            logger.warning("StatsCollector error: %s", e)
            return {"type": "stats", "cpu": 0, "ram": 0, "ram_total": 1000, "temp": 0, "disk": 0}


# ─────────────────────────────────────────────────────────────────────────────
# Spotify Now Playing — DISABLED
# ─────────────────────────────────────────────────────────────────────────────
# Spotify API polling was removed after Spotify rate-limited (banned) this
# account for excessive request volume from duplicate bridge instances.
# This stub keeps the "spotify" mode slot wired (so firmware protocol is
# unchanged) but never makes any network call. Returns a static payload so
# the display shows "Disabled" rather than stale data.
#
# DO NOT re-enable without: (1) a single canonical bridge instance, (2) a
# long polling interval (≥60s), and (3) an on-device cache. See skill
# `ttgo-chat-controller` → references/ttgo-satellite-bridge-spotify-rate-limit.md
class SpotifyCollector:
    def __init__(self):
        self._payload = {
            "type":         "spotify",
            "track":        "Spotify disabled",
            "artist":       "",
            "playing":      False,
            "progress_pct": 0,
            "progress_sec": 0,
            "duration_sec": 0,
        }

    def collect(self) -> dict:
        return self._payload


# ─────────────────────────────────────────────────────────────────────────────
# Weather — Home Assistant sensors
# ─────────────────────────────────────────────────────────────────────────────
class WeatherCollector:
    # Sensor entity IDs to fetch from HA
    SENSORS = {
        "temp_out": "sensor.outdoor_temp",
        "hum_out":  "sensor.outdoor_humidity",
        "temp_in":  "sensor.living_room_temp",
        "hum_in":   "sensor.living_room_humidity",
        "aqi":      "sensor.living_room_aqi",
    }

    def __init__(self):
        self._last = {"type": "weather"}

    def collect(self) -> dict:
        hass_url   = os.environ.get("HASS_URL",   "http://homeassistant.local:8123").rstrip("/")
        hass_token = os.environ.get("HASS_TOKEN", "")
        if not hass_token:
            return self._last

        try:
            import requests
            headers = {"Authorization": f"Bearer {hass_token}", "Content-Type": "application/json"}
            data = {"type": "weather"}

            # Single /api/states call instead of one GET per sensor:
            # - 1 HTTP round-trip instead of 5 (5× faster, 5× less chance
            #   of blocking the push loop on a slow/unreachable HA).
            # - 2.5s total timeout instead of up to 25s worst-case.
            # - Returns ~all entities; filter client-side.
            wanted = set(self.SENSORS.values())
            r = requests.get(f"{hass_url}/api/states",
                             headers=headers, timeout=2.5)
            if r.status_code != 200:
                return self._last

            states_by_id = {}
            for entry in r.json():
                eid = entry.get("entity_id")
                if eid in wanted:
                    states_by_id[eid] = entry.get("state", "unavailable")

            for key, entity_id in self.SENSORS.items():
                state = states_by_id.get(entity_id, "unavailable")
                if state in ("unavailable", "unknown", None):
                    continue
                try:
                    data[key] = float(state) if "." in str(state) else int(state)
                except (TypeError, ValueError):
                    pass

            if len(data) > 1:   # got at least one sensor
                self._last = data
            return self._last

        except Exception as e:
            logger.warning("WeatherCollector error: %s", e)
            return self._last


# ─────────────────────────────────────────────────────────────────────────────
# Webcam — JPEG snapshot from /dev/video0
# ─────────────────────────────────────────────────────────────────────────────
class WebcamCollector:
    TARGET_W  = 135
    TARGET_H  = 240
    QUALITY   = 50    # JPEG quality 1-95 (lower reduces ringing/artifacts)
    DEVICE    = "/dev/video0"
    WARMUP_FRAMES = 10  # discard first N frames — C920 needs AE/AF to settle after open

    # Firmware currently has tight RAM/serial limits:
    #  - SerialProtocol input buffer: 16KB line (SP_BUF_SIZE)
    #  - Image decode heap buffer: 14KB (IMG_DECODE_BUF)
    #
    # To make sure images reliably decode, we cap JPEG payload size so
    # the full JSON line + base64 fits and the JPEG is not truncated.
    MAX_JPEG_BYTES = 11000
    MIN_QUALITY = 10

    def __init__(self):
        self._last_b64: Optional[str] = None
        self._last_capture = 0.0
        self._cache_ttl    = 30.0   # re-capture at most every 30s on mode entry

    def collect(self) -> Optional[dict]:
        """Returns image dict, or None if capture failed."""
        now = time.time()
        if self._last_b64 and (now - self._last_capture) < self._cache_ttl:
            return {"type": "image", "jpeg_b64": self._last_b64}

        b64 = self._capture()
        if b64 is None:
            if self._last_b64:
                logger.info("WebcamCollector: capture failed; reusing cached image")
                return {"type": "image", "jpeg_b64": self._last_b64}
            logger.warning("WebcamCollector: capture failed; no cached image")
            return None

        self._last_b64     = b64
        self._last_capture = now

        # Helpful for debugging truncation/serial size limits.
        try:
            jpeg_bytes_len = int(len(b64) * 3 / 4)
        except Exception:
            jpeg_bytes_len = -1
        logger.info("WebcamCollector: captured image payload ~%d bytes (b64 chars=%d)", jpeg_bytes_len, len(b64))

        return {"type": "image", "jpeg_b64": b64}

    def invalidate_cache(self):
        """Force a fresh capture next time (called on mode entry)."""
        self._last_capture = 0.0

    def _capture(self) -> Optional[str]:
        """Capture one frame from /dev/video0, resize, JPEG-encode, base64.
        Opens and releases the camera each time — do NOT keep it open, as
        a persistent handle blocks re-open attempts from the same process.
        """
        try:
            try:
                import cv2
                # Retry open — USB autosuspend can cause the first attempt to fail
                cap = None
                for attempt in range(3):
                    cap = cv2.VideoCapture(self.DEVICE)
                    if cap.isOpened():
                        break
                    cap.release()
                    logger.debug("Camera open attempt %d failed, retrying...", attempt + 1)
                    time.sleep(0.5)
                if cap is None or not cap.isOpened():
                    raise RuntimeError("cv2: could not open camera after retries")
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                # Read warmup frames so C920 AE/AF can settle, then take the last good one.
                frame = None
                for _ in range(self.WARMUP_FRAMES):
                    ok, f = cap.read()
                    if ok and f is not None:
                        frame = f   # always keep the latest frame
                cap.release()

                if frame is None:
                    raise RuntimeError("cv2 capture failed after retry")

                # Resize to fill 135×240 (portrait), crop center
                fh, fw = frame.shape[:2]
                scale  = max(self.TARGET_W / fw, self.TARGET_H / fh)
                nw, nh = int(fw * scale), int(fh * scale)
                frame  = cv2.resize(frame, (nw, nh))
                cx, cy = (nw - self.TARGET_W) // 2, (nh - self.TARGET_H) // 2
                frame  = frame[cy:cy + self.TARGET_H, cx:cx + self.TARGET_W]

                # Encode with quality backoff so JPEG fits the TTGO serial + RAM limits.
                # (If JPEG is too large, base64 line gets truncated in SerialProtocol and/or
                # the decoded JPEG buffer on the ESP32 gets truncated.)
                q = int(self.QUALITY)
                for _try in range(6):
                    ok, buf = cv2.imencode(
                        ".jpg",
                        frame,
                        [cv2.IMWRITE_JPEG_QUALITY, max(self.MIN_QUALITY, q)],
                    )
                    if not ok:
                        raise RuntimeError("cv2 encode failed")

                    jpeg_bytes = buf.tobytes()
                    if len(jpeg_bytes) <= self.MAX_JPEG_BYTES:
                        return base64.b64encode(jpeg_bytes).decode("ascii")

                    # Too big — lower quality and try again.
                    q = q - 10
                    time.sleep(0.05)

                # If still too large, send the smallest we got (but log a warning).
                logger.warning(
                    "JPEG still too large for TTGO limits (%d bytes > %d); sending truncated-safe smallest attempt",
                    len(jpeg_bytes), self.MAX_JPEG_BYTES,
                )
                return base64.b64encode(jpeg_bytes[: self.MAX_JPEG_BYTES]).decode("ascii")


            except ImportError:
                pass

            # Fallback: ffmpeg subprocess
            # ffmpeg fallback: try to keep JPEG payload under TTGO limits.
            # We'll start from requested quality and (rarely) back off if too large.
            # Note: ffmpeg -q:v is a quality scale (lower is better/less compression).
            q = max(1, int((100 - self.QUALITY) / 10))
            last = None
            for _try in range(6):
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "v4l2",
                        "-i",
                        "/dev/video0",
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={self.TARGET_W}:{self.TARGET_H}:force_original_aspect_ratio=increase,"
                        f"crop={self.TARGET_W}:{self.TARGET_H}",
                        "-q:v",
                        str(q),
                        "-f",
                        "image2",
                        "pipe:1",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                last = result
                if result.returncode != 0 or not result.stdout:
                    break

                jpeg_bytes = result.stdout
                if len(jpeg_bytes) <= self.MAX_JPEG_BYTES:
                    return base64.b64encode(jpeg_bytes).decode("ascii")

                # Too big — make JPEG more compressed (increase q)
                q += 3
                time.sleep(0.05)

            # If fallback still too large, send truncated-safe bytes.
            if last and last.returncode == 0 and last.stdout:
                jpeg_bytes = last.stdout
                if len(jpeg_bytes) > self.MAX_JPEG_BYTES:
                    logger.warning(
                        "ffmpeg JPEG too large for TTGO limits (%d bytes > %d); truncating",
                        len(jpeg_bytes),
                        self.MAX_JPEG_BYTES,
                    )
                    jpeg_bytes = jpeg_bytes[: self.MAX_JPEG_BYTES]
                return base64.b64encode(jpeg_bytes).decode("ascii")
            if result.returncode != 0 or not result.stdout:
                logger.warning("ffmpeg capture failed: %s", result.stderr[:200])
                return None

            return base64.b64encode(result.stdout).decode("ascii")

        except Exception as e:
            logger.warning("WebcamCollector error: %s", e)
            return None
