"""Dispatch Flash character deploy via GitHub Actions (Linux runner)."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from photoreal.portal.paths import REPO_ROOT

LogFn = Callable[[str], None]

WORKFLOW_FILE = "flash-deploy-character.yml"
API = "https://api.github.com"

GHA_TOKEN_MSG = (
    "Flash deploy needs Linux. This PC has no WSL distro, so the portal uses "
    "GitHub Actions.\n"
    "Save a GitHub token on the portal with classic ``repo`` scope "
    "(or fine-grained: Actions + Secrets + Contents).\n"
    "Portal Save/Launch auto-pushes Actions secrets RUNPOD_API_KEY / HF_TOKEN "
    "from the values you enter — no manual website secrets required.\n"
    "Or run the workflow manually: Actions → Flash deploy character → Run workflow.\n"
    "See docs/portal.md"
)


def _emit(log: LogFn | None, msg: str) -> None:
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def parse_github_owner_repo(remote_url: str) -> tuple[str, str] | None:
    """Parse owner/repo from an origin URL (https or ssh)."""
    url = (remote_url or "").strip()
    if not url:
        return None
    # git@github.com:owner/repo.git
    m = re.match(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).removesuffix(".git")
    # https://github.com/owner/repo.git
    if "github.com" in url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[1].removesuffix(".git")
    return None


def detect_github_repo(*, cwd: Any = None) -> tuple[str, str]:
    """Return (owner, repo) from git remote origin."""
    root = cwd or REPO_ROOT
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"Could not read git remote origin ({exc}). {GHA_TOKEN_MSG}"
        ) from exc
    if r.returncode != 0:
        raise RuntimeError(
            f"git remote get-url origin failed: {(r.stderr or r.stdout or '').strip()}\n"
            f"{GHA_TOKEN_MSG}"
        )
    parsed = parse_github_owner_repo(r.stdout.strip())
    if not parsed:
        raise RuntimeError(
            f"origin is not a GitHub remote ({r.stdout.strip()!r}). {GHA_TOKEN_MSG}"
        )
    return parsed


def detect_git_ref(*, cwd: Any = None) -> str:
    """Current branch name, or main."""
    root = cwd or REPO_ROOT
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if r.returncode == 0:
            name = (r.stdout or "").strip()
            if name and name != "HEAD":
                return name
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "main"


def deploy_via_github_actions(
    *,
    github_token: str,
    log: LogFn | None = None,
    timeout_s: float = 2700.0,
    poll_interval_s: float = 8.0,
    client: httpx.Client | None = None,
    owner: str | None = None,
    repo: str | None = None,
    ref: str | None = None,
) -> None:
    """
    workflow_dispatch flash-deploy-character.yml and wait for success.

    Requires a PAT with actions:write on the repository.
    """
    token = (github_token or "").strip()
    if not token:
        raise RuntimeError(GHA_TOKEN_MSG)

    # Must sync Actions secrets before dispatch (empty RUNPOD_API_KEY fails the workflow)
    from photoreal.flash.gha_secrets import try_sync_actions_secrets_from_portal
    from photoreal.portal.credentials import apply_env_to_process, load_credentials

    apply_env_to_process()
    creds = load_credentials()
    if (creds.get("runpod_api_key") or "").strip():
        sync_err = try_sync_actions_secrets_from_portal(log=log)
        if sync_err:
            raise RuntimeError(
                "Cannot dispatch Flash deploy: failed to sync GitHub Actions secrets "
                f"(RUNPOD_API_KEY must exist on the repo).\n{sync_err}"
            )

    if not owner or not repo:
        owner, repo = detect_github_repo()
    ref = (ref or detect_git_ref()).strip() or "main"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "photoreal-flash-deploy",
    }
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(60.0))
    try:
        _emit(log, f"flash: dispatching GitHub Actions {WORKFLOW_FILE} @ {owner}/{repo} ref={ref}")
        before = time.time()
        dispatch_url = (
            f"{API}/repos/{owner}/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches"
        )
        resp = http.post(dispatch_url, headers=headers, json={"ref": ref})
        if resp.status_code == 404:
            raise RuntimeError(
                f"Workflow {WORKFLOW_FILE} not found on {owner}/{repo} "
                f"(push the workflow file, or check the remote). {GHA_TOKEN_MSG}"
            )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"GitHub Actions dispatch forbidden HTTP {resp.status_code}. "
                f"Check GITHUB_TOKEN scopes (actions:write). {GHA_TOKEN_MSG}"
            )
        if resp.status_code not in (204, 200):
            raise RuntimeError(
                f"workflow_dispatch failed HTTP {resp.status_code}: {resp.text[:500]}\n"
                f"{GHA_TOKEN_MSG}"
            )

        run = _wait_for_new_run(
            http,
            headers=headers,
            owner=owner,
            repo=repo,
            since=before - 30.0,
            log=log,
            timeout_s=min(120.0, timeout_s),
        )
        run_id = int(run["id"])
        html = str(run.get("html_url") or "")
        _emit(log, f"flash: Actions run id={run_id} {html}")

        deadline = time.time() + timeout_s
        last = ""
        while time.time() < deadline:
            st = http.get(
                f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}",
                headers=headers,
            )
            if st.status_code >= 400:
                raise RuntimeError(
                    f"Get Actions run failed HTTP {st.status_code}: {st.text[:400]}"
                )
            data = st.json()
            status = str(data.get("status") or "")
            conclusion = str(data.get("conclusion") or "")
            label = f"{status}/{conclusion or '-'}"
            if label != last:
                _emit(log, f"flash: Actions {label}")
                last = label
            if status == "completed":
                if conclusion == "success":
                    _emit(log, "flash: GitHub Actions deploy finished ok")
                    return
                raise RuntimeError(
                    f"GitHub Actions deploy {conclusion or 'failed'}. "
                    f"See {data.get('html_url') or html}"
                )
            time.sleep(poll_interval_s)

        raise RuntimeError(
            f"GitHub Actions deploy timed out after {timeout_s:.0f}s. "
            f"See {html or f'https://github.com/{owner}/{repo}/actions'}"
        )
    finally:
        if owns:
            http.close()


def _wait_for_new_run(
    http: httpx.Client,
    *,
    headers: dict[str, str],
    owner: str,
    repo: str,
    since: float,
    log: LogFn | None,
    timeout_s: float,
) -> dict[str, Any]:
    """Find the newest workflow_dispatch run created around dispatch time."""
    deadline = time.time() + timeout_s
    url = f"{API}/repos/{owner}/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
    while time.time() < deadline:
        resp = http.get(
            url,
            headers=headers,
            params={"event": "workflow_dispatch", "per_page": 5},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"List Actions runs failed HTTP {resp.status_code}: {resp.text[:400]}"
            )
        runs = resp.json().get("workflow_runs") or []
        for run in runs:
            if not isinstance(run, dict):
                continue
            # Prefer runs created after dispatch
            created = run.get("created_at") or ""
            # ISO timestamps compare lexicographically
            if created:
                # Accept any in-progress/queued run from this workflow
                status = str(run.get("status") or "")
                if status in ("queued", "in_progress", "waiting", "requested", "pending"):
                    return run
                # Or recently completed (fast fail)
                if status == "completed" and run.get("id"):
                    # Only if very new — caller just dispatched
                    return run
        _emit(log, "flash: waiting for Actions run to appear…")
        time.sleep(3.0)
    raise RuntimeError(
        f"No Actions run appeared for {WORKFLOW_FILE} within {timeout_s:.0f}s. "
        f"Check https://github.com/{owner}/{repo}/actions"
    )
