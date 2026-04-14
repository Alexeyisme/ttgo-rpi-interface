#!/usr/bin/env python3
"""
send_test_data.py — Send test packets to the TTGO T-Display over serial.

Generates realistic data for each display mode and sends newline-delimited
JSON directly to /dev/ttyACM0 (bypassing the bridge).

Usage:
    ./send_test_data.py --mode stats          # stats data for 30s
    ./send_test_data.py --mode spotify         # spotify data for 30s
    ./send_test_data.py --mode weather         # weather data for 30s
    ./send_test_data.py --mode image           # RGB stripe test image
    ./send_test_data.py --mode all             # cycle through all modes
    ./send_test_data.py --mode all --duration 60
    ./send_test_data.py --set-mode 2           # switch display to weather mode
    ./send_test_data.py --mode stats --interval 2  # send every 2s
"""

import argparse
import base64
import io
import json
import math
import random
import signal
import struct
import sys
import time
from pathlib import Path

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200

# ── Test data generators ──────────────────────────────────────────────────────

def gen_stats(t: float) -> dict:
    """Generate realistic RPi system stats with gentle animation."""
    base_cpu = 15 + 10 * math.sin(t * 0.3)
    spike = random.random() * 20 if random.random() < 0.1 else 0
    return {
        "type": "stats",
        "cpu": round(max(0, min(100, base_cpu + spike + random.gauss(0, 2))), 1),
        "ram": round(max(100, min(3800, 1800 + 400 * math.sin(t * 0.1) + random.gauss(0, 50)))),
        "temp": round(max(30, min(80, 48 + 8 * math.sin(t * 0.05) + random.gauss(0, 1))), 1),
        "disk": round(max(1, min(95, 42 + 0.01 * t + random.gauss(0, 0.5))), 1),
    }


def gen_spotify(t: float) -> dict:
    """Generate Spotify playback data with rotating tracks."""
    tracks = [
        ("Bohemian Rhapsody", "Queen"),
        ("Stairway to Heaven", "Led Zeppelin"),
        ("Hotel California", "Eagles"),
        ("Imagine", "John Lennon"),
        ("Billie Jean", "Michael Jackson"),
        ("Smells Like Teen Spirit", "Nirvana"),
        ("Hallelujah", "Jeff Buckley"),
        ("Lose Yourself", "Eminem"),
        ("Rolling in the Deep", "Adele"),
        ("Blinding Lights", "The Weeknd"),
    ]
    idx = int(t / 15) % len(tracks)  # change track every 15s
    track, artist = tracks[idx]
    progress = ((t % 15) / 15) * 100  # 0-100 over 15s cycles
    playing = True if int(t) % 40 < 35 else False  # pause briefly every 40s
    return {
        "type": "spotify",
        "track": track,
        "artist": artist,
        "playing": playing,
        "progress_pct": round(progress, 1),
    }


def gen_weather(t: float) -> dict:
    """Generate weather data with slow drift."""
    return {
        "type": "weather",
        "temp_out": round(22 + 5 * math.sin(t * 0.02) + random.gauss(0, 0.3), 1),
        "hum_out": round(max(20, min(95, 55 + 15 * math.sin(t * 0.03) + random.gauss(0, 2)))),
        "temp_in": round(24 + 1.5 * math.sin(t * 0.01) + random.gauss(0, 0.1), 1),
        "hum_in": round(max(25, min(70, 48 + 5 * math.sin(t * 0.02) + random.gauss(0, 1)))),
        "aqi": round(max(0, min(300, 52 + 20 * math.sin(t * 0.015) + random.gauss(0, 5)))),
    }


def gen_image_test_pattern() -> dict:
    """Generate an RGB stripe test pattern as a small JPEG.

    Creates horizontal color bars: red, green, blue, white, black.
    135x240 pixels, tiny JPEG for serial transport.
    """
    try:
        from PIL import Image
        width, height = 135, 240
        img = Image.new("RGB", (width, height))
        pixels = img.load()

        colors = [
            (255, 0, 0),    # red
            (0, 255, 0),    # green
            (0, 0, 255),    # blue
            (255, 255, 0),  # yellow
            (0, 255, 255),  # cyan
            (255, 0, 255),  # magenta
            (255, 255, 255),# white
            (0, 0, 0),      # black
        ]

        bar_height = height // len(colors)
        for y in range(height):
            color_idx = min(y // bar_height, len(colors) - 1)
            for x in range(width):
                pixels[x, y] = colors[color_idx]

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        jpeg_bytes = buf.getvalue()
    except ImportError:
        # Fallback: create a minimal valid JPEG manually (1x1 red pixel)
        # This is a known minimal JPEG
        jpeg_bytes = _minimal_jpeg()

    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    return {
        "type": "image",
        "jpeg_b64": b64,
    }


def _minimal_jpeg() -> bytes:
    """Return a minimal 8x8 JPEG (red block) for when Pillow is unavailable."""
    # Pre-generated 8x8 red JPEG, base64-decoded
    import binascii
    # Tiny red JPEG generated externally
    red_jpeg_hex = (
        "ffd8ffe000104a46494600010100000100010000"
        "ffdb004300080606070605080707070909080a0c"
        "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
        "20242e2720222c231c1c2837292c30313434341f"
        "27393d38323c2e333432ffc0000b080008000801"
        "011100ffc4001f000001050101010101010000000"
        "0000000000102030405060708090a0bffc4004010"
        "000201030302040305050404000001770001020311"
        "0004210531124151060713226171081432819108"
        "a1b1c10923334152d1f01562e17224728292a2b2"
        "c2d2e2f2ffda0008010100003f00fbd5c0000001"
        "ffd9"
    )
    try:
        return binascii.unhexlify(red_jpeg_hex)
    except Exception:
        # Absolute minimal valid JPEG won't actually render but won't crash
        return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9'


def gen_ack(t: float) -> dict:
    """Generate a test ACK message."""
    messages = [
        "Playing jazz playlist...",
        "Temperature set to 22C",
        "Lights dimmed to 30%",
        "Timer set for 5 minutes",
        "OK, checking the weather...",
        "Volume set to 50%",
    ]
    return {
        "type": "ack",
        "text": messages[int(t / 10) % len(messages)],
    }


# ── Mode generators map ──────────────────────────────────────────────────────

GENERATORS = {
    "stats":   gen_stats,
    "spotify": gen_spotify,
    "weather": gen_weather,
}


# ── Serial helpers ────────────────────────────────────────────────────────────

def open_serial(port: str, baud: int):
    """Open serial port. Returns serial.Serial instance."""
    import serial
    ser = serial.Serial(port, baud, timeout=2.0)
    time.sleep(0.2)  # brief settle
    return ser


def send_packet(ser, data: dict):
    """Send a JSON packet as a newline-terminated line."""
    line = json.dumps(data, separators=(",", ":")) + "\n"
    ser.write(line.encode("utf-8"))
    ser.flush()
    size = len(line)
    return size


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Send test data to TTGO T-Display over serial",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --mode stats              Stats data for 30s
  %(prog)s --mode all --duration 60  Cycle all modes for 60s
  %(prog)s --set-mode 1              Switch to Spotify mode
  %(prog)s --mode image              Send test pattern image""",
    )
    parser.add_argument(
        "--mode", choices=["stats", "spotify", "weather", "image", "all"],
        help="Data mode to send",
    )
    parser.add_argument(
        "--duration", type=int, default=30,
        help="Duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="Seconds between packets (default: 3.0)",
    )
    parser.add_argument(
        "--set-mode", type=int, choices=[0, 1, 2, 3], dest="set_mode",
        help="Set display mode: 0=stats 1=spotify 2=weather 3=image",
    )
    parser.add_argument(
        "--port", default=SERIAL_PORT,
        help=f"Serial port (default: {SERIAL_PORT})",
    )
    parser.add_argument(
        "--baud", type=int, default=SERIAL_BAUD,
        help=f"Baud rate (default: {SERIAL_BAUD})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Send one packet and exit",
    )

    args = parser.parse_args()

    if args.mode is None and args.set_mode is None:
        parser.error("Either --mode or --set-mode is required")

    # Graceful exit
    running = [True]
    def _sigint(sig, frame):
        running[0] = False
        print("\nStopping...")
    signal.signal(signal.SIGINT, _sigint)

    try:
        import serial  # noqa: F811
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial", file=sys.stderr)
        sys.exit(1)

    # Open serial
    try:
        ser = open_serial(args.port, args.baud)
    except Exception as e:
        print(f"ERROR: Cannot open {args.port}: {e}", file=sys.stderr)
        print("Hint: Is the bridge service holding the port? Stop it first:", file=sys.stderr)
        print(f"  sudo systemctl stop ttgo-bridge.service", file=sys.stderr)
        sys.exit(1)

    print(f"Connected to {args.port} @ {args.baud}")

    # ── set-mode command ──────────────────────────────────────────────────
    if args.set_mode is not None:
        mode_names = ["stats", "spotify", "weather", "image"]
        pkt = {"type": "set_mode", "mode": args.set_mode}
        size = send_packet(ser, pkt)
        print(f"Sent set_mode={args.set_mode} ({mode_names[args.set_mode]}) [{size}B]")
        ser.close()
        if args.mode is None:
            return

    # ── data sending loop ─────────────────────────────────────────────────
    mode = args.mode
    if mode is None:
        ser.close()
        return

    mode_cycle = ["stats", "spotify", "weather", "image"] if mode == "all" else [mode]
    cycle_interval = 8.0  # seconds per mode in 'all' mode

    t_start = time.monotonic()
    t_ref = time.monotonic()
    packet_count = 0

    print(f"Sending {mode} data for {args.duration}s (interval: {args.interval}s)...")
    print("─" * 50)

    while running[0]:
        elapsed = time.monotonic() - t_start
        if elapsed >= args.duration:
            break

        t = time.monotonic() - t_ref

        # Pick current mode
        if mode == "all":
            current_mode = mode_cycle[int(elapsed / cycle_interval) % len(mode_cycle)]
        else:
            current_mode = mode

        # Generate data
        if current_mode == "image":
            data = gen_image_test_pattern()
        else:
            data = GENERATORS[current_mode](t)

        # Send
        size = send_packet(ser, data)
        packet_count += 1

        # Pretty display
        remaining = args.duration - elapsed
        if current_mode == "image":
            b64_len = len(data.get("jpeg_b64", ""))
            print(f"[{elapsed:5.1f}s] image: {b64_len}B base64 ({size}B total) [{remaining:.0f}s left]")
        elif current_mode == "stats":
            print(f"[{elapsed:5.1f}s] stats: cpu={data['cpu']}% ram={data['ram']}MB temp={data['temp']}C disk={data['disk']}% [{remaining:.0f}s left]")
        elif current_mode == "spotify":
            state = "▶" if data["playing"] else "⏸"
            print(f"[{elapsed:5.1f}s] spotify: {state} {data['artist']} - {data['track']} ({data['progress_pct']:.0f}%) [{remaining:.0f}s left]")
        elif current_mode == "weather":
            print(f"[{elapsed:5.1f}s] weather: out={data['temp_out']}C/{data['hum_out']}% in={data['temp_in']}C/{data['hum_in']}% aqi={data['aqi']} [{remaining:.0f}s left]")

        if args.once:
            break

        time.sleep(args.interval)

    ser.close()
    print("─" * 50)
    print(f"Done. Sent {packet_count} packets in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
