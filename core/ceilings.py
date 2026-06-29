"""
Cálculo de tetos mensais de preço.
Com MIN_SOURCES_FOR_CEILING = 1, o teto é calculado mesmo com uma única fonte.
"""
from __future__ import annotations

import json
from collections import defaultdict

from core import storage

DISCOUNT_PERCENT = 30.0
MIN_SOURCES_FOR_CEILING = 1  # era 5 — reduzido para funcionar com fonte única


def calculate_monthly_ceilings(batch_id: str, min_sources: int = MIN_SOURCES_FOR_CEILING) -> list[dict]:
    rows = storage.monthly_source_prices(batch_id)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for row in rows:
        grouped[(str(row["route_id"]), str(row["month"]))].append(dict(row))

    results = []
    for (route_id, month), items in grouped.items():
        source_names = sorted({str(item["data_source"]) for item in items})
        prices = [float(item["price"]) for item in items]
        sources_count = len(source_names)

        if sources_count >= min_sources:
            average_price = sum(prices) / len(prices)
            ceiling_price = average_price * (1 - DISCOUNT_PERCENT / 100)
            status = "CALCULATED"
        else:
            average_price = sum(prices) / len(prices) if prices else None
            ceiling_price = None
            status = "PENDING_SOURCES"

        result = {
            "route_id": route_id,
            "month": month,
            "average_price": average_price,
            "ceiling_price": ceiling_price,
            "discount_percent": DISCOUNT_PERCENT,
            "sources_count": sources_count,
            "status": status,
            "source_names": source_names,
        }
        storage.upsert_monthly_ceiling(result)
        results.append(result)

    return results


def serialize_sources(source_names: list[str]) -> str:
    return json.dumps(source_names, ensure_ascii=False)
