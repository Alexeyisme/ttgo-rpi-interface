"""
voice_handler.py — PTT recording and Telegram voice message dispatch.

Flow:
  1. ptt_start  → start arecord from C920 mic (ALSA hw:3,0)
  2. ptt_stop   → stop recording, send audio as Telegram voice message
  3. Hermes receives it exactly like a regular user voice message and processes it
  4. Returns {"type":"ack","text":"Voice sent"} for TTGO screen

ALSA device: hw:3,0 — HD Pro Webcam C920 (card 3, device 0).
Audio format: OGG Opus via ffmpeg (Telegram voice format), fallback to raw WAV.
"""

import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

ALSA_DEVICE  = "hw:3,0"   # C920 mic: card 3, device 0
SAMPLE_RATE  = 16000
CHANNELS     = 1
FORMAT       = "S16_LE"
MAX_RECORD_S = 30          # safety cap on recording length


class VoiceHandler:
    def __init__(self, on_ack: Optional[Callable[[str], None]] = None):
        self._on_ack     = on_ack
        self._proc: Optional[subprocess.Popen] = None
        self._wav_path: Optional[str] = None
        self._active     = False
        self._tg_token   = ""
        self._tg_chat_id = ""
        self._load_env()

    def _load_env(self):
        env_file = Path.home() / ".hermes" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
        self._tg_token   = os.environ.get("TELEGRAM_TOKEN", "")
        self._tg_chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "")

    def on_ptt_start(self):
        if self._active:
            return
        self._active = True

        fd, path = tempfile.mkstemp(suffix=".wav", prefix="ptt_")
        os.close(fd)
        self._wav_path = path

        self._proc = subprocess.Popen(
            [
                "arecord",
                "-D", ALSA_DEVICE,
                "-f", FORMAT,
                "-r", str(SAMPLE_RATE),
                "-c", str(CHANNELS),
                "-d", str(MAX_RECORD_S),
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("PTT recording started → %s", path)

    def on_ptt_stop(self):
        if not self._active or self._proc is None:
            return
        self._active = False

        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

        wav = self._wav_path
        self._wav_path = None

        if wav:
            t = threading.Thread(target=self._send, args=(wav,), daemon=True, name="ptt-send")
            t.start()

    def _send(self, wav_path: str):
        try:
            # Try to convert WAV → OGG Opus (Telegram native voice format)
            ogg_path = wav_path.replace(".wav", ".ogg")
            converted = False
            try:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", wav_path,
                        "-c:a", "libopus",
                        "-b:a", "32k",
                        ogg_path,
                    ],
                    capture_output=True, timeout=15,
                )
                if result.returncode == 0:
                    converted = True
            except FileNotFoundError:
                pass   # ffmpeg not installed, fall back to WAV

            audio_path = ogg_path if converted else wav_path

            if not self._tg_token or not self._tg_chat_id:
                logger.warning("Telegram credentials missing — cannot send voice")
                if self._on_ack:
                    self._on_ack("No TG config")
                return

            # Send as Telegram voice message — Hermes picks it up like any voice message
            url = f"https://api.telegram.org/bot{self._tg_token}/sendVoice"
            with open(audio_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"chat_id": self._tg_chat_id},
                    files={"voice": ("voice.ogg" if converted else "voice.wav", f,
                                     "audio/ogg" if converted else "audio/wav")},
                    timeout=30,
                )

            if resp.status_code == 200:
                logger.info("Voice message sent to Telegram")
                if self._on_ack:
                    self._on_ack("Voice sent!")
            else:
                logger.warning("Telegram sendVoice failed: %s %s",
                               resp.status_code, resp.text[:100])
                if self._on_ack:
                    self._on_ack("Send failed")

        except Exception as e:
            logger.error("Voice send error: %s", e)
            if self._on_ack:
                self._on_ack("Error sending")
        finally:
            for p in [wav_path, ogg_path if converted else None]:
                if p:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
