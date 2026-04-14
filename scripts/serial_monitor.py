#!/usr/bin/env python3
"""
serial_monitor.py — Read and pretty-print TTGO serial events.

Monitors the TTGO T-Display serial output (TTGO → RPi direction) and
displays events with timestamps and color formatting.

Usage:
    ./serial_monitor.py                  # monitor for 60s
    ./serial_monitor.py --duration 120   # monitor for 2 minutes
    ./serial_monitor.py --duration 0     # monitor indefinitely (Ctrl+C to stop)
    ./serial_monitor.py --raw            # raw JSON lines, no formatting
    ./serial_monitor.py --json           # pretty-printed JSON output
"""

import argparse
import json
import signal
import sys
import time
from datetime import datetime

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 460800

# ── ANSI colors ──────────────────────────────────────────────────────────────

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"
    BG_DIM  = "\033[48;5;236m"


EVENT_COLORS = {
    "btn1_press":    C.CYAN,
    "mode_changed":  C.MAGENTA,
    "ptt_start":     C.GREEN,
    "ptt_stop":      C.RED,
    "device_ready":  C.YELLOW + C.BOLD,
}


# ── Pretty printer ───────────────────────────────────────────────────────────

def format_event(obj: dict, raw_line: str) -> str:
    """Format a parsed JSON event for display."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    event = obj.get("event", "")

    if event:
        color = EVENT_COLORS.get(event, C.WHITE)
        parts = [f"{C.DIM}{ts}{C.RESET}", f"{color}{event}{C.RESET}"]

        # Extra fields
        extras = {k: v for k, v in obj.items() if k != "event"}
        if extras:
            extra_str = " ".join(f"{C.DIM}{k}={C.RESET}{C.BOLD}{v}{C.RESET}" for k, v in extras.items())
            parts.append(extra_str)

        return " │ ".join(parts)

    # Non-event JSON (maybe debug output from firmware)
    type_str = obj.get("type", "unknown")
    return f"{C.DIM}{ts}{C.RESET} │ {C.BLUE}[data]{C.RESET} type={C.BOLD}{type_str}{C.RESET} {C.DIM}{json.dumps(obj, separators=(',',':'))[:120]}{C.RESET}"


def format_non_json(line: str) -> str:
    """Format a non-JSON serial line (e.g., boot messages)."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    return f"{C.DIM}{ts}{C.RESET} │ {C.YELLOW}[raw]{C.RESET} {line}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Monitor TTGO T-Display serial output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Events from TTGO:
  btn1_press    - Mode button pressed
  mode_changed  - Display mode switched (includes mode index)
  ptt_start     - Push-to-talk button held down
  ptt_stop      - Push-to-talk button released
  device_ready  - TTGO finished booting""",
    )
    parser.add_argument(
        "--duration", type=int, default=60,
        help="Monitor duration in seconds (0 = indefinite, default: 60)",
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
        "--raw", action="store_true",
        help="Print raw serial lines without formatting",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Pretty-print JSON objects",
    )
    parser.add_argument(
        "--filter", type=str, default=None,
        help="Only show events matching this string (e.g., 'ptt' or 'mode')",
    )

    args = parser.parse_args()

    running = [True]
    def _sigint(sig, frame):
        running[0] = False
        print(f"\n{C.DIM}Stopping...{C.RESET}")
    signal.signal(signal.SIGINT, _sigint)

    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial", file=sys.stderr)
        sys.exit(1)

    # Open serial
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1.0)
    except Exception as e:
        print(f"ERROR: Cannot open {args.port}: {e}", file=sys.stderr)
        print("Hint: Is the bridge service holding the port? Stop it first:", file=sys.stderr)
        print(f"  sudo systemctl stop ttgo-bridge.service", file=sys.stderr)
        sys.exit(1)

    duration_str = f"{args.duration}s" if args.duration > 0 else "indefinite"
    print(f"{C.BOLD}TTGO Serial Monitor{C.RESET} — {args.port} @ {args.baud} — duration: {duration_str}")
    if args.filter:
        print(f"Filter: {C.CYAN}{args.filter}{C.RESET}")
    print("─" * 60)

    t_start = time.monotonic()
    event_count = 0
    line_count = 0
    error_count = 0

    try:
        while running[0]:
            # Duration check
            elapsed = time.monotonic() - t_start
            if args.duration > 0 and elapsed >= args.duration:
                break

            try:
                raw = ser.readline()
            except Exception as e:
                error_count += 1
                if error_count <= 3:
                    print(f"{C.RED}Serial read error: {e}{C.RESET}")
                if error_count >= 10:
                    print(f"{C.RED}Too many errors, exiting{C.RESET}")
                    break
                time.sleep(1)
                continue

            if not raw:
                continue  # timeout, no data

            try:
                line = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                continue

            if not line:
                continue

            line_count += 1

            # Filter
            if args.filter and args.filter.lower() not in line.lower():
                continue

            # Raw mode
            if args.raw:
                print(line)
                sys.stdout.flush()
                continue

            # Try to parse JSON
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(format_non_json(line))
                sys.stdout.flush()
                continue

            event_count += 1

            # JSON pretty-print mode
            if args.json_mode:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"--- {ts} ---")
                print(json.dumps(obj, indent=2))
                sys.stdout.flush()
                continue

            # Pretty formatted mode
            print(format_event(obj, line))
            sys.stdout.flush()

    finally:
        ser.close()
        elapsed = time.monotonic() - t_start
        print("─" * 60)
        print(f"{C.DIM}Session: {elapsed:.1f}s │ {line_count} lines │ {event_count} events │ {error_count} errors{C.RESET}")


if __name__ == "__main__":
    main()
