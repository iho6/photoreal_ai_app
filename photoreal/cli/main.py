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


def _cmd_reprompt(args: argparse.Namespace) -> int:
    from photoreal.pipelines.vision.reprompt import RepromptPipeline

    pipe = RepromptPipeline()
    rewritten = pipe.run(
        prompt=args.prompt,
        max_new_tokens=args.max_new_tokens,
        max_exemplars=args.max_exemplars,
        model_path=args.model_path,
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
