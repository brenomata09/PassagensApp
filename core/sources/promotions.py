from __future__ import annotations

from core.sources.registry import PROMOTION_SOURCES, always_notify_promotions


def list_promotions() -> list[dict]:
    return list(PROMOTION_SOURCES)


def list_always_notify_promotions() -> list[dict]:
    return always_notify_promotions()

