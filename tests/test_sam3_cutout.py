"""Unit tests for SAM segment cutout helper."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from photoreal.portal.sam3_jobs import make_segment_cutout


def test_make_segment_cutout(tmp_path: Path):
    frame = tmp_path / "frame.png"
    mask = tmp_path / "mask.png"
    out = tmp_path / "cutout.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(frame)
    # white left half = keep
    m = Image.new("L", (4, 4), 0)
    for y in range(4):
        for x in range(2):
            m.putpixel((x, y), 255)
    m.save(mask)

    make_segment_cutout(frame, mask, out)
    assert out.is_file()
    cut = Image.open(out).convert("RGBA")
    assert cut.size == (4, 4)
    assert cut.getpixel((0, 0))[3] == 255
    assert cut.getpixel((3, 0))[3] == 0
