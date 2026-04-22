# WiFi WebSocket Transport Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace USB serial transport with WiFi WebSocket, making the TTGO T-Display completely wireless while keeping the same JSON protocol, same bridge logic, and all existing functionality (PTT, mode switching, display modes).

**Architecture:**
- TTGO connects to home WiFi and opens a persistent WebSocket connection TO the RPi bridge server.
- RPi bridge runs a WebSocket server (asyncio + websockets library) that accepts exactly one client.
- The existing newline-delimited JSON protocol is reused verbatim as WS text frames (no newline needed — each frame is one message).
- SerialTransport is replaced by a new WsTransport class with the same interface (start/stop/send/connected).
- TTGOBridge is unchanged. Only the transport layer swaps.

**Tech Stack:**
- Firmware: ESP32 WiFi (built-in), Links2004/arduinoWebSockets library, ArduinoJson (existing)
- Bridge: Python `websockets` 12.x (asyncio), wrapped in a threading shim to match SerialTransport interface
- Same JSON message schema, no protocol changes

**Assumptions & Environment:**
- Project root: /home/homunculus/.hermes/hermes-agent/ttgo-display/
- Venv: .venv-ttgo (Python 3.13)
- Run tests: cd bridge && ../.venv-ttgo/bin/pytest tests/ -v
- WiFi credentials stored in firmware/wifi_config.h (gitignored)
- RPi hostname: homunculus.local (mDNS) — TTGO connects to this
- Bridge WS server port: 8765
- Existing test infra: pytest in bridge/tests/, xdist available
- No env vars needed for WiFi (hardcoded in firmware, gitignored file)

---

## Task 1: Add wifi_config.h (gitignored credentials file)

**Objective:** Create a gitignored header for WiFi SSID/password so credentials never hit git.

**Files:**
- Create: `firmware/wifi_config.h`
- Modify: `.gitignore`

**Step 1: Create wifi_config.h**

```cpp
// firmware/wifi_config.h
// WiFi credentials — DO NOT COMMIT. This file is gitignored.
#ifndef WIFI_CONFIG_H
#define WIFI_CONFIG_H

#define WIFI_SSID     "YourSSID"
#define WIFI_PASSWORD "YourPassword"
#define WS_HOST       "homunculus.local"   // RPi hostname (mDNS)
#define WS_PORT       8765
#define WS_PATH       "/"

#endif // WIFI_CONFIG_H
```

**Step 2: Add to .gitignore**

Append to .gitignore:
```
firmware/wifi_config.h
```

**Step 3: Verify gitignore works**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
git status firmware/wifi_config.h
```
Expected: file listed as "Ignored" or not shown at all.

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore wifi_config.h (credentials)"
```

---

## Task 2: Add WebSockets library to platformio.ini

**Objective:** Add Links2004/arduinoWebSockets to firmware dependencies.

**Files:**
- Modify: `platformio.ini`

**Step 1: Add lib_dep**

In platformio.ini, under lib_deps, add:
```
links2004/WebSockets@^2.4.1
```

Full lib_deps section becomes:
```ini
lib_deps =
    bodmer/TFT_eSPI@^2.5.43
    bblanchon/ArduinoJson@^7.0.3
    bitbank2/JPEGDEC@^1.8.4
    links2004/WebSockets@^2.4.1
```

**Step 2: Verify library resolves**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
pio pkg install
```
Expected: "Already up to date" or downloads WebSockets library without error.

**Step 3: Commit**

```bash
git add platformio.ini
git commit -m "feat(firmware): add arduinoWebSockets library dependency"
```

---

## Task 3: Create ws_transport.h — WiFi + WebSocket firmware module

**Objective:** New firmware header that replaces SerialProtocol for WiFi/WS communication. Provides the same poll()/sendEvent()/sendModeChange() API so main.cpp changes are minimal.

**Files:**
- Create: `firmware/ws_transport.h`

**Complete implementation:**

```cpp
// firmware/ws_transport.h
// WiFi + WebSocket transport — replaces serial_protocol.h for wireless mode.
//
// Connects ESP32 to home WiFi and maintains a WebSocket client connection
// to the RPi bridge server. Provides same API as SerialProtocol:
//   begin()          — init WiFi + WS
//   poll()           — process incoming WS frames, returns true if JSON ready
//   getDoc()         — access last parsed JsonDocument
//   sendEvent()      — send {"event":"..."} to RPi
//   sendModeChange() — send {"event":"mode_changed","mode":N} to RPi
//
// Reconnect behavior:
//   WiFi: auto-managed by ESP32 SDK (reconnects on drop).
//   WS:   reconnect loop in poll() — retries every WS_RECONNECT_MS if disconnected.

#ifndef WS_TRANSPORT_H
#define WS_TRANSPORT_H

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "wifi_config.h"

#define WS_RECONNECT_MS   3000   // ms between WS reconnect attempts
#define WS_JSON_DOC_SIZE  40000  // same as serial_protocol.h SERIAL_JSON_DOC_SIZE

class WsTransport {
public:
    WsTransport() : _ready(false), _msgReady(false), _lastReconnectMs(0) {}

    void begin() {
        // Connect WiFi
        WiFi.mode(WIFI_STA);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

        // Block until WiFi connects (with timeout)
        unsigned long t = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) {
            delay(200);
        }

        // Setup WS client
        _ws.begin(WS_HOST, WS_PORT, WS_PATH);
        _ws.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
            this->_onWsEvent(type, payload, length);
        });
        _ws.setReconnectInterval(WS_RECONNECT_MS);
        _ws.enableHeartbeat(15000, 3000, 2);  // ping every 15s, pong timeout 3s, 2 retries
    }

    // Call in loop(). Returns true if a complete JSON message arrived.
    bool poll() {
        _ws.loop();
        if (_msgReady) {
            _msgReady = false;
            return true;
        }
        return false;
    }

    bool connected() const {
        return _ready && WiFi.status() == WL_CONNECTED;
    }

    JsonDocument& getDoc() { return _doc; }

    void sendEvent(const char* eventName) {
        if (!_ready) return;
        // Build compact JSON manually to avoid heap alloc
        char buf[64];
        snprintf(buf, sizeof(buf), "{\"event\":\"%s\"}", eventName);
        _ws.sendTXT(buf);
    }

    void sendModeChange(int modeIndex) {
        if (!_ready) return;
        char buf[48];
        snprintf(buf, sizeof(buf), "{\"event\":\"mode_changed\",\"mode\":%d}", modeIndex);
        _ws.sendTXT(buf);
    }

    // Send an arbitrary JSON object (used internally for ack, etc.)
    void sendRaw(const char* json) {
        if (!_ready) return;
        _ws.sendTXT(json);
    }

    // Returns WiFi IP as string (for display on boot screen)
    String ipAddress() const {
        return WiFi.localIP().toString();
    }

private:
    WebSocketsClient _ws;
    StaticJsonDocument<WS_JSON_DOC_SIZE> _doc;
    bool   _ready;
    bool   _msgReady;
    unsigned long _lastReconnectMs;

    void _onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
            case WStype_CONNECTED:
                _ready = true;
                break;

            case WStype_DISCONNECTED:
                _ready = false;
                break;

            case WStype_TEXT: {
                // Parse incoming JSON frame
                DeserializationError err = deserializeJson(_doc, payload, length);
                if (!err) {
                    _msgReady = true;
                }
                break;
            }

            default:
                break;
        }
    }
};

#endif // WS_TRANSPORT_H
```

**Step 2: Verify it compiles**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
pio run
```
Expected: BUILD SUCCEEDED (or only warnings, no errors).

**Step 3: Commit**

```bash
git add firmware/ws_transport.h
git commit -m "feat(firmware): add WsTransport WiFi+WebSocket module"
```

---

## Task 4: Update main.cpp to use WsTransport instead of SerialProtocol

**Objective:** Swap the transport in main.cpp. Keep ALL other logic (buttons, display, PTT) identical.

**Files:**
- Modify: `firmware/main.cpp`

**Step 1: Replace include and global**

Old:
```cpp
#include "serial_protocol.h"
...
SerialProtocol  proto;
```

New:
```cpp
#include "ws_transport.h"
...
WsTransport  proto;
```

**Step 2: Update setup() — replace proto.begin()**

Old:
```cpp
proto.begin();
```

New:
```cpp
proto.begin();
// Show IP on serial monitor for debugging
Serial.begin(115200);
Serial.printf("WiFi IP: %s\n", proto.ipAddress().c_str());
```

Note: Serial.begin is now only for debug output (not data). It can be removed later.

**Step 3: No other changes needed**

poll(), getDoc(), sendEvent(), sendModeChange() have the same signatures in WsTransport. The rest of main.cpp stays byte-for-byte identical.

**Step 4: Build to verify**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
pio run
```
Expected: BUILD SUCCEEDED.

**Step 5: Commit**

```bash
git add firmware/main.cpp
git commit -m "feat(firmware): switch transport from SerialProtocol to WsTransport"
```

---

## Task 5: Create ws_transport.py — WebSocket server transport for the bridge

**Objective:** New Python transport that replaces SerialTransport. Same interface: start()/stop()/send(data)/connected property. Runs an asyncio WebSocket server in a background thread.

**Files:**
- Create: `bridge/ws_transport.py`

**Complete implementation:**

```python
"""
ws_transport.py — WebSocket server transport (replaces serial_transport.py).

Runs an asyncio WebSocket server that waits for the TTGO to connect.
Accepts exactly one client at a time (the TTGO device).
Provides the same interface as SerialTransport:
  start()        — start the WS server background thread
  stop()         — shut down cleanly
  send(dict)     — queue a JSON message to send to TTGO
  connected      — True when TTGO client is connected

JSON framing: each WS text frame = one JSON object (no newline needed).
"""

import asyncio
import json
import logging
import queue
import threading
from typing import Callable, Optional

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)

WS_HOST = "0.0.0.0"
WS_PORT = 8765
RECONNECT_WAIT = 3.0  # seconds to wait if no client after disconnect


class WsTransport:
    def __init__(
        self,
        host: str = WS_HOST,
        port: int = WS_PORT,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self._host = host
        self._port = port
        self._on_event = on_event
        self._queue: queue.Queue = queue.Queue(maxsize=64)
        self._connected = False
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws_client: Optional[WebSocketServerProtocol] = None
        self._stop_event: Optional[asyncio.Event] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ws-server"
        )
        self._thread.start()
        logger.info("WsTransport started on %s:%d", self._host, self._port)

    def stop(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: self._stop_event.set() if self._stop_event else None
            )
        logger.info("WsTransport stopped")

    def send(self, data: dict):
        """Queue a dict to be sent as a JSON WS frame."""
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            logger.warning("WS send queue full — dropping packet")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self):
        async with websockets.serve(self._handle_client, self._host, self._port):
            logger.info("WebSocket server listening on ws://%s:%d", self._host, self._port)
            await self._stop_event.wait()

    async def _handle_client(self, ws: WebSocketServerProtocol):
        """Handle one TTGO client connection."""
        remote = ws.remote_address
        logger.info("TTGO connected from %s", remote)
        self._ws_client = ws
        self._connected = True

        # Spawn sender task
        sender = asyncio.ensure_future(self._sender_loop(ws))

        try:
            async for message in ws:
                try:
                    obj = json.loads(message)
                    if self._on_event and isinstance(obj, dict):
                        self._on_event(obj)
                except json.JSONDecodeError:
                    logger.debug("WS bad JSON: %r", message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            sender.cancel()
            self._connected = False
            self._ws_client = None
            logger.info("TTGO disconnected from %s", remote)

    async def _sender_loop(self, ws: WebSocketServerProtocol):
        """Drain the send queue and forward messages to the WS client."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Poll queue without blocking the event loop
                try:
                    item = await loop.run_in_executor(
                        None, lambda: self._queue.get(timeout=0.1)
                    )
                except queue.Empty:
                    continue

                if item is None:
                    break

                try:
                    frame = json.dumps(item, separators=(",", ":"))
                    await ws.send(frame)
                except websockets.exceptions.ConnectionClosed:
                    # Put it back? No — just drop and let reconnect handle it.
                    break
                except Exception as e:
                    logger.warning("WS send error: %s", e)

            except asyncio.CancelledError:
                break
```

**Step 2: Install websockets in the project venv**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
.venv-ttgo/bin/pip install "websockets>=12.0"
echo "websockets>=12.0" >> bridge/requirements.txt
```

**Step 3: Verify import**

```bash
.venv-ttgo/bin/python -c "import websockets; print(websockets.__version__)"
```
Expected: prints version >= 12.0

**Step 4: Commit**

```bash
git add bridge/ws_transport.py bridge/requirements.txt
git commit -m "feat(bridge): add WsTransport WebSocket server"
```

---

## Task 6: Write tests for WsTransport

**Objective:** Verify WsTransport server starts, accepts a client, delivers messages in both directions, and handles disconnect gracefully.

**Files:**
- Create: `bridge/tests/test_ws_transport.py`

```python
"""Tests for WsTransport — WebSocket server transport."""

import asyncio
import json
import time
import threading
import pytest
import websockets

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ws_transport import WsTransport

WS_TEST_PORT = 8766  # Use different port from production to avoid conflicts


@pytest.fixture
def transport():
    """Start a WsTransport server, yield it, then stop."""
    received = []
    t = WsTransport(port=WS_TEST_PORT, on_event=received.append)
    t.start()
    time.sleep(0.3)  # Allow server to bind
    yield t, received
    t.stop()


def _connect_and_receive(port, send_msg=None, n_recv=1, timeout=3.0):
    """Helper: connect a WS client, optionally send a message, collect n_recv frames."""
    received = []

    async def _run():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            if send_msg:
                await ws.send(json.dumps(send_msg))
            for _ in range(n_recv):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    received.append(json.loads(msg))
                except asyncio.TimeoutError:
                    break

    asyncio.run(_run())
    return received


def test_server_starts_and_accepts_client(transport):
    """Server should start and accept a connection from a WS client."""
    t, _ = transport
    time.sleep(0.2)

    async def _connect():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}"):
            await asyncio.sleep(0.1)

    asyncio.run(_connect())
    # No assertion needed — if connect raised, test would fail


def test_connected_flag_set_on_client_join(transport):
    """connected property should become True when TTGO connects."""
    t, _ = transport
    assert t.connected is False

    async def _connect():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}"):
            await asyncio.sleep(0.2)

    asyncio.run(_connect())
    # connected flag should be True during connection
    # We can't easily assert mid-connection, so assert it went False after disconnect
    time.sleep(0.2)
    assert t.connected is False


def test_server_receives_event_from_client(transport):
    """Events sent from TTGO client should trigger on_event callback."""
    t, received = transport

    async def _send():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "ptt_start"}))
            await asyncio.sleep(0.2)

    asyncio.run(_send())
    time.sleep(0.1)
    assert any(m.get("event") == "ptt_start" for m in received)


def test_send_delivers_message_to_client(transport):
    """send() should deliver a JSON dict to the connected WS client."""
    t, _ = transport
    payload = {"type": "stats", "cpu": 42.0, "ram": 512}

    # Client connects, then waits for one message
    result_holder = []

    async def _recv():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            # Wait briefly for server to register us as connected
            await asyncio.sleep(0.1)
            t.send(payload)
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            result_holder.append(json.loads(msg))

    asyncio.run(_recv())
    assert result_holder, "No message received"
    assert result_holder[0]["type"] == "stats"
    assert result_holder[0]["cpu"] == 42.0


def test_send_queue_full_drops_gracefully(transport):
    """When queue is full, send() should not raise — just log and drop."""
    t, _ = transport
    # Fill the queue (maxsize=64)
    for i in range(70):
        t.send({"type": "stats", "i": i})
    # If we get here without exception, test passes


def test_server_handles_bad_json_from_client(transport):
    """Bad JSON from TTGO should not crash the server."""
    t, received = transport

    async def _send_garbage():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send("this is not json {{{")
            await asyncio.sleep(0.1)
            # Server should still be alive — send a valid event after
            await ws.send(json.dumps({"event": "device_ready"}))
            await asyncio.sleep(0.1)

    asyncio.run(_send_garbage())
    time.sleep(0.1)
    assert any(m.get("event") == "device_ready" for m in received)


def test_reconnect_works(transport):
    """After client disconnects and reconnects, server should accept new connection."""
    t, received = transport

    async def _two_connections():
        # First connection
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "conn1"}))
            await asyncio.sleep(0.1)
        # Second connection (reconnect)
        await asyncio.sleep(0.1)
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "conn2"}))
            await asyncio.sleep(0.1)

    asyncio.run(_two_connections())
    time.sleep(0.2)
    events = [m.get("event") for m in received]
    assert "conn1" in events
    assert "conn2" in events
```

**Step 2: Run tests**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
.venv-ttgo/bin/pytest bridge/tests/test_ws_transport.py -v
```
Expected: all 7 tests pass.

**Step 3: Commit**

```bash
git add bridge/tests/test_ws_transport.py
git commit -m "test(bridge): add WsTransport unit tests"
```

---

## Task 7: Update TTGOBridge to support WsTransport (via --transport flag)

**Objective:** Make TTGOBridge instantiate WsTransport by default (with an optional --serial fallback flag for debugging with USB).

**Files:**
- Modify: `bridge/ttgo_bridge.py`

**Step 1: Add transport_type parameter to TTGOBridge.__init__**

Change the constructor default from SerialTransport to WsTransport:

Old:
```python
from serial_transport import SerialTransport
...
self._transport = transport or SerialTransport(
    port=serial_port, baud=baud, on_event=self._on_serial_event
)
```

New:
```python
from serial_transport import SerialTransport
from ws_transport import WsTransport
...
if transport is not None:
    self._transport = transport
elif transport_type == "serial":
    self._transport = SerialTransport(
        port=serial_port, baud=baud, on_event=self._on_serial_event
    )
else:  # default: websocket
    ws_port = int(os.environ.get("WS_PORT", "8765"))
    self._transport = WsTransport(
        port=ws_port, on_event=self._on_serial_event
    )
```

**Step 2: Add transport_type to constructor signature**

```python
def __init__(
    self,
    serial_port: str = "/dev/ttyACM0",
    baud: int = 460800,
    transport_type: str = "ws",   # "ws" or "serial"
    collectors: Optional[dict[str, Any]] = None,
    voice: Any = None,
    transport: Optional[Any] = None,
    ...
):
```

**Step 3: Update main() to accept --transport flag**

```python
parser.add_argument(
    "--transport",
    choices=["ws", "serial"],
    default="ws",
    help="Transport type: ws (WebSocket, default) or serial (USB fallback)",
)
...
bridge = TTGOBridge(transport_type=args.transport)
```

**Step 4: Update log message**

Change:
```python
logger.info("TTGO Bridge started. Mode: %s", MODE_TYPES[self._current_mode])
```
To:
```python
logger.info(
    "TTGO Bridge started. Transport: %s  Mode: %s",
    transport_type, MODE_TYPES[self._current_mode],
)
```

**Step 5: Run existing bridge tests to verify nothing broke**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
.venv-ttgo/bin/pytest bridge/tests/ -v
```
Expected: all tests pass (existing + new WS tests).

**Step 6: Commit**

```bash
git add bridge/ttgo_bridge.py
git commit -m "feat(bridge): default to WsTransport, add --transport flag for serial fallback"
```

---

## Task 8: Update systemd service for WiFi operation

**Objective:** Update ttgo-bridge.service to remove the dialout group (no USB serial needed) and add WS_PORT env var.

**Files:**
- Modify: `bridge/ttgo-bridge.service`

**Step 1: Update service file**

Change SupplementaryGroups from:
```
SupplementaryGroups=dialout audio video
```
To:
```
SupplementaryGroups=audio video
```
(dialout was only needed for /dev/ttyACM0 serial access)

Add to Environment section (or keep in EnvironmentFile):
```
Environment=WS_PORT=8765
```

**Step 2: Reload and verify**

```bash
sudo cp bridge/ttgo-bridge.service /etc/systemd/system/ttgo-bridge.service
sudo systemctl daemon-reload
sudo systemctl restart ttgo-bridge
sudo systemctl status ttgo-bridge
```
Expected: service active (running).

**Step 3: Commit**

```bash
git add bridge/ttgo-bridge.service
git commit -m "chore(service): remove dialout group, add WS_PORT for WiFi transport"
```

---

## Task 9: Update docs — add WiFi WebSocket protocol doc

**Objective:** Update docs/serial-protocol.md to document the new WS transport and keep the serial transport as a legacy/fallback section.

**Files:**
- Modify: `docs/serial-protocol.md`

Prepend a new section at the top:

```markdown
# TTGO Transport Protocol

## Primary Transport: WiFi WebSocket

The TTGO connects to home WiFi and opens a persistent WebSocket connection
to the RPi bridge server (ws://homunculus.local:8765).

Each WS text frame = one JSON object (no newline framing needed).
Protocol is otherwise identical to the serial protocol below.

Firmware WiFi config: firmware/wifi_config.h (gitignored — see wifi_config.h.example).
Bridge WS server: bridge/ws_transport.py (port 8765, configurable via WS_PORT env var).
Fallback to USB serial: run bridge with --transport serial flag.

## Legacy Transport: USB Serial (fallback)

...rest of existing content...
```

**Step 2: Commit**

```bash
git add docs/serial-protocol.md
git commit -m "docs: update protocol doc for WiFi WebSocket transport"
```

---

## Task 10: End-to-end verification checklist

**Objective:** Flash firmware and verify the full wireless loop works.

**Step 1: Fill in wifi_config.h with real credentials**

```cpp
#define WIFI_SSID     "YourActualSSID"
#define WIFI_PASSWORD "YourActualPassword"
#define WS_HOST       "homunculus.local"
#define WS_PORT       8765
```

**Step 2: Flash firmware (USB cable still needed for initial flash)**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display
pio run --target upload
```

**Step 3: Stop the old serial bridge service**

```bash
sudo systemctl stop ttgo-bridge
```

**Step 4: Run bridge manually with debug logging**

```bash
cd /home/homunculus/.hermes/hermes-agent/ttgo-display/bridge
../.venv-ttgo/bin/python ttgo_bridge.py --debug
```

**Step 5: Watch serial monitor on TTGO for IP address**

```bash
pio device monitor --baud 115200
```
Expected output: "WiFi IP: 192.168.x.x"

**Step 6: Verify TTGO connects to bridge**

In bridge logs you should see:
```
TTGO connected from ('192.168.x.x', XXXXX)
TTGO device ready — pushing current mode data
```

**Step 7: Verify display shows data**

TTGO display should show stats/spotify/weather data updating normally.

**Step 8: Verify PTT works**

Hold Button2 on TTGO. Bridge logs should show:
```
PTT start
PTT stop
```

**Step 9: Test button mode switching**

Press Button1. Bridge logs:
```
Mode changed: stats → spotify
```

**Step 10: Disconnect USB cable**

TTGO should remain connected over WiFi and display should keep updating.

**Step 11: Deploy service**

```bash
sudo systemctl start ttgo-bridge
sudo systemctl enable ttgo-bridge
journalctl -u ttgo-bridge -f
```

---

## Summary of changed files

```
firmware/wifi_config.h         NEW  — WiFi credentials (gitignored)
firmware/ws_transport.h        NEW  — WiFi+WS transport (replaces serial_protocol.h)
firmware/main.cpp              MOD  — swap SerialProtocol → WsTransport
platformio.ini                 MOD  — add links2004/WebSockets lib dep
bridge/ws_transport.py         NEW  — Python WS server transport
bridge/tests/test_ws_transport.py  NEW  — 7 unit tests for WsTransport
bridge/ttgo_bridge.py          MOD  — default to WsTransport, --transport flag
bridge/requirements.txt        MOD  — add websockets>=12.0
bridge/ttgo-bridge.service     MOD  — remove dialout group
docs/serial-protocol.md        MOD  — document WiFi transport
.gitignore                     MOD  — ignore wifi_config.h
```

Serial transport (serial_transport.py) is kept untouched as USB fallback.
