"""Local Vosk small-en keyword spotting for Record Reference Start/Stop."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOSK_MODEL_DIR = REPO_ROOT / "data" / "models" / "vosk" / VOSK_MODEL_NAME
SAMPLE_RATE = 16_000

_lock = threading.Lock()
_model: Any = None
_recognizer: Any = None
_recognizer_rate: int = SAMPLE_RATE


def model_ready() -> bool:
    # Unpacked model contains am/ + conf/ (layout varies slightly by version)
    return VOSK_MODEL_DIR.is_dir() and any(VOSK_MODEL_DIR.iterdir())


def status() -> dict[str, Any]:
    vosk_ok = False
    try:
        import vosk  # noqa: F401

        vosk_ok = True
    except ImportError:
        vosk_ok = False
    return {
        "ready": bool(vosk_ok and model_ready()),
        "vosk_installed": vosk_ok,
        "model_present": model_ready(),
        "model_path": str(VOSK_MODEL_DIR),
        "sample_rate": SAMPLE_RATE,
        "hint": (
            None
            if model_ready() and vosk_ok
            else "pip install vosk && python scripts/download_models.py --vosk"
        ),
    }


def _ensure_recognizer(sample_rate: int = SAMPLE_RATE) -> Any:
    global _model, _recognizer, _recognizer_rate
    if not model_ready():
        raise RuntimeError(
            f"Vosk model missing at {VOSK_MODEL_DIR}. "
            "Run: python scripts/download_models.py --vosk"
        )
    try:
        from vosk import KaldiRecognizer, Model
    except ImportError as e:
        raise RuntimeError(
            "vosk package not installed. pip install 'photoreal[portal]' extras / vosk"
        ) from e

    rate = int(sample_rate) if sample_rate else SAMPLE_RATE
    if rate <= 0:
        rate = SAMPLE_RATE

    if _model is None:
        _model = Model(str(VOSK_MODEL_DIR))
    if _recognizer is None or _recognizer_rate != rate:
        # Grammar bias: only start/stop (+ unk) — far more reliable than free dictation.
        grammar = '["start", "stop", "[unk]"]'
        try:
            _recognizer = KaldiRecognizer(_model, rate, grammar)
        except Exception:  # noqa: BLE001
            _recognizer = KaldiRecognizer(_model, rate)
        _recognizer.SetWords(True)
        _recognizer_rate = rate
    return _recognizer


def detect_command(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return "none"
    # Exact / word-boundary match; also tolerate tiny ASR fragments
    if re.search(r"\bstart\b", t) or t in ("start", "started", "starting"):
        return "start"
    if re.search(r"\bstop\b", t) or t in ("stop", "stopped", "stopping"):
        return "stop"
    return "none"


def process_pcm(pcm: bytes, *, sample_rate: int = SAMPLE_RATE) -> dict[str, Any]:
    """Feed raw s16le mono PCM; return command + transcript snippet."""
    if not pcm:
        return {"command": "none", "text": ""}
    with _lock:
        rec = _ensure_recognizer(sample_rate)
        text = ""
        if rec.AcceptWaveform(pcm):
            payload = json.loads(rec.Result() or "{}")
            text = str(payload.get("text") or "").strip()
        else:
            payload = json.loads(rec.PartialResult() or "{}")
            text = str(payload.get("partial") or "").strip()
        return {"command": detect_command(text), "text": text}


def reset_recognizer() -> None:
    """Drop streaming state (e.g. between modal sessions)."""
    global _recognizer
    with _lock:
        _recognizer = None
