#!/usr/bin/env python3
"""TTGO Serial Protocol end-to-end harness.

This suite uses a pty pair to simulate the TTGO firmware serial side.
It then runs the *real* Python bridge (TTGOBridge + SerialTransport)
against that simulated device, verifying the JSON protocol contract.

What we validate:
- device_ready causes bridge to push stats payload
- remote set_mode triggers mode_changed on the simulated firmware
  and causes bridge to push mode-specific payloads
- heartbeat emission from the bridge

No external services or audio/camera dependencies are required because
collectors and voice handler are injected as test doubles.
"""

from __future__ import annotations

import json
import os
import pty
import select
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

# ── Virtual TTGO Firmware Simulator ──────────────────────────────────────────


@dataclass
class FirmwareLog:
    received: list[dict] = field(default_factory=list)
    sent: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    received_by_type: dict[str, list[dict]] = field(
        default_factory=lambda: defaultdict(list)
    )


class VirtualTTGO:
    """Simulates the TTGO firmware over a virtual serial port (pty)."""

    def __init__(self, auto_ready: bool = True, ready_delay: float = 0.2):
        self._auto_ready = auto_ready
        self._ready_delay = ready_delay

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.log = FirmwareLog()

        self._master_fd, self._slave_fd = pty.openpty()
        self.device_path = os.ttyname(self._slave_fd)

        self.current_mode = 0

    @property
    def port(self) -> str:
        return self.device_path

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        try:
            os.close(self._slave_fd)
        except OSError:
            pass

    def send_event(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, separators=(",", ":")) + "\n"
        try:
            os.write(self._master_fd, line.encode("utf-8"))
            self.log.sent.append(event)
        except OSError as e:
            self.log.errors.append(f"send_event error: {e}")

    def _run(self) -> None:
        if self._auto_ready:
            time.sleep(self._ready_delay)
            self.send_event({"event": "device_ready"})

        buf = b""
        while self._running:
            try:
                ready, _, _ = select.select([self._master_fd], [], [], 0.1)
                if not ready:
                    continue
                data = os.read(self._master_fd, 4096)
                if not data:
                    break
                buf += data

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue

                    try:
                        obj = json.loads(text)
                        self.log.received.append(obj)
                        msg_type = obj.get("type", "")
                        self.log.received_by_type[msg_type].append(obj)

                        msg_cmd = obj.get("type", "")
                        if msg_cmd == "set_mode":
                            new_mode = obj.get("mode", 0)
                            if isinstance(new_mode, int) and 0 <= new_mode <= 3:
                                self.current_mode = new_mode
                                self.send_event(
                                    {"event": "mode_changed", "mode": new_mode}
                                )
                    except json.JSONDecodeError as e:
                        self.log.errors.append(
                            f"Bad JSON from bridge: {text!r} — {e}"
                        )
            except OSError:
                break

    def wait_for_type(
        self, msg_type: str, timeout: float = 5.0, count: int = 1
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msgs = self.log.received_by_type.get(msg_type, [])
            if len(msgs) >= count:
                return msgs[:count]
            time.sleep(0.05)
        return self.log.received_by_type.get(msg_type, [])


# ── Test doubles (no external deps) ─────────────────────────────────────────


class DummyVoice:
    def on_ptt_start(self):
        return

    def on_ptt_stop(self):
        return


class DummyStatsCollector:
    def collect(self) -> dict[str, Any]:
        return {
            "type": "stats",
            "cpu": 42.5,
            "ram": 1024,
            "ram_total": 4096,
            "temp": 55.3,
            "disk": 100.2,
            "uptime_sec": 123,
            "load1": 0.1,
            "load5": 0.2,
            "load15": 0.3,
        }


class DummySpotifyCollector:
    def collect(self) -> dict[str, Any]:
        return {
            "type": "spotify",
            "track": "Test Song",
            "artist": "Tester",
            "playing": True,
            "progress_pct": 50,
            "progress_sec": 120,
            "duration_sec": 240,
        }


class DummyWeatherCollector:
    def collect(self) -> dict[str, Any]:
        return {
            "type": "weather",
            "temp_out": 22.5,
            "hum_out": 65,
            "temp_in": 21.0,
            "hum_in": 50,
            "aqi": 35,
        }


class DummyImageCollector:
    def __init__(self):
        self.capture_count = 0

    def invalidate_cache(self):
        return

    def collect(self) -> dict[str, Any]:
        self.capture_count += 1
        # Small payload; VirtualTTGO doesn't decode it.
        return {"type": "image", "jpeg_b64": "dGVzdA=="}


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def ttgo() -> VirtualTTGO:
    dev = VirtualTTGO(auto_ready=True, ready_delay=0.2)
    dev.start()
    yield dev
    dev.stop()


@pytest.fixture
def bridge(ttgo: VirtualTTGO):
    # Import inside fixture so the test module can be collected even if
    # optional deps are missing.
    from bridge.ttgo_bridge import TTGOBridge

    stats = DummyStatsCollector()
    spotify = DummySpotifyCollector()
    weather = DummyWeatherCollector()
    image = DummyImageCollector()

    collectors = {
        "stats": stats,
        "spotify": spotify,
        "weather": weather,
        "image": image,
    }

    voice = DummyVoice()

    b = TTGOBridge(
        serial_port=ttgo.port,
        baud=460800,
        collectors=collectors,
        voice=voice,
        enable_periodic_push=False,
        enable_heartbeat=True,
        heartbeat_interval=0.2,
        mode_switch_delay=0.0,
    )

    b.start()
    try:
        yield b, image
    finally:
        b.stop()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_device_ready_pushes_stats(ttgo: VirtualTTGO, bridge):
    bridge_obj, _ = bridge

    msgs = ttgo.wait_for_type("stats", timeout=3, count=1)
    assert len(msgs) >= 1

    payload = msgs[0]
    required = {"type", "cpu", "ram", "ram_total", "temp", "disk"}
    assert required.issubset(set(payload.keys()))
    assert payload["type"] == "stats"
    assert payload["cpu"] == 42.5


def test_set_mode_roundtrip_switches_to_spotify(ttgo: VirtualTTGO, bridge):
    bridge_obj, _ = bridge

    # Wait for initial stats push, then clear before switching
    ttgo.wait_for_type("stats", timeout=3, count=1)
    ttgo.log.received_by_type["spotify"] = []

    bridge_obj.set_mode(1)

    msgs = ttgo.wait_for_type("spotify", timeout=3, count=1)
    assert len(msgs) >= 1
    payload = msgs[0]
    assert payload["type"] == "spotify"
    assert payload["track"] == "Test Song"
    assert payload["playing"] is True


def test_set_mode_image_triggers_image_push_and_no_periodic_image(
    ttgo: VirtualTTGO, bridge
):
    bridge_obj, img_collector = bridge

    ttgo.wait_for_type("stats", timeout=3, count=1)

    # Clear prior image payloads
    ttgo.log.received_by_type["image"] = []
    before = img_collector.capture_count

    bridge_obj.set_mode(3)

    msgs = ttgo.wait_for_type("image", timeout=3, count=1)
    assert len(msgs) >= 1

    # Since periodic push is disabled, we expect only a small number of
    # captures triggered by set_mode/mode_changed.
    cap = img_collector.capture_count - before
    assert cap >= 1
    assert cap <= 3


def test_heartbeat_emitted(ttgo: VirtualTTGO, bridge):
    bridge_obj, _ = bridge

    hb = ttgo.wait_for_type("heartbeat", timeout=2.0, count=3)
    assert len(hb) >= 3
    for msg in hb[:3]:
        assert msg["type"] == "heartbeat"
        assert "ts" in msg
        assert isinstance(msg["ts"], (int, float))


# Debugging aid if something times out
# (Pytest will print this on failure if you uncomment it.)
# def test_dump(ttgo: VirtualTTGO):
#     print(ttgo.log.received)
