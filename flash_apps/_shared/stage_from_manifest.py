#!/usr/bin/env python3
"""Copy MANIFEST allowlist from repo root into flash_apps/<app>/photoreal/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_manifest(manifest: Path) -> list[str]:
    lines: list[str] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.replace("\\", "/"))
    return lines


def _iter_sources(repo: Path, entry: str) -> list[Path]:
    """Expand a manifest entry to concrete files under repo."""
    entry = entry.rstrip("/")
    src = repo / entry
    if entry.endswith("**"):
        base = repo / entry[:-2].rstrip("/")
        if not base.is_dir():
            raise FileNotFoundError(f"MANIFEST glob base missing: {entry}")
        return [p for p in base.rglob("*") if p.is_file()]
    if src.is_file():
        return [src]
    if src.is_dir():
        return [p for p in src.rglob("*") if p.is_file()]
    # glob pattern relative to repo
    matches = [p for p in repo.glob(entry) if p.is_file()]
    if matches:
        return matches
    raise FileNotFoundError(f"MANIFEST entry not found: {entry}")


def stage(app_dir: Path, *, repo: Path | None = None) -> int:
    repo = repo or _repo_root()
    app_dir = app_dir.resolve()
    manifest = app_dir / "MANIFEST.txt"
    if not manifest.is_file():
        raise FileNotFoundError(f"Missing MANIFEST.txt in {app_dir}")

    dest_root = app_dir / "photoreal"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)

    # Package root marker for imports (photoreal.*)
    # Real files come from MANIFEST; ensure parent package exists.
    n = 0
    for entry in _parse_manifest(manifest):
        for src in _iter_sources(repo, entry):
            rel = src.relative_to(repo)
            # MANIFEST paths are like photoreal/foo.py → stage under app/photoreal/...
            if rel.parts[0] != "photoreal":
                raise ValueError(
                    f"MANIFEST entries must be under photoreal/ (got {rel.as_posix()})"
                )
            dest = app_dir.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            n += 1

    if n == 0:
        raise RuntimeError(f"MANIFEST staged 0 files for {app_dir.name}")

    # Ensure every package directory has an __init__.py. Never keep the monorepo
    # photoreal/flash/__init__.py (it imports portal/GHA helpers unsuitable for workers).
    flash_init = dest_root / "flash" / "__init__.py"
    flash_init.parent.mkdir(parents=True, exist_ok=True)
    flash_init.write_text(
        '"""Staged Flash worker package (deploy helpers not included)."""\n',
        encoding="utf-8",
    )
    for dirpath in sorted({p.parent for p in dest_root.rglob("*") if p.is_file()}):
        if not dirpath.is_relative_to(dest_root):
            continue
        init = dirpath / "__init__.py"
        if not init.is_file():
            init.write_text("", encoding="utf-8")

    print(f"staged {n} files → {dest_root}/")
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "app_dir",
        type=Path,
        help="Path to flash_apps/<id> (contains MANIFEST.txt)",
    )
    p.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Monorepo root (default: two levels above _shared/)",
    )
    args = p.parse_args(argv)
    try:
        stage(args.app_dir, repo=args.repo.resolve() if args.repo else None)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
