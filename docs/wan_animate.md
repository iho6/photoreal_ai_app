# `wan_animate`

Wan2.2 **Animate — Animation (Move) mode**: drive a pose-locked character still
with performer motion from a reference video. Local GPU / Comfy only.

## Product mapping (Replace Character)

| Input | Source |
|-------|--------|
| Character still | Pose Lock (`poseLockUrl`) |
| Driving video | Reference clip `src` |

Timeline: **Wan Animate** (after Pose Lock) creates a `role=animate` clip on the
**Animate** track. **Extend Animate** on that clip continues with
`continue_motion` + frame offset when the ref is longer than one chunk.

## FPS / cinematic

Output fps **matches the driving video** (detected via ffprobe or timeline probe;
fallback **24**). Higher fps is **not** more cinematic (film ≈ 24) and burns the
77-frame chunk budget faster. Prefer capturing refs at **24 fps**.

Pose/face frames stay 1:1 with driving frames; timeline duration uses
`wanLength / wanFps` (minus overlap trim on Extend) so chunks stay time-aligned.

## Length / Extend

- Max **77** frames per click (Wan single-chunk limit; step-aligned `1+4k`).
- `length = min(77, remaining_driving_frames)` — auto-shorten when the ref ends.
- Extend disabled when remaining ≤ 0.
- Temporal glue: last N frames of the prior animate video → `continue_motion`
  (default N=5); stable Pose Lock still; seek via `video_frame_offset`.

## Setup

```bash
python scripts/download_models.py --wan-animate
# Restart ComfyUI after custom node install
```

## Structure

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/video/wan_animate.py` |
| Workflow | `photoreal/pipelines/video/workflows/wan_animate_api.json` |
| Portal | `POST /api/wan-animate`, `GET /api/wan-animate/jobs/{id}` |
| Outputs | `data/outputs/wan_animate/` (`/wan-animate-outputs`) |

## CLI

```bash
photoreal wan-animate \
  --character pose_lock.png \
  --video reference.mp4 \
  -p "a person moving naturally, photorealistic"

# Extend chunk
photoreal wan-animate \
  --character pose_lock.png \
  --video reference.mp4 \
  --offset 77 \
  --continue-motion prev_chunk.mp4 \
  --driving-frames 200
```

`--fps` omitted → detect from driving (else 24). LightX2V defaults: 4 steps, cfg ~1.

## Out of scope (still)

Flash worker, auto extend-to-end, Replacement/Mix, audio mux.

See also: [replace_character.md](replace_character.md), [architecture.md](architecture.md).
