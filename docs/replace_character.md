# Replace Character (timeline stages)

Staged right-click / preview menu on timeline clips for preparing a
pose-accurate character still (later: Wan animate). **Not** a single auto-chain button.

## Stages

| Menu | Requires | Does |
|------|----------|------|
| **Segment** | Media clip | SAM3 on first frame for `role=reference` clips (else playhead), always `text_prompt=person`. Returns mask + frame + **bg-removed cutout**. Shows a blocking operation log until the job finishes. **Show Segment** swaps preview to cutout. |
| **Depth** | Segment mask + frame | `depth_subject` person-only depth from the **reference** plate. **Show Depth** preview overlay. |
| **Character Reference** | Segment cutout + overlapping **`role=location`** | Hover gallery → composite cutout onto Location plate → `character_inpaint`. Lighting from Location, not the reference plate. |
| **Pose Lock** | Depth + inpaint bake | `character_depth` RefControl using ref depth + lighting bake. **Show Pose Lock** preview. |
| **Wan Animate** | Pose Lock + video `src` | First chunk → new `role=animate` clip on **Animate** track. |
| **Extend Animate** | `role=animate` clip | Next chunk via `continue_motion` + offset; auto-shortens if ref ends. |

Driving fps is preserved on output (prefer 24 fps capture). See [wan_animate.md](wan_animate.md).

### Backdrop auto-detect

At segment timeline time, pick an overlapping clip with **`role=location`** (from **Create Location** → image onto the Locations track). Untagged imports and other media are ignored so Character Reference does not pick a random overlapping B-roll. Without an overlapping Location plate, Character Reference stays disabled.

Mask inpaint alone does **not** lock pose; Pose Lock is required before Wan sync.

### Reference slots

Each **Record Reference** save gets an auto-incremented `refSlot` (1, 2, …) with badge `ref1` / `ref2` and default name `Reference N`. Stack multiple takes for a conversation now; Replace Character still runs **per clip**. Binding different gallery characters per slot is a later step.

## Portal APIs

| Endpoint | Role |
|----------|------|
| `POST /api/sam3/segment` | Existing; job now includes `cutout_url` |
| `POST /api/depth/convert` | Existing person-only depth |
| `POST /api/character/inpaint` | Multipart scene (client composite) + mask + reference |
| `GET /api/character/inpaint/jobs/{id}` | Poll bake |
| `POST /api/character/pose-lock` | Multipart depth + bake |
| `GET /api/character/pose-lock/jobs/{id}` | Poll pose lock |

Static: `/sam3-outputs`, `/depth-outputs`, `/inpaint-outputs`, `/pose-lock-outputs`, `/character-outputs`.

## Clip fields

`segmentMaskUrl`, `segmentFrameUrl`, `segmentCutoutUrl`, `showSegment`, `depthUrl`, `showDepth`, `inpaintUrl`, `showInpaint`, `backdropClipId`, `poseLockUrl`, `showPoseLock`, plus on references `role=reference` and `refSlot`. Animate outputs: `role=animate` with `drivingVideoSrc`, `characterStillUrl`, `videoFrameOffset`, `wanLength`, `wanFps`, `drivingFrameCount`.

Preview priority: Pose Lock → Character Reference (inpaint) → Depth → Segment → media.

## Persistence

The timeline **autosaves** a default project document to
`data/workspace/projects/default/project.json` (API: `GET/PUT /api/project`).
User-authored media (imports, Record Reference WebMs, Location plates) is
uploaded via `POST /api/project/media` and served from `/project-media/`.

Pipeline stage files remain under `data/outputs/{sam3_segment,depth_subject,…}`
with existing static mounts. Clip fields above store those URLs so the full
Segment → Depth → Inpaint → Pose Lock → Wan graph reloads after refresh.
Gallery characters used for inpaint are listed in `characters.usedUrls`.
Undo stacks and in-flight job maps are not persisted.
