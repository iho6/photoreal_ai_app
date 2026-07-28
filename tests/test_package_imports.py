"""Smoke tests: package structure imports cleanly."""

from __future__ import annotations


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

    assert Invoker is not None
    assert ImageService is not None
    assert ModelService is not None
    assert QueueService is not None
    assert StorageService is not None
