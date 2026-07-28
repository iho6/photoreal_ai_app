"""Smoke tests: package structure, VLM helpers, download flags (no GPU)."""

from __future__ import annotations

import json
from pathlib import Path


def test_photoreal_version() -> None:
    import photoreal

    assert photoreal.__version__


def test_import_pipelines() -> None:
    import photoreal.pipelines
    from photoreal.pipelines.base import Pipeline

    assert Pipeline is not None


def test_import_api() -> None:
    import photoreal.api
    from photoreal.api.routes import health

    assert health.health()["status"] == "ok"


def test_import_app_and_services() -> None:
    from photoreal.app.invoker import Invoker
    from photoreal.services.images import ImageService
    from photoreal.services.models import ModelService
    from photoreal.services.queue import QueueService
    from photoreal.services.storage import StorageService
    from photoreal.services.vlm_engine import VlmEngine, build_messages

    assert Invoker is not None
    assert ImageService is not None
    assert ModelService is not None
    assert QueueService is not None
    assert StorageService is not None
    assert VlmEngine is not None
    assert build_messages is not None


def test_photoreal_gen_pipeline_and_workflow() -> None:
    from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline, WORKFLOW_PATH
    from photoreal.services.comfy_client import load_workflow_template

    pipe = PhotorealGenPipeline()
    assert pipe.id == "photoreal_gen"
    assert WORKFLOW_PATH.is_file()
    wf = load_workflow_template(WORKFLOW_PATH)
    assert "1" in wf and wf["1"]["class_type"] == "UNETLoader"
    assert Path("scripts/download_models.py").is_file()


def test_vlm_and_reprompt_pipelines() -> None:
    from photoreal.pipelines.vision import RepromptPipeline, VlmPipeline
    from photoreal.pipelines.vision.reprompt import PROMPTS_PATH, load_popo_pack, parse_rewritten
    from photoreal.services.vlm_engine import build_messages, build_user_content

    vlm = VlmPipeline()
    assert vlm.id == "vlm"
    assert vlm.domain == "vision"

    rep = RepromptPipeline()
    assert rep.id == "reprompt"

    assert PROMPTS_PATH.is_file()
    pack = load_popo_pack()
    assert pack.get("system")
    assert len(pack.get("exemplars") or []) >= 6
    assert pack.get("version", 0) >= 2

    assert parse_rewritten('{"rewritten": "studio portrait, 85mm"}') == "studio portrait, 85mm"
    assert parse_rewritten('{"Rewritten": "alt"}') == "alt"
    assert parse_rewritten('Here you go:\n```json\n{"rewritten": "x"}\n```') == "x"

    content = build_user_content(prompt="hi", images=None, video=None)
    assert content == [{"type": "text", "text": "hi"}]
    msgs = build_messages(prompt="q", system="sys")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_vlm_cli_parser() -> None:
    from photoreal.cli.main import build_parser

    p = build_parser()
    args = p.parse_args(["vlm", "-p", "hello", "--images", "a.png", "b.png"])
    assert args.command == "vlm"
    assert args.prompt == "hello"
    assert args.images == ["a.png", "b.png"]

    args2 = p.parse_args(["reprompt", "-p", "cafe", "--gen"])
    assert args2.command == "reprompt"
    assert args2.gen is True


def test_download_models_cli_flags() -> None:
    import importlib.util

    import pytest

    path = Path("scripts/download_models.py")
    spec = importlib.util.spec_from_file_location("download_models", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.selected_abilities(mod.build_parser().parse_args([])) == []
    assert mod.selected_abilities(mod.build_parser().parse_args(["--photoreal-gen"])) == [
        "photoreal_gen"
    ]
    assert mod.selected_abilities(mod.build_parser().parse_args(["--vlm"])) == ["vlm"]
    assert mod.selected_abilities(mod.build_parser().parse_args(["--all"])) == [
        "photoreal_gen",
        "vlm",
    ]
    assert "vlm" in mod.ABILITY_DOWNLOADERS
    assert mod.HF_VLM_REPO == "Qwen/Qwen3-VL-8B-Instruct"

    with pytest.raises(SystemExit):
        mod.main([])


def test_reprompt_message_builder() -> None:
    from photoreal.pipelines.vision.reprompt import build_reprompt_messages, load_popo_pack

    pack = load_popo_pack()
    msgs = build_reprompt_messages("quick idea", pack=pack, max_exemplars=2)
    assert msgs[0]["role"] == "system"
    # 1 system + 2*(user+assistant) + final user
    assert len(msgs) == 1 + 4 + 1
    assert msgs[-1]["content"] == "quick idea"
    assert json.loads(msgs[2]["content"])["rewritten"]
