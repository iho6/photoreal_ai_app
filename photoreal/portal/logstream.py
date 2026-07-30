"""CR/LF-aware stdout splitting for same-line progress (tqdm-style \\r)."""

from __future__ import annotations

import re
from typing import Literal

LogMode = Literal["append", "replace", "progress"]
LogEvent = tuple[str, LogMode]

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_PROGRESS_MARK = "@@PROGRESS@@|"


def parse_percent(line: str) -> float | None:
    m = _PCT_RE.search(line)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def format_progress_bar(pct: float, label: str = "", *, width: int = 20) -> str:
    """ASCII bar for the portal log, e.g. ``[########--------]  40.0%  ae``."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    bar = "#" * filled + "-" * (width - filled)
    name = " ".join(str(label).split())
    if len(name) > 48:
        name = name[:45] + "…"
    if name:
        return f"  [{bar}] {pct:5.1f}%  {name}"
    return f"  [{bar}] {pct:5.1f}%"


def parse_progress_mark(line: str) -> tuple[float, str] | None:
    """Parse ``@@PROGRESS@@|<pct>|<label>`` markers from the downloader."""
    s = line.strip()
    if not s.startswith(_PROGRESS_MARK):
        return None
    rest = s[len(_PROGRESS_MARK) :]
    pct_s, _, label = rest.partition("|")
    try:
        pct = float(pct_s)
    except ValueError:
        return None
    return pct, label.strip()


def is_progress_line(line: str) -> bool:
    """True for tqdm / byte counters / progress markers."""
    if parse_progress_mark(line) is not None:
        return True
    s = line.strip()
    if not s:
        return False
    if s.startswith("[") and "]" in s and parse_percent(s) is not None:
        return True
    low = s.lower()
    pct = parse_percent(s)
    if pct is not None:
        if (
            "|" in s
            or "bytes" in low
            or "fetching" in low
            or "it/s" in low
            or "download" in low
            or "/" in s
            or len(s) < 120
        ):
            return True
    if s.startswith("Fetching ") and "files" in low:
        return True
    if "bytes" in low and ("/" in s or ":" in s):
        return True
    return False


def feed_cr_lf(buffer: str, chunk: str) -> tuple[str, list[LogEvent]]:
    """
    Append ``chunk`` to ``buffer`` and emit completed log events.

    - ``\\n`` (and ``\\r\\n``) → append (or progress if it looks like a bar)
    - bare ``\\r`` → progress (in-place percentage rewrite)
    """
    buffer = buffer + chunk
    events: list[LogEvent] = []
    while True:
        i_n = buffer.find("\n")
        i_r = buffer.find("\r")
        if i_n < 0 and i_r < 0:
            break
        use_cr = i_r >= 0 and (i_n < 0 or i_r < i_n)
        if use_cr:
            if i_r + 1 < len(buffer) and buffer[i_r + 1] == "\n":
                text = buffer[:i_r]
                buffer = buffer[i_r + 2 :]
                mode: LogMode = "progress" if is_progress_line(text) else "append"
                events.append((text, mode))
            else:
                text = buffer[:i_r]
                buffer = buffer[i_r + 1 :]
                events.append((text, "progress"))
        else:
            text = buffer[:i_n]
            if text.endswith("\r"):
                text = text[:-1]
            buffer = buffer[i_n + 1 :]
            mode = "progress" if is_progress_line(text) else "append"
            events.append((text, mode))
    return buffer, events


def flush_cr_lf(buffer: str) -> list[LogEvent]:
    """Emit any trailing text without a final newline."""
    if not buffer:
        return []
    mode: LogMode = "progress" if is_progress_line(buffer) else "append"
    return [(buffer, mode)]
