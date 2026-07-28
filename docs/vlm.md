# vlm + reprompt

Multimodal **Qwen3-VL-8B-Instruct** for vision Q&A (`vlm`) and Popo-style photoreal prompt rewriting (`reprompt`) ahead of `photoreal_gen`.

Inference uses the official Hugging Face path: `Qwen3VLForConditionalGeneration` + `AutoProcessor.apply_chat_template(..., tokenize=True, return_dict=True)`. Prefer `flash_attention_2` when available; otherwise `sdpa`. Optional production serving with **vLLM** is out of scope for v1 (Transformers only).

## VRAM

| Card | Notes |
|------|--------|
| 3090 / 4090 (24 GB) | ~19 GB BF16 for 8B; **do not** co-load with Klein 9B — unload VLM before Comfy |
| 5090 (32 GB) | More headroom; still default to sequential unload |

Vision token budget is capped in `photoreal/services/vlm_engine.py` for consumer GPUs. Video needs more budget than stills — keep clips short.

## Install + download

```bash
pip install -e ".[vlm]"
# torch / CUDA: install a build matching your GPU if not already present
python scripts/download_models.py --vlm
# or with photoreal_gen:
# python scripts/download_models.py --all
```

Weights: `data/models/vlm/Qwen3-VL-8B-Instruct`. Manifest: `data/models/vlm_manifest.json`.

**Windows note:** `flash-attn` wheels often fail; the engine falls back to `sdpa` automatically. `ffmpeg` on PATH helps for some video URL edge cases; local files work via Transformers processor.

## CLI

```bash
# text-only or multimodal
photoreal vlm -p "Describe this scene." --images shot.png
photoreal vlm -p "What happens in this clip?" --video clip.mp4
photoreal vlm -p "Explain aperture in one sentence."

# Popo photoreal rewrite (prints one optimized prompt)
photoreal reprompt -p "woman in a cafe by the window"

# rewrite then generate (unloads VLM, then needs Comfy running)
photoreal reprompt -p "studio portrait" --gen
```

## Layout

| Piece | Path |
|-------|------|
| Engine | `photoreal/services/vlm_engine.py` |
| Ability `vlm` | `photoreal/pipelines/vision/vlm.py` |
| Ability `reprompt` | `photoreal/pipelines/vision/reprompt.py` |
| Few-shot pack | `photoreal/pipelines/vision/prompts/popo_photoreal_reprompt.json` |

Few-shots are **SFW** prompts manually pasted from Mrpopo714 (long photographic / surreal NL). Comfy metadata (`Steps` / `CFG` / `Sampler`) is stripped from exemplars.
