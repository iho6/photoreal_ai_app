"""Size-aware skip/complete checks for model downloads (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "download_models.py"


def _load():
    spec = importlib.util.spec_from_file_location("download_models", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dm():
    return _load()


def test_sizes_match(dm) -> None:
    assert dm._sizes_match(100, 100)
    assert not dm._sizes_match(0, 100)
    assert not dm._sizes_match(99, 100)
    assert dm._sizes_match(99, 100, tol=1)


def test_local_file_complete_requires_expected_size(dm, tmp_path: Path) -> None:
    p = tmp_path / "lora.safetensors"
    p.write_bytes(b"x" * 500)
    assert not dm.local_file_complete(p, expected_bytes=1000)
    assert not dm.local_file_complete(p, expected_bytes=None, min_bytes=1_000_000)

    p.write_bytes(b"y" * 1000)
    assert dm.local_file_complete(p, expected_bytes=1000)
    assert not dm.local_file_complete(p, expected_bytes=1001)


def test_local_file_complete_min_bytes_fallback(dm, tmp_path: Path) -> None:
    p = tmp_path / "big.safetensors"
    p.write_bytes(b"z" * 1_000_000)
    assert dm.local_file_complete(p, expected_bytes=None, min_bytes=1_000_000)
    assert not dm.local_file_complete(p, expected_bytes=None, min_bytes=1_000_001)


def test_promote_incomplete_to_partial(dm, tmp_path: Path) -> None:
    dest = tmp_path / "a.safetensors"
    tmp = tmp_path / "a.safetensors.partial"
    dest.write_bytes(b"partial-data")
    n = dm._promote_incomplete_to_partial(dest, tmp)
    assert n == len(b"partial-data")
    assert not dest.exists()
    assert tmp.exists()
