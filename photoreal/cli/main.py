"""CLI entry for photoreal."""

from __future__ import annotations

import argparse
import sys


def _cmd_gen(args: argparse.Namespace) -> int:
    from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline

    pipe = PhotorealGenPipeline()
    paths = pipe.run(
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        seed=args.seed,
        steps=args.steps,
        guidance=args.guidance,
        lenovo_strength=args.lenovo_strength,
        mrpopo_strength=args.mrpopo_strength,
        with_snofs=args.with_snofs,
        comfy_url=args.comfy_url,
        output_dir=args.output_dir,
    )
    for p in paths:
        print(p)
    return 0


def _cmd_vlm(args: argparse.Namespace) -> int:
    from photoreal.pipelines.vision.vlm import VlmPipeline

    pipe = VlmPipeline()
    text = pipe.run(
        prompt=args.prompt,
        images=args.images,
        video=args.video,
        max_new_tokens=args.max_new_tokens,
        sampling_profile=args.sampling,
        model_path=args.model_path,
        require_media=args.require_media,
        unload=args.unload,
    )
    print(text)
    return 0


def _cmd_sam3(args: argparse.Namespace) -> int:
    import json

    from photoreal.pipelines.vision.sam3_segment import Sam3SegmentPipeline

    pos = json.loads(args.positive_coords or "[]")
    neg = json.loads(args.negative_coords or "[]")
    pipe = Sam3SegmentPipeline()
    paths = pipe.run(
        image=args.image,
        job=args.job,
        positive_coords=pos,
        negative_coords=neg,
        text_prompt=args.text_prompt or "",
        threshold=args.threshold,
        refine_iterations=args.refine_iterations,
        comfy_url=args.comfy_url,
        output_dir=args.output_dir,
    )
    for p in paths:
        print(p)
    return 0


def _cmd_reprompt(args: argparse.Namespace) -> int:
    from photoreal.pipelines.vision.reprompt import (
        BACKDROP_PROMPTS_PATH,
        CHARACTER_PROMPTS_PATH,
        PROMPTS_PATH,
        RepromptPipeline,
    )

    pack_map = {
        "popo": PROMPTS_PATH,
        "character": CHARACTER_PROMPTS_PATH,
        "backdrop": BACKDROP_PROMPTS_PATH,
    }
    pack_path = pack_map[args.pack]

    pipe = RepromptPipeline()
    rewritten = pipe.run(
        prompt=args.prompt,
        max_new_tokens=args.max_new_tokens,
        max_exemplars=args.max_exemplars,
        model_path=args.model_path,
        pack_path=pack_path,
        unload=True,
    )
    if args.gen:
        from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline

        print(rewritten, file=sys.stderr)
        paths = PhotorealGenPipeline().run(
            prompt=rewritten,
            width=args.width,
            height=args.height,
            seed=args.seed,
            steps=args.steps,
            guidance=args.guidance,
            with_snofs=args.with_snofs,
            comfy_url=args.comfy_url,
            output_dir=args.output_dir,
        )
        for p in paths:
            print(p)
        return 0

    print(rewritten)
    return 0


def _cmd_character_depth(args: argparse.Namespace) -> int:
    from photoreal.pipelines.image.character_depth import CharacterDepthPipeline

    pipe = CharacterDepthPipeline()
    paths = pipe.run(
        depth_image=args.depth,
        reference_image=args.reference,
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        seed=args.seed,
        steps=args.steps,
        guidance=args.guidance,
        lenovo_strength=args.lenovo_strength,
        mrpopo_strength=args.mrpopo_strength,
        refcontrol_strength=args.refcontrol_strength,
        comfy_url=args.comfy_url,
        output_dir=args.output_dir,
    )
    for p in paths:
        print(p)
    return 0


def _cmd_character_inpaint(args: argparse.Namespace) -> int:
    from photoreal.pipelines.image.character_inpaint import CharacterInpaintPipeline

    pipe = CharacterInpaintPipeline()
    paths = pipe.run(
        scene_image=args.scene,
        mask_image=args.mask,
        reference_image=args.reference,
        prompt=args.prompt,
        seed=args.seed,
        steps=args.steps,
        guidance=args.guidance,
        denoise=args.denoise,
        lenovo_strength=args.lenovo_strength,
        mrpopo_strength=args.mrpopo_strength,
        mask_channel=args.mask_channel,
        mask_expand=args.mask_expand,
        mask_feather=args.mask_feather,
        comfy_url=args.comfy_url,
        output_dir=args.output_dir,
    )
    for p in paths:
        print(p)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photoreal", description="Photoreal AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "gen",
        help="Run photoreal_gen (FLUX.2 Klein 9B Base + Lenovo + Mrpopo via ComfyUI)",
    )
    gen.add_argument("--prompt", "-p", required=True, help="Text prompt")
    gen.add_argument("--width", type=int, default=1024)
    gen.add_argument("--height", type=int, default=1024)
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--steps", type=int, default=28)
    gen.add_argument("--guidance", type=float, default=4.0, help="FluxGuidance value (Base ~4)")
    gen.add_argument("--lenovo-strength", type=float, default=0.85)
    gen.add_argument("--mrpopo-strength", type=float, default=1.0)
    gen.add_argument(
        "--with-snofs",
        action="store_true",
        help="Enable optional NSFW SNOFS LoRA (must be downloaded with --with-snofs)",
    )
    gen.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    gen.add_argument("--output-dir", default=None)
    gen.set_defaults(func=_cmd_gen)

    cdepth = sub.add_parser(
        "character-depth",
        help=(
            "Depth map + character reference via RefControl depth LoRA "
            "(Klein Base; Comfy must be running)"
        ),
    )
    cdepth.add_argument(
        "--depth",
        required=True,
        help="Person-only depth PNG (e.g. from depth_subject)",
    )
    cdepth.add_argument(
        "--reference",
        required=True,
        help="Character reference image (identity)",
    )
    cdepth.add_argument(
        "--prompt",
        "-p",
        default="refcontrol",
        help='Prompt (trigger "refcontrol" is auto-added if missing)',
    )
    cdepth.add_argument("--width", type=int, default=1024)
    cdepth.add_argument("--height", type=int, default=1024)
    cdepth.add_argument("--seed", type=int, default=None)
    cdepth.add_argument("--steps", type=int, default=28)
    cdepth.add_argument("--guidance", type=float, default=4.0)
    cdepth.add_argument("--lenovo-strength", type=float, default=0.85)
    cdepth.add_argument("--mrpopo-strength", type=float, default=1.0)
    cdepth.add_argument("--refcontrol-strength", type=float, default=0.9)
    cdepth.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    cdepth.add_argument("--output-dir", default=None)
    cdepth.set_defaults(func=_cmd_character_depth)

    cinpaint = sub.add_parser(
        "character-inpaint",
        help=(
            "Place character reference into masked scene region "
            "(Klein Base lighting bake; Comfy must be running)"
        ),
    )
    cinpaint.add_argument(
        "--scene",
        required=True,
        help="Scene plate image (original frame)",
    )
    cinpaint.add_argument(
        "--mask",
        required=True,
        help="Person mask PNG (e.g. from SAM3 segment)",
    )
    cinpaint.add_argument(
        "--reference",
        required=True,
        help="Character reference image (identity)",
    )
    cinpaint.add_argument(
        "--prompt",
        "-p",
        default=(
            "replace the person with the reference character, "
            "match scene lighting and camera, photorealistic"
        ),
        help="Edit prompt",
    )
    cinpaint.add_argument("--seed", type=int, default=None)
    cinpaint.add_argument("--steps", type=int, default=28)
    cinpaint.add_argument("--guidance", type=float, default=4.0)
    cinpaint.add_argument("--denoise", type=float, default=0.95)
    cinpaint.add_argument("--lenovo-strength", type=float, default=0.85)
    cinpaint.add_argument("--mrpopo-strength", type=float, default=1.0)
    cinpaint.add_argument(
        "--mask-channel",
        default="red",
        choices=("red", "green", "blue", "alpha"),
        help="LoadImageMask channel (grayscale SAM masks: red)",
    )
    cinpaint.add_argument("--mask-expand", type=int, default=6)
    cinpaint.add_argument("--mask-feather", type=int, default=8)
    cinpaint.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    cinpaint.add_argument("--output-dir", default=None)
    cinpaint.set_defaults(func=_cmd_character_inpaint)

    vlm = sub.add_parser(
        "vlm",
        help="Multimodal Q&A with Qwen3-VL-8B (images / video / text)",
    )
    vlm.add_argument("--prompt", "-p", required=True, help="Question or instruction")
    vlm.add_argument(
        "--images",
        "-i",
        nargs="+",
        default=None,
        help="Optional image path(s)",
    )
    vlm.add_argument("--video", "-v", default=None, help="Optional video path")
    vlm.add_argument("--max-new-tokens", type=int, default=512)
    vlm.add_argument(
        "--sampling",
        choices=("instruct", "deterministic"),
        default="instruct",
        help="Generation profile (default: instruct)",
    )
    vlm.add_argument(
        "--model-path",
        default=None,
        help="Local Qwen3-VL snapshot (default: data/models/vlm/Qwen3-VL-8B-Instruct)",
    )
    vlm.add_argument(
        "--require-media",
        action="store_true",
        help="Fail if neither images nor video are provided",
    )
    vlm.add_argument(
        "--unload",
        action="store_true",
        help="Unload VLM from VRAM after the reply (before Comfy)",
    )
    vlm.set_defaults(func=_cmd_vlm)

    reprompt = sub.add_parser(
        "reprompt",
        help="Rewrite a prompt in Popo photoreal style for photoreal_gen",
    )
    reprompt.add_argument("--prompt", "-p", required=True, help="User idea to rewrite")
    reprompt.add_argument(
        "--pack",
        choices=("popo", "character", "backdrop"),
        default="popo",
        help="Few-shot pack: popo (default), character (full-body studio), backdrop (cinematic scenery)",
    )
    reprompt.add_argument("--max-new-tokens", type=int, default=512)
    reprompt.add_argument("--max-exemplars", type=int, default=8)
    reprompt.add_argument("--model-path", default=None)
    reprompt.add_argument(
        "--gen",
        action="store_true",
        help="After rewrite, unload VLM and run photoreal_gen (Comfy must be running)",
    )
    reprompt.add_argument("--width", type=int, default=1024)
    reprompt.add_argument("--height", type=int, default=1024)
    reprompt.add_argument("--seed", type=int, default=None)
    reprompt.add_argument("--steps", type=int, default=28)
    reprompt.add_argument("--guidance", type=float, default=4.0)
    reprompt.add_argument("--with-snofs", action="store_true")
    reprompt.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    reprompt.add_argument("--output-dir", default=None)
    reprompt.set_defaults(func=_cmd_reprompt)

    sam3 = sub.add_parser(
        "sam3",
        help="SAM 3.1 segmentation via ComfyUI (text and/or point prompts)",
    )
    sam3.add_argument("--image", "-i", required=True, help="Input image path")
    sam3.add_argument(
        "--job",
        choices=("image_mask", "image_rgba"),
        default="image_mask",
        help="image_mask = mask PNG; image_rgba = cutout with alpha",
    )
    sam3.add_argument(
        "--text-prompt",
        "-p",
        default="",
        help='Concept text prompt, e.g. "person" (optional if points given)',
    )
    sam3.add_argument(
        "--positive-coords",
        default="[]",
        help='JSON list of {"x","y"} positive points (optional if text given)',
    )
    sam3.add_argument(
        "--negative-coords",
        default="[]",
        help='JSON list of {"x","y"} negative points',
    )
    sam3.add_argument("--threshold", type=float, default=0.5)
    sam3.add_argument("--refine-iterations", type=int, default=2)
    sam3.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    sam3.add_argument("--output-dir", default=None)
    sam3.set_defaults(func=_cmd_sam3)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = args.func(args)
    except Exception as e:  # noqa: BLE001 — CLI boundary
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    raise SystemExit(code)


if __name__ == "__main__":
    main()
