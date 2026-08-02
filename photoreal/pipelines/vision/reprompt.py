"""reprompt — rewrite prompts in Popo photoreal style for photoreal_gen."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.vlm_engine import (
    DEFAULT_LOCAL_DIR,
    VlmEngine,
    get_vlm_engine,
    unload_vlm_engine,
)

PROMPTS_PATH = (
    Path(__file__).resolve().parent / "prompts" / "popo_photoreal_reprompt.json"
)
CHARACTER_PROMPTS_PATH = (
    Path(__file__).resolve().parent / "prompts" / "character_reprompt.json"
)
BACKDROP_PROMPTS_PATH = (
    Path(__file__).resolve().parent / "prompts" / "backdrop_reprompt.json"
)

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def load_popo_pack(path: Path | None = None) -> dict[str, Any]:
    p = path or PROMPTS_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def build_reprompt_messages(
    user_prompt: str,
    *,
    pack: dict[str, Any] | None = None,
    max_exemplars: int = 8,
) -> list[dict[str, Any]]:
    """Few-shot chat messages: system + exemplar pairs + user request."""
    data = pack or load_popo_pack()
    system = str(data.get("system") or "").strip()
    exemplars = list(data.get("exemplars") or [])[:max_exemplars]

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})

    for ex in exemplars:
        u = str(ex.get("user") or "").strip()
        r = str(ex.get("rewritten") or "").strip()
        if not u or not r:
            continue
        messages.append({"role": "user", "content": u})
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps({"rewritten": r}, ensure_ascii=False),
            }
        )

    messages.append({"role": "user", "content": user_prompt.strip()})
    return messages


def parse_rewritten(raw: str) -> str:
    """Extract rewritten prompt from model JSON (or plain text fallback)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty VLM response")

    # Strip optional markdown fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    candidates = [text]
    match = _JSON_RE.search(text)
    if match:
        candidates.insert(0, match.group(0))

    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            for key in ("rewritten", "Rewritten", "prompt", "Prompt"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()

    # Last resort: treat whole reply as the prompt if it looks like prose.
    if len(text) > 20 and not text.startswith("{"):
        return text
    raise ValueError(f"could not parse rewritten prompt from: {raw[:200]!r}")


class RepromptPipeline(Pipeline):
    """Popo-style photoreal prompt rewriter for photoreal_gen."""

    id = "reprompt"
    domain = "vision"

    def validate(self, *, prompt: str = "", **kwargs: Any) -> None:
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt is required and must be non-empty")

    def run(
        self,
        *,
        prompt: str,
        max_new_tokens: int = 512,
        max_exemplars: int = 8,
        model_path: str | Path | None = None,
        pack_path: str | Path | None = None,
        unload: bool = True,
        engine: VlmEngine | None = None,
        log: Any = None,
        **kwargs: Any,
    ) -> str:
        """
        Rewrite ``prompt`` into a Popo photoreal string.

        unload defaults True so callers can chain into photoreal_gen on 24 GB GPUs.
        Optional ``log`` is a callable(str) for test/debug streaming.
        """
        def _emit(msg: str) -> None:
            if callable(log):
                try:
                    log(msg)
                except Exception:  # noqa: BLE001
                    pass

        self.validate(prompt=prompt)
        settings = get_settings()
        path = (
            Path(model_path)
            if model_path
            else Path(settings.data_root) / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
        )
        if not path.exists():
            path = DEFAULT_LOCAL_DIR

        _emit(f"reprompt: model_path = {path}")
        pack = load_popo_pack(Path(pack_path) if pack_path else None)
        messages = build_reprompt_messages(
            prompt, pack=pack, max_exemplars=max_exemplars
        )
        _emit(
            f"reprompt: messages = {len(messages)} "
            f"(system+exemplars+user, max_exemplars={max_exemplars})"
        )
        eng = engine or get_vlm_engine(path)
        try:
            _emit(f"reprompt: VLM generate (max_new_tokens={max_new_tokens})…")
            raw = eng.generate(
                messages,
                max_new_tokens=max_new_tokens,
                sampling_profile="deterministic",
            )
            raw_s = raw if isinstance(raw, str) else str(raw)
            limit = 4000
            shown = raw_s if len(raw_s) <= limit else raw_s[:limit] + f"… (+{len(raw_s) - limit} chars)"
            _emit(f"reprompt: raw VLM response ({len(raw_s)} chars):\n{shown}")
            rewritten = parse_rewritten(raw_s)
            _emit("reprompt: parsed rewritten prompt OK")
            return rewritten
        finally:
            if unload:
                _emit("reprompt: unloading VLM…")
                eng.unload()
                unload_vlm_engine()
                _emit("reprompt: VLM unloaded")
