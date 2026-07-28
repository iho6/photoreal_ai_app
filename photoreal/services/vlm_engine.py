"""Qwen3-VL engine via official Hugging Face Transformers API.

Uses Qwen3VLForConditionalGeneration + AutoProcessor.apply_chat_template
(tokenize=True, return_dict=True). Not a student/ad-hoc Vision2Seq wrapper.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, Literal, Sequence

SamplingProfile = Literal["deterministic", "instruct"]

DEFAULT_MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_LOCAL_DIR = Path("data/models/vlm/Qwen3-VL-8B-Instruct")

# Cap visual tokens for ~24 GB consumer GPUs (image + video).
_DEFAULT_IMAGE_SIZE = {"longest_edge": 1280 * 28 * 28}
_DEFAULT_VIDEO_SIZE = {"longest_edge": 384 * 28 * 28}

_SAMPLING: dict[SamplingProfile, dict[str, Any]] = {
    "deterministic": {
        "do_sample": False,
    },
    "instruct": {
        "do_sample": True,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
    },
}


class VlmEngineError(RuntimeError):
    """Raised when the VLM engine cannot load or generate."""


def resolve_media_uri(path: str | Path) -> str:
    """Turn a local path into an absolute path string HF processor accepts."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"media not found: {p}")
    return str(p.resolve())


def build_user_content(
    *,
    prompt: str,
    images: Sequence[str | Path] | None = None,
    video: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Build a Qwen3-VL user content list (images, optional video, then text)."""
    content: list[dict[str, Any]] = []
    for img in images or []:
        content.append({"type": "image", "image": resolve_media_uri(img)})
    if video is not None:
        content.append({"type": "video", "video": resolve_media_uri(video)})
    content.append({"type": "text", "text": prompt})
    return content


def build_messages(
    *,
    prompt: str,
    images: Sequence[str | Path] | None = None,
    video: str | Path | None = None,
    system: str | None = None,
) -> list[dict[str, Any]]:
    """Build a full chat messages list for Qwen3-VL."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": build_user_content(prompt=prompt, images=images, video=video),
        }
    )
    return messages


class VlmEngine:
    """Lazy-loaded Transformers Qwen3-VL with explicit unload for VRAM reclaim."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        attn_implementation: str | None = None,
        max_image_longest_edge: int | None = None,
        max_video_longest_edge: int | None = None,
    ) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_LOCAL_DIR
        self._attn_preference = attn_implementation  # None = try flash_attn2 then sdpa
        self._max_image_edge = max_image_longest_edge
        self._max_video_edge = max_video_longest_edge
        self._model: Any = None
        self._processor: Any = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    def load(self) -> None:
        if self.is_loaded:
            return

        try:
            import torch
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        except ImportError as e:
            raise VlmEngineError(
                "VLM deps missing. Install with: pip install -e '.[vlm]'"
            ) from e

        source = str(self.model_path)
        if not self.model_path.exists():
            # Fall back to Hub id when local snapshot is absent (dev / HF cache).
            source = DEFAULT_MODEL_ID

        attn = self._attn_preference
        if attn is None:
            attn = self._pick_attn_implementation()

        load_kwargs: dict[str, Any] = {
            "dtype": "auto",
            "device_map": "auto",
        }
        if attn:
            load_kwargs["attn_implementation"] = attn

        try:
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                source, **load_kwargs
            )
        except Exception as first:
            if attn and attn != "sdpa":
                load_kwargs["attn_implementation"] = "sdpa"
                try:
                    self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                        source, **load_kwargs
                    )
                except Exception as second:
                    raise VlmEngineError(
                        f"Failed to load Qwen3-VL from {source}: {second}"
                    ) from second
            else:
                raise VlmEngineError(
                    f"Failed to load Qwen3-VL from {source}: {first}"
                ) from first

        self._processor = AutoProcessor.from_pretrained(source)
        self._apply_vision_budget()
        # Silence unused torch import warning when only used for CUDA empty below.
        _ = torch

    def _pick_attn_implementation(self) -> str:
        try:
            import flash_attn  # noqa: F401

            return "flash_attention_2"
        except ImportError:
            return "sdpa"

    def _apply_vision_budget(self) -> None:
        """Cap image/video token budget for 24 GB cards."""
        assert self._processor is not None
        img_edge = self._max_image_edge or _DEFAULT_IMAGE_SIZE["longest_edge"]
        vid_edge = self._max_video_edge or _DEFAULT_VIDEO_SIZE["longest_edge"]
        try:
            if hasattr(self._processor, "image_processor") and self._processor.image_processor is not None:
                self._processor.image_processor.size = {"longest_edge": img_edge}
        except Exception:
            pass
        try:
            if hasattr(self._processor, "video_processor") and self._processor.video_processor is not None:
                self._processor.video_processor.size = {"longest_edge": vid_edge}
        except Exception:
            pass

    def unload(self) -> None:
        """Release model weights and free CUDA cache when available."""
        self._model = None
        self._processor = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _model_device(self) -> Any:
        assert self._model is not None
        try:
            return self._model.device
        except Exception:
            return next(self._model.parameters()).device

    def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        max_new_tokens: int = 512,
        sampling_profile: SamplingProfile = "instruct",
    ) -> str:
        """Run one chat turn; returns decoded assistant text."""
        self.load()
        assert self._model is not None and self._processor is not None

        if sampling_profile not in _SAMPLING:
            raise ValueError(
                f"unknown sampling_profile={sampling_profile!r}; "
                f"expected one of {tuple(_SAMPLING)}"
            )

        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self._model_device())

        gen_kwargs = dict(_SAMPLING[sampling_profile])
        generated = self._model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            **gen_kwargs,
        )
        trimmed = [
            out_ids[len(in_ids) :]
            for in_ids, out_ids in zip(inputs.input_ids, generated)
        ]
        texts = self._processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        return (texts[0] if texts else "").strip()


# Process-wide singleton for sequential VLM → Comfy workflows.
_ENGINE: VlmEngine | None = None


def get_vlm_engine(model_path: str | Path | None = None) -> VlmEngine:
    """Return a shared VlmEngine (recreated if model_path differs)."""
    global _ENGINE
    path = Path(model_path) if model_path else DEFAULT_LOCAL_DIR
    if _ENGINE is None or Path(_ENGINE.model_path) != path:
        if _ENGINE is not None and _ENGINE.is_loaded:
            _ENGINE.unload()
        _ENGINE = VlmEngine(model_path=path)
    return _ENGINE


def unload_vlm_engine() -> None:
    """Unload the shared engine if present."""
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.unload()
