"""CR/LF logstream splitter tests (no network)."""

from __future__ import annotations

from photoreal.portal.logstream import (
    feed_cr_lf,
    flush_cr_lf,
    format_progress_bar,
    is_progress_line,
    parse_percent,
    parse_progress_mark,
)


def test_feed_cr_lf_progress_replace_then_newline() -> None:
    buf = ""
    buf, ev = feed_cr_lf(buf, "downloading")
    assert ev == []
    assert buf == "downloading"

    buf, ev = feed_cr_lf(buf, " 10%\r")
    assert ev == [("downloading 10%", "progress")]
    assert buf == ""

    buf, ev = feed_cr_lf(buf, "downloading 50%\r")
    assert ev == [("downloading 50%", "progress")]

    buf, ev = feed_cr_lf(buf, "downloading 100%\n")
    assert ev == [("downloading 100%", "progress")]
    assert buf == ""


def test_feed_cr_lf_crlf_is_append() -> None:
    buf, ev = feed_cr_lf("", "hello\r\nworld\n")
    assert ev == [("hello", "append"), ("world", "append")]
    assert buf == ""


def test_feed_cr_lf_flush_trailing() -> None:
    buf, ev = feed_cr_lf("", "partial")
    assert ev == []
    assert flush_cr_lf(buf) == [("partial", "append")]
    assert flush_cr_lf("") == []


def test_feed_cr_lf_chunked_across_cr() -> None:
    buf = ""
    buf, ev = feed_cr_lf(buf, "abc")
    assert ev == []
    buf, ev = feed_cr_lf(buf, "\rdef\r")
    assert ev == [("abc", "progress"), ("def", "progress")]
    assert buf == ""


def test_tqdm_line_is_progress_not_append() -> None:
    buf, ev = feed_cr_lf("", "Fetching 14 files: 100%|##########| 14/14 [00:00<?, ?it/s]\n")
    assert len(ev) == 1
    assert ev[0][1] == "progress"
    assert is_progress_line(ev[0][0])
    assert parse_percent(ev[0][0]) == 100.0


def test_status_line_stays_append() -> None:
    buf, ev = feed_cr_lf("", "  AE -> /tmp/ae.safetensors\n")
    assert ev == [("  AE -> /tmp/ae.safetensors", "append")]


def test_progress_mark_and_bar() -> None:
    assert parse_progress_mark("@@PROGRESS@@|42.5|transformer (1/2)") == (
        42.5,
        "transformer (1/2)",
    )
    bar = format_progress_bar(40.0, "ae")
    assert "[########" in bar or "[#######-" in bar
    assert "40.0%" in bar
    assert "ae" in bar
    buf, ev = feed_cr_lf("", "@@PROGRESS@@|12.0|vlm\n")
    assert ev == [("@@PROGRESS@@|12.0|vlm", "progress")]
