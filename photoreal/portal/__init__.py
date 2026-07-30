"""Launch portal: credentials UI, Stage-2 bootstrap, service supervisor."""

from __future__ import annotations

__all__ = ["create_app"]


def create_app():
    from photoreal.portal.app import create_app as _create

    return _create()
