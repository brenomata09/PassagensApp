from __future__ import annotations

import time
import uuid
from datetime import date
from math import isfinite
from collections import defaultdict
from core.config import settings
from core.routes import load_routes
from core import storage
from core.alerts import process, send_sweep_summary
from core.ceilings import calculate_monthly_ceilings
from core.sources import enabled_sources
from core.sweep_lock import acquire_sweep_lock

LEG_SNAPSHOTS_SAVED = 1
MAX_COMBINATIONS_SAVED = 1
MONTHLY_COMBINATIONS_SAVED = 1
MIN_STAY_DAYS = 4
MAX_STAY_DAYS = 20

SOURCE_FAILURE_STREAKS: dict[str, int] = defaultdict(int)

def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


CALENDAR_RANGE_SOURCES = {
    "kayak_browser",
    "kiwi_browser",
    "skyscanner_browser",
}


def _is_plausible_total_row(route, item: dict) -> tuple[bool, str | None]:
    try:
        price = float(item["price"])
    except Exception:
        return False, "preco_invalido"
    if not isfinite(price) or price <= 0:
        return False, "preco_invalido"

    departure = item.get("departure_date")
    return_date = item.get("return_date")
    if not departure or not return_date:
        return False, "datas_incompletas"

    try:
        dep = _parse_date(departure)
        ret = _parse_date(return_date)
    except Exception:
        return False, "data_invalida"

    if ret <= dep:
        return False, "volta_antes_da_ida"

    duration = (ret - dep).days
    source_name = str(item.get("source") or "").strip()
    if source_name not in CALENDAR_RANGE_SOURCES and (duration < MIN_STAY_DAYS or duration > MAX_STAY_DAYS):
        return False, "duracao_fora_da_janela"

    ceiling = route.price_ceiling_total
    if ceiling is not None and price > float(ceiling) * 20:
        return False, "preco_fora_da_faixa"

    return True, None

def _combine_legs(route, outbound_rows: list[dict], return_rows: list[dict], source_name: str = "unknown") -> list[dict]:
    combinations = []
    for outbound in outbound_rows:
        outbound_date = _parse_date(outbound["departure_date"])
        for return_leg in return_rows:
            return_date = _parse_date(return_leg["departure_date"])
            duration = (return_date - outbound_date).days
            if duration < MIN_STAY_DAYS or duration > MAX_STAY_DAYS:
                continue

            price = float(outbound["price"]) + float(return_leg["price"])
            combinations.append({
                "source": source_name,
                "origin": route.origin,
                "destination": route.destination,
                "snapshot_kind": "TOTAL",
                "departure_date": outbound["departure_date"],
                "return_date": return_leg["departure_date"],
                "trip_duration": duration,
                "price": price,
                "currency": outbound.get("currency") or return_leg.get("currency") or route.currency,
                "raw": {
                    "strategy": "calendar_leg_combinations",
                    "source": source_name,
                    "outbound": outbound,
                    "return": return_leg,
                },
            })

    return sorted(combinations, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))

def _select_combinations_to_save(combinations: list[dict]) -> list[dict]:
    selected: dict[tuple[str, str], dict] = {}

    for item in combinations[:MAX_COMBINATIONS_SAVED]:
        selected[(item["departure_date"], item["return_date"])] = item

    months = sorted({str(item["departure_date"])[:7] for item in combinations})
    for month in months:
        month_items = [item for item in combinations if str(item["departure_date"])[:7] == month]
        for item in month_items[:MONTHLY_COMBINATIONS_SAVED]:
            selected[(item["departure_date"], item["return_date"])] = item

    return sorted(selected.values(), key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))


def _call_with_retry(source_name: str, fn, errors: list[str], retry_count: int = 3):
    last_exc = None
    for attempt in range(1, retry_count + 1):
        try:
            result = fn()
            SOURCE_FAILURE_STREAKS[source_name] = 0
            return result
        except Exception as exc:
            last_exc = exc
            errors.append(f"{source_name}: tentativa {attempt}/{retry_count}: {type(exc).__name__}: {exc}")
            time.sleep(1.0 * attempt)

    SOURCE_FAILURE_STREAKS[source_name] += 1
    if SOURCE_FAILURE_STREAKS[source_name] >= 3:
        errors.append(f"{source_name}: circuit_breaker_aberto apos {SOURCE_FAILURE_STREAKS[source_name]} falhas")
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{source_name}: falha desconhecida")

def run_sweep():
    with acquire_sweep_lock():
        storage.init_db()

        routes = [r for r in load_routes() if r.is_active]
        routes = storage.sync_routes(routes)
        sources = enabled_sources()

        batch_id = str(uuid.uuid4())
        storage.start_sweep(batch_id, len(routes))

        ok = 0
        fail = 0
        snapshots = 0
        alerts = 0
        errors = []

        for route in routes:
            try:
                route_success = False
                for source in sources:
                    if SOURCE_FAILURE_STREAKS.get(source.name, 0) >= 3:
                        errors.append(f"{route.origin}->{route.destination} [{source.name}]: fonte_pulada_por_circuit_breaker")
                        continue
                    try:
                        if hasattr(source, "search_total"):
                            total_rows = _call_with_retry(source.name, lambda: source.search_total(route), errors)
                            inserted_rows = 0
                            total_rows = sorted(
                                total_rows,
                                key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]),
                            )[:LEG_SNAPSHOTS_SAVED]
                            for item in total_rows:
                                ok_row, reason = _is_plausible_total_row(route, item)
                                if not ok_row:
                                    errors.append(
                                        f"{route.origin}->{route.destination} [{source.name}]: "
                                        f"snapshot_descartado:{reason}"
                                    )
                                    continue
                                storage.insert_snapshot(route.id, "TOTAL", item, batch_id)
                                snapshots += 1
                                inserted_rows += 1
                            if inserted_rows:
                                route_success = True
                        else:
                            outbound_rows, return_rows = _call_with_retry(source.name, lambda: source.search_legs(route), errors)
                            combined_rows = _combine_legs(route, outbound_rows, return_rows, source.name)
                            best_combined = _select_combinations_to_save(combined_rows)[:LEG_SNAPSHOTS_SAVED]
                            inserted_rows = 0

                            for item in best_combined:
                                ok_row, reason = _is_plausible_total_row(route, item)
                                if not ok_row:
                                    errors.append(
                                        f"{route.origin}->{route.destination} [{source.name}]: "
                                        f"snapshot_descartado:{reason}"
                                    )
                                    continue
                                storage.insert_snapshot(route.id, "TOTAL", item, batch_id)
                                snapshots += 1
                                inserted_rows += 1
                            if inserted_rows:
                                route_success = True
                    except Exception as source_exc:
                        errors.append(
                            f"{route.origin}->{route.destination} [{source.name}]: "
                            f"{type(source_exc).__name__}: {source_exc}"
                        )
                        continue

                    time.sleep(settings.route_delay_seconds)

                if route_success:
                    best = storage.best_in_batch(route.id, batch_id, "TOTAL")
                    if process(route, best, batch_id):
                        alerts += 1
                    ok += 1
                else:
                    fail += 1
                    errors.append(f"{route.origin}->{route.destination}: nenhuma fonte retornou resultado.")
            except Exception as e:
                fail += 1
                errors.append(f"{route.origin}->{route.destination}: {type(e).__name__}: {e}")

            time.sleep(settings.route_delay_seconds)

        storage.end_sweep(batch_id, ok, fail, snapshots, alerts, "\n".join(errors))
        calculate_monthly_ceilings(batch_id)
        send_sweep_summary(batch_id, routes)

        return {
            "batch_id": batch_id,
            "routes_total": len(routes),
            "routes_success": ok,
            "routes_failed": fail,
            "snapshots_saved": snapshots,
            "alerts_sent": alerts,
            "errors": errors,
        }

if __name__ == "__main__":
    print(run_sweep())
