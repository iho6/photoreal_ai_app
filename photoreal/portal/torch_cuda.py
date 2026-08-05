"""Ensure a CUDA-capable PyTorch wheel (cu128) when an NVIDIA GPU is present.

Default ``pip install torch`` from PyPI often yields a CPU build (or an older
CUDA build without Blackwell / sm_120). RTX 50-series needs CUDA 12.8+ wheels
from ``https://download.pytorch.org/whl/cu128``.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Callable

from photoreal.portal.paths import REPO_ROOT, venv_python

CU128_INDEX = "https://download.pytorch.org/whl/cu128"
# Minimum torch.version.cuda major.minor we accept for local GPU generate.
MIN_TORCH_CUDA = (12, 8)

LogFn = Callable[[str], None]


def nvidia_smi_ok() -> bool:
    """True if nvidia-smi runs (host has an NVIDIA driver + GPU visible)."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0:
            return False
        out = (r.stdout or "") + (r.stderr or "")
        return bool(re.search(r"GPU\s+\d+:", out, re.I)) or "NVIDIA" in out.upper()
    except (OSError, subprocess.TimeoutExpired):
        return False


def describe_torch_cuda() -> dict[str, Any]:
    """
    Best-effort torch CUDA summary without requiring CUDA to work.

    Keys: available, version, cuda_version, device_count, device_name, error.
    """
    info: dict[str, Any] = {
        "available": False,
        "version": None,
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "error": None,
    }
    try:
        import torch

        info["version"] = str(getattr(torch, "__version__", "") or "")
        info["cuda_version"] = getattr(torch.version, "cuda", None)
        info["available"] = bool(torch.cuda.is_available())
        if info["available"]:
            try:
                info["device_count"] = int(torch.cuda.device_count())
                if info["device_count"] > 0:
                    info["device_name"] = str(torch.cuda.get_device_name(0))
            except Exception as exc:  # noqa: BLE001
                info["error"] = f"device query failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def _parse_cuda_version(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    m = re.match(r"^(\d+)\.(\d+)", str(s).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def torch_cuda_build_ok(info: dict[str, Any] | None = None) -> bool:
    """True when torch reports CUDA available and build CUDA >= 12.8."""
    d = info if info is not None else describe_torch_cuda()
    if not d.get("available"):
        return False
    parsed = _parse_cuda_version(d.get("cuda_version"))
    if parsed is None:
        # CUDA available but version string missing — treat as usable.
        return True
    return parsed >= MIN_TORCH_CUDA


def needs_cuda_torch_reinstall(info: dict[str, Any] | None = None) -> bool:
    """
    True when the host has an NVIDIA GPU but torch cannot use a modern CUDA build.

    ``info`` should be a subprocess (venv) probe when deciding Generate/Launch heal —
    do not pass a sticky in-process ``describe_torch_cuda()`` from a long-lived API.
    """
    if not nvidia_smi_ok():
        return False
    d = info if info is not None else describe_torch_cuda()
    if d.get("error") and not d.get("version"):
        return True  # torch missing / broken
    ver = d.get("version")
    if isinstance(ver, str) and _looks_like_cpu_torch(ver):
        return True
    if not d.get("available"):
        return True
    # Explicit cu128 tag is enough even if cuda string is odd.
    if isinstance(ver, str) and "cu128" in ver.lower():
        return False
    parsed = _parse_cuda_version(d.get("cuda_version"))
    if parsed is not None and parsed < MIN_TORCH_CUDA:
        return True
    if parsed is not None and parsed >= MIN_TORCH_CUDA:
        return False
    # available=True but no cuda version / no cu128 tag — treat as OK.
    return False


def venv_torch_needs_reinstall(python: str | None = None) -> tuple[bool, dict[str, Any]]:
    """
    Authoritative decision for the repo ``.venv`` via a fresh interpreter.

    Returns ``(needs_reinstall, probe_info)``.
    """
    info = probe_torch_build_subprocess(python)
    return needs_cuda_torch_reinstall(info), info


def probe_torch_build_subprocess(python: str | None = None) -> dict[str, Any]:
    """Return version / cuda / available from a fresh interpreter."""
    py = python or str(venv_python())
    info: dict[str, Any] = {
        "version": None,
        "cuda_version": None,
        "available": False,
        "error": None,
    }
    try:
        r = subprocess.run(
            [
                py,
                "-c",
                "import torch; print(torch.__version__); "
                "print(torch.version.cuda); print(torch.cuda.is_available())",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = str(exc)
        return info
    if r.returncode != 0:
        info["error"] = ((r.stderr or r.stdout or "")[-500:]).strip() or f"exit {r.returncode}"
        return info
    lines = (r.stdout or "").strip().splitlines()
    if len(lines) >= 1:
        info["version"] = lines[0].strip()
    if len(lines) >= 2:
        cv = lines[1].strip()
        info["cuda_version"] = None if cv in ("None", "none", "") else cv
    if len(lines) >= 3:
        info["available"] = lines[2].strip().lower() in ("true", "1")
    return info


def probe_torch_cuda_subprocess(python: str | None = None) -> bool:
    """Fresh-interpreter check so a prior CPU torch import cannot stick."""
    return bool(probe_torch_build_subprocess(python).get("available"))


def _looks_like_cpu_torch(version: str | None) -> bool:
    if not version:
        return True
    v = version.lower()
    return "+cpu" in v or v.endswith("cpu")


def _looks_like_cu128_torch(version: str | None, cuda_version: str | None) -> bool:
    if _looks_like_cpu_torch(version):
        return False
    if version and "cu128" in version.lower():
        return True
    parsed = _parse_cuda_version(cuda_version)
    return parsed is not None and parsed >= MIN_TORCH_CUDA


def _emit_pip_tail(emit: LogFn, label: str, stdout: str, stderr: str, limit: int = 1500) -> None:
    blob = ((stdout or "") + "\n" + (stderr or "")).strip()
    if not blob:
        emit(f"torch: {label}: (no pip output)")
        return
    tail = blob[-limit:]
    for line in tail.splitlines()[-20:]:
        emit(f"torch: {label}: {line}")


def ensure_cuda_torch(
    *,
    python: str | None = None,
    log: LogFn | None = None,
    force: bool = False,
) -> bool:
    """
    Replace CPU/old torch with cu128 wheels.

    Uninstalls first and uses ``--force-reinstall`` so a newer ``+cpu`` build
    cannot block an older/different ``+cu128`` wheel via plain ``--upgrade``.
    """

    def _emit(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    if not force:
        needs, info = venv_torch_needs_reinstall(python)
        if not needs:
            _emit("torch: CUDA build already OK (skip cu128 install)")
            return bool(info.get("available")) or probe_torch_cuda_subprocess(python)

    if not nvidia_smi_ok():
        _emit("torch: nvidia-smi missing — cannot install GPU torch; local CUDA disabled")
        return False

    py = python or str(venv_python())
    env = os.environ.copy()
    env.pop("CUDA_VISIBLE_DEVICES", None)

    _emit("torch: uninstalling existing torch/torchvision/torchaudio …")
    uninstall_cmd = [
        py,
        "-m",
        "pip",
        "uninstall",
        "-y",
        "torch",
        "torchvision",
        "torchaudio",
    ]
    try:
        u = subprocess.run(
            uninstall_cmd,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _emit(f"torch: uninstall failed to start: {exc}")
        return False
    _emit_pip_tail(_emit, "uninstall", u.stdout or "", u.stderr or "")

    _emit(f"torch: force-installing CUDA 12.8 wheels via {CU128_INDEX} …")
    install_cmd = [
        py,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "torch",
        "torchvision",
        "torchaudio",
        "--index-url",
        CU128_INDEX,
    ]
    try:
        r = subprocess.run(
            install_cmd,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _emit(f"torch: pip failed to start: {exc}")
        return False

    _emit_pip_tail(_emit, "install", r.stdout or "", r.stderr or "")
    if r.returncode != 0:
        _emit(f"torch: cu128 install failed (exit {r.returncode})")
        return False

    _emit("torch: cu128 install finished; verifying in subprocess …")
    build = probe_torch_build_subprocess(py)
    ver = build.get("version")
    cuda_v = build.get("cuda_version")
    avail = bool(build.get("available"))
    _emit(f"torch: {ver}")
    _emit(f"torch: {cuda_v}")
    _emit(f"torch: {avail}")
    if build.get("error"):
        _emit(f"torch: verify failed: {build['error']}")
        return False
    if _looks_like_cpu_torch(ver) or not _looks_like_cu128_torch(ver, cuda_v):
        _emit(
            "torch: cu128 wheel not installed "
            f"(still {ver or 'unknown'}; cuda_build={cuda_v or 'none'}); see pip log"
        )
        return False
    if not avail:
        _emit(
            "torch: cu128 wheel installed but cuda.is_available() is false — "
            "check NVIDIA driver on this host"
        )
        return False
    return True


def format_torch_diag(info: dict[str, Any] | None = None) -> str:
    d = info if info is not None else describe_torch_cuda()
    ver = d.get("version") or "missing"
    cuda_v = d.get("cuda_version") or "none"
    avail = "true" if d.get("available") else "false"
    name = d.get("device_name") or "-"
    err = d.get("error")
    base = f"torch={ver} cuda_build={cuda_v} available={avail} gpu={name}"
    if err:
        return f"{base} error={err}"
    return base
