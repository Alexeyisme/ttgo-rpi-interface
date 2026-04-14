#!/usr/bin/env python3
"""
TTGO Serial Protocol Test Harness

Uses Python pty module to create a virtual serial port pair,
simulating TTGO firmware behaviour for testing the bridge without hardware.

Virtual firmware behaviour:
  - Sends {"event":"device_ready"} on connect
  - Responds to {"type":"set_mode","mode":N} with {"event":"mode_changed","mode":N}
  - Validates all incoming JSON
  - Logs all received data to a list for assertions

Pytest tests exercise the serial protocol contract:
  - test_stats_push:       stats data arrives within 5s
  - test_mode_switch:      mode_changed tracking
  - test_all_modes_pushed: all 4 mode types get pushed
  - test_heartbeat:        heartbeat for slow modes
  - test_set_mode:         set_mode command works

Usage:
    /home/homunculus/.hermes/hermes-agent/venv/bin/python -m pytest test_harness.py -v
"""

import json
import os
import pty
import select
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import pytest


# ── Virtual TTGO Firmware Simulator ──────────────────────────────────────────

@dataclass
class FirmwareLog:
    """Collects everything the firmware received/sent for test assertions."""
    received: list = field(default_factory=list)
    sent: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    received_by_type: dict = field(default_factory=lambda: defaultdict(list))


class VirtualTTGO:
    """
    Simulates TTGO firmware over a virtual serial port pair.

    Creates a pty pair: one end acts as the "device" (firmware), the other
    is exposed as a file path that the bridge can open like /dev/ttyACM0.
    """

    def __init__(self, auto_ready: bool = True, ready_delay: float = 0.3):
        self._auto_ready = auto_ready
        self._ready_delay = ready_delay
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.log = FirmwareLog()

        # Create pty pair
        self._master_fd, self._slave_fd = pty.openpty()
        self.device_path = os.ttyname(self._slave_fd)

        # Current mode tracked by the virtual firmware
        self.current_mode = 0

    @property
    def port(self) -> str:
        """Path to the virtual serial port (slave end) — pass this to SerialTransport."""
        return self.device_path

    def start(self):
        """Start the firmware simulation loop."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="virtual-ttgo")
        self._thread.start()

    def stop(self):
        """Stop the firmware simulation and close fds."""
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

    def send_event(self, event: dict):
        """Send a JSON event from the firmware to the bridge."""
        line = json.dumps(event, separators=(",", ":")) + "\n"
        try:
            os.write(self._master_fd, line.encode("utf-8"))
            self.log.sent.append(event)
        except OSError as e:
            self.log.errors.append(f"send_event error: {e}")

    def _run(self):
        """Main firmware loop: read from master, parse JSON, respond."""
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
                # Process complete lines
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

                        # Handle set_mode command
                        if msg_type == "set_mode":
                            new_mode = obj.get("mode", 0)
                            if isinstance(new_mode, int) and 0 <= new_mode <= 3:
                                self.current_mode = new_mode
                                self.send_event({
                                    "event": "mode_changed",
                                    "mode": new_mode,
                                })

                    except json.JSONDecodeError as e:
                        self.log.errors.append(f"Bad JSON from bridge: {text!r} — {e}")

            except OSError:
                break

    def wait_for_type(self, msg_type: str, timeout: float = 5.0, count: int = 1) -> list:
        """Block until we've received `count` messages of `msg_type`, or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msgs = self.log.received_by_type.get(msg_type, [])
            if len(msgs) >= count:
                return msgs[:count]
            time.sleep(0.1)
        return self.log.received_by_type.get(msg_type, [])

    def wait_for_any(self, timeout: float = 5.0, count: int = 1) -> list:
        """Block until we've received `count` messages of any type, or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.log.received) >= count:
                return self.log.received[:count]
            time.sleep(0.1)
        return list(self.log.received)


# ── Lightweight Bridge Client (sends JSON lines to virtual port) ─────────────

class BridgeClient:
    """
    Minimal bridge-side serial writer/reader for testing.
    Opens the slave side of the pty (same path as VirtualTTGO.port).
    """

    def __init__(self, port_path: str):
        self._fd = os.open(port_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.received: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start_reader(self):
        """Start a background thread reading events from the device."""
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="bridge-reader")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        try:
            os.close(self._fd)
        except OSError:
            pass

    def send(self, data: dict):
        """Send a JSON line to the device."""
        line = json.dumps(data, separators=(",", ":")) + "\n"
        os.write(self._fd, line.encode("utf-8"))

    def _read_loop(self):
        buf = b""
        while self._running:
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.1)
                if not ready:
                    continue
                data = os.read(self._fd, 4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        try:
                            self.received.append(json.loads(text))
                        except json.JSONDecodeError:
                            pass
            except (OSError, BlockingIOError):
                time.sleep(0.05)

    def wait_for_event(self, event_name: str, timeout: float = 5.0) -> Optional[dict]:
        """Wait until we receive an event with the given name."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self.received:
                if msg.get("event") == event_name:
                    return msg
            time.sleep(0.1)
        return None


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def ttgo():
    """Create and start a VirtualTTGO, yield it, then stop."""
    device = VirtualTTGO(auto_ready=True, ready_delay=0.2)
    device.start()
    yield device
    device.stop()


@pytest.fixture
def bridge_and_ttgo():
    """Create a paired VirtualTTGO + BridgeClient, ready for testing."""
    device = VirtualTTGO(auto_ready=True, ready_delay=0.2)
    device.start()
    # Small delay to let pty settle
    time.sleep(0.1)
    client = BridgeClient(device.port)
    client.start_reader()
    yield client, device
    client.stop()
    device.stop()


# ── Tests ────────────────────────────────────────────────────────────────────

MODE_TYPES = ["stats", "spotify", "weather", "image"]


class TestStatsPush:
    """test_stats_push: stats data arrives within 5s of being sent."""

    def test_stats_push(self, bridge_and_ttgo):
        client, ttgo = bridge_and_ttgo

        # Wait for device_ready from firmware
        ready = client.wait_for_event("device_ready", timeout=3)
        assert ready is not None, "device_ready not received from virtual firmware"

        # Bridge pushes stats data
        stats_payload = {
            "type": "stats",
            "cpu": 42.5,
            "ram": 1024,
            "ram_total": 4096,
            "temp": 55.3,
            "disk": 100.2,
        }
        client.send(stats_payload)

        # Firmware should receive it within 5s
        msgs = ttgo.wait_for_type("stats", timeout=5, count=1)
        assert len(msgs) >= 1, "Firmware did not receive stats push within 5s"
        assert msgs[0]["type"] == "stats"
        assert msgs[0]["cpu"] == 42.5
        assert msgs[0]["ram"] == 1024

    def test_stats_has_required_fields(self, bridge_and_ttgo):
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        stats_payload = {
            "type": "stats",
            "cpu": 10.0,
            "ram": 512,
            "ram_total": 2048,
            "temp": 40.0,
            "disk": 50.0,
        }
        client.send(stats_payload)

        msgs = ttgo.wait_for_type("stats", timeout=5, count=1)
        assert len(msgs) >= 1
        required = {"type", "cpu", "ram", "ram_total", "temp", "disk"}
        assert required.issubset(set(msgs[0].keys())), f"Missing fields: {required - set(msgs[0].keys())}"


class TestModeSwitch:
    """test_mode_switch: mode_changed event tracking."""

    def test_mode_switch(self, bridge_and_ttgo):
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        # Send set_mode to switch to spotify (mode 1)
        client.send({"type": "set_mode", "mode": 1})

        # Should get mode_changed back
        mode_evt = client.wait_for_event("mode_changed", timeout=5)
        assert mode_evt is not None, "mode_changed event not received"
        assert mode_evt["mode"] == 1

        # Virtual firmware tracks mode
        assert ttgo.current_mode == 1

    def test_mode_switch_roundtrip(self, bridge_and_ttgo):
        """Cycle through all modes and verify firmware tracks each."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        for mode_idx in range(4):
            client.send({"type": "set_mode", "mode": mode_idx})
            time.sleep(0.3)
            assert ttgo.current_mode == mode_idx, f"Firmware mode should be {mode_idx}, got {ttgo.current_mode}"


class TestAllModesPushed:
    """test_all_modes_pushed: all 4 mode types get pushed and received."""

    def test_all_modes_pushed(self, bridge_and_ttgo):
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        # Push one of each mode type
        payloads = {
            "stats":   {"type": "stats", "cpu": 50, "ram": 1000, "ram_total": 4000, "temp": 50, "disk": 80},
            "spotify": {"type": "spotify", "track": "Test Song", "artist": "Test", "playing": True,
                        "progress_pct": 50, "progress_sec": 120, "duration_sec": 240},
            "weather": {"type": "weather", "temp_out": 22.5, "hum_out": 65, "temp_in": 21.0,
                        "hum_in": 50, "aqi": 35},
            "image":   {"type": "image", "jpeg_b64": "dGVzdA=="},
        }

        for mode_type, payload in payloads.items():
            client.send(payload)
            time.sleep(0.1)

        # Give firmware time to process
        time.sleep(0.5)

        # Verify all 4 types were received
        for mode_type in MODE_TYPES:
            msgs = ttgo.log.received_by_type.get(mode_type, [])
            assert len(msgs) >= 1, f"Firmware did not receive {mode_type} data"

    def test_mode_type_data_integrity(self, bridge_and_ttgo):
        """Ensure each payload arrives with its data intact."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        client.send({"type": "spotify", "track": "Hello World", "artist": "Tester",
                      "playing": False, "progress_pct": 0, "progress_sec": 0, "duration_sec": 180})
        time.sleep(0.3)

        msgs = ttgo.log.received_by_type.get("spotify", [])
        assert len(msgs) >= 1
        assert msgs[0]["track"] == "Hello World"
        assert msgs[0]["artist"] == "Tester"
        assert msgs[0]["playing"] is False


class TestHeartbeat:
    """test_heartbeat: heartbeat for slow-refresh modes."""

    def test_heartbeat(self, bridge_and_ttgo):
        """
        For modes with push interval > 15s (like image at 30s),
        the bridge should send heartbeats to keep the connection alive.
        We simulate this by sending heartbeat packets and verifying
        the firmware receives them.
        """
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        # Simulate the bridge sending heartbeats (type: heartbeat)
        for i in range(3):
            client.send({"type": "heartbeat", "ts": time.time()})
            time.sleep(0.3)

        # Firmware should have received heartbeats
        hb_msgs = ttgo.wait_for_type("heartbeat", timeout=3, count=3)
        assert len(hb_msgs) >= 3, f"Expected 3 heartbeats, got {len(hb_msgs)}"

    def test_heartbeat_has_timestamp(self, bridge_and_ttgo):
        """Heartbeat packets should carry a timestamp."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        ts_before = time.time()
        client.send({"type": "heartbeat", "ts": ts_before})
        time.sleep(0.3)

        msgs = ttgo.wait_for_type("heartbeat", timeout=3, count=1)
        assert len(msgs) >= 1
        assert "ts" in msgs[0]
        assert abs(msgs[0]["ts"] - ts_before) < 1.0


class TestSetMode:
    """test_set_mode: set_mode command works end-to-end."""

    def test_set_mode(self, bridge_and_ttgo):
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        # Send set_mode for each valid mode
        for mode_idx in range(4):
            client.received.clear()  # clear to detect fresh mode_changed
            client.send({"type": "set_mode", "mode": mode_idx})

            # Wait for mode_changed response
            time.sleep(0.5)

            found = False
            for msg in client.received:
                if msg.get("event") == "mode_changed" and msg.get("mode") == mode_idx:
                    found = True
                    break
            assert found, f"set_mode({mode_idx}) did not produce mode_changed event"
            assert ttgo.current_mode == mode_idx

    def test_set_mode_invalid_ignored(self, bridge_and_ttgo):
        """Invalid mode indices should not crash the firmware."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        initial_mode = ttgo.current_mode
        client.send({"type": "set_mode", "mode": 99})
        time.sleep(0.3)

        # Mode should not have changed
        assert ttgo.current_mode == initial_mode

    def test_set_mode_negative_ignored(self, bridge_and_ttgo):
        """Negative mode indices should be ignored."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        initial_mode = ttgo.current_mode
        client.send({"type": "set_mode", "mode": -1})
        time.sleep(0.3)
        assert ttgo.current_mode == initial_mode


class TestProtocolValidation:
    """Additional protocol validation tests."""

    def test_device_ready_on_connect(self, bridge_and_ttgo):
        """Firmware sends device_ready automatically."""
        client, ttgo = bridge_and_ttgo
        ready = client.wait_for_event("device_ready", timeout=3)
        assert ready is not None
        assert ready["event"] == "device_ready"

    def test_invalid_json_logged(self, ttgo):
        """Sending invalid JSON should be logged as an error."""
        # Write garbage directly to the master fd
        os.write(ttgo._master_fd, b"this is not json\n")
        time.sleep(0.5)
        assert len(ttgo.log.errors) >= 1, "Invalid JSON should produce an error log"

    def test_empty_lines_ignored(self, bridge_and_ttgo):
        """Empty lines should not crash anything."""
        client, ttgo = bridge_and_ttgo
        client.wait_for_event("device_ready", timeout=3)

        # Send empty lines
        os.write(os.open(ttgo.port, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK),
                 b"\n\n\n")
        time.sleep(0.3)

        # Firmware should still be running and responsive
        client.send({"type": "stats", "cpu": 1, "ram": 1, "ram_total": 1, "temp": 1, "disk": 1})
        msgs = ttgo.wait_for_type("stats", timeout=3, count=1)
        assert len(msgs) >= 1


# ── Run directly ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
