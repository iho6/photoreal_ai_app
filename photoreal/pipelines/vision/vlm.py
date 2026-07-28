"""vlm — multimodal Q&A with Qwen3-VL (images / video / text)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.vlm_engine import (
    DEFAULT_LOCAL_DIR,
    VlmEngine,
    build_messages,
    get_vlm_engine,
)


class VlmPipeline(Pipeline):
    """General vision-language ability (media optional)."""

    id = "vlm"
    domain = "vision"

    def validate(
        self,
        *,
        prompt: str = "",
        images: Sequence[str | Path] | None = None,
        video: str | Path | None = None,
        require_media: bool = False,
        **kwargs: Any,
    ) -> None:
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt is required and must be non-empty")
        if require_media and not images and video is None:
            raise ValueError("require_media=True but no images or video provided")
        for img in images or []:
            p = Path(img)
            if not p.is_file():
                raise FileNotFoundError(f"image not found: {p}")
        if video is not None:
            vp = Path(video)
            if not vp.is_file():
                raise FileNotFoundError(f"video not found: {vp}")

    def run(
        self,
        *,
        prompt: str,
        images: Sequence[str | Path] | None = None,
        video: str | Path | None = None,
        system: str | None = None,
        max_new_tokens: int = 512,
        sampling_profile: str = "instruct",
        model_path: str | Path | None = None,
        require_media: bool = False,
        unload: bool = False,
        engine: VlmEngine | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Run multimodal chat against local Qwen3-VL-8B-Instruct.

        Returns assistant text. Set unload=True to free VRAM after (before Comfy).
        """
        self.validate(
            prompt=prompt,
            images=images,
            video=video,
            require_media=require_media,
        )
        settings = get_settings()
        path = Path(model_path) if model_path else Path(settings.data_root) / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
        if not path.exists():
            path = DEFAULT_LOCAL_DIR

        eng = engine or get_vlm_engine(path)
        messages = build_messages(
            prompt=prompt,
            images=images,
            video=video,
            system=system,
        )
        try:
            return eng.generate(
                messages,
                max_new_tokens=max_new_tokens,
                sampling_profile=sampling_profile,  # type: ignore[arg-type]
            )
        finally:
            if unload:
                eng.unload()
