from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from typing import Any
from core.config import settings
from core.models import Route

def find_fli() -> str:
    local = settings.root / "venv" / "Scripts" / "fli.exe"
    if local.exists():
        return str(local)
    found = shutil.which("fli")
    if found:
        return found
    raise RuntimeError("fli.exe nao encontrado")

def parse_price(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("R$", "").replace("BRL", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)

def normalize(
    payload: Any,
    route: Route,
    origin: str,
    destination: str,
    kind: str,
    trip_duration: int | None = None,
) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("dates"), list):
        rows = payload["dates"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise RuntimeError(f"Formato inesperado de retorno fli dates: {type(payload).__name__}")

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dep = row.get("departure_date") or row.get("date")
        ret = row.get("return_date")
        price = row.get("price")
        if not dep or price is None:
            continue
        out.append({
            "origin": origin,
            "destination": destination,
            "snapshot_kind": kind,
            "departure_date": str(dep)[:10],
            "return_date": str(ret)[:10] if ret else None,
            "trip_duration": trip_duration if kind == "TOTAL" else None,
            "price": parse_price(price),
            "currency": row.get("currency") or route.currency,
            "raw": row,
        })
    return out

def search_dates(
    route: Route,
    kind: str = "TOTAL",
    origin: str | None = None,
    destination: str | None = None,
    start_offset_days: int = 1,
    end_offset_days: int | None = None,
    trip_duration: int | None = None,
) -> list[dict[str, Any]]:
    fli = find_fli()
    origin = origin or route.origin
    destination = destination or route.destination

    start = date.today() + timedelta(days=start_offset_days)
    end = date.today() + timedelta(days=end_offset_days or settings.sweep_days_ahead)

    cmd = [
        fli, "dates", origin, destination,
        "--from", start.isoformat(),
        "--to", end.isoformat(),
        "--currency", route.currency,
        "--format", "json",
    ]

    duration = trip_duration or route.trip_duration

    if kind == "TOTAL" and route.trip_type == "ROUND_TRIP":
        cmd += ["--round", "--duration", str(duration)]

    p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)

    if p.returncode != 0:
        raise RuntimeError("fli dates falhou\nCMD: " + " ".join(cmd) + "\nSTDERR:\n" + p.stderr[:2000])

    raw = p.stdout.strip()
    if not raw:
        raise RuntimeError("fli dates retornou vazio")

    payload = json.loads(raw)
    return normalize(payload, route, origin, destination, kind, duration if kind == "TOTAL" else None)


def search_dates_duration_range(
    route: Route,
    min_duration: int = 4,
    max_duration: int = 20,
    kind: str = "TOTAL",
    origin: str | None = None,
    destination: str | None = None,
    start_offset_days: int = 1,
    end_offset_days: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for duration in range(min_duration, max_duration + 1):
        rows.extend(
            search_dates(
                route=route,
                kind=kind,
                origin=origin,
                destination=destination,
                start_offset_days=start_offset_days,
                end_offset_days=end_offset_days,
                trip_duration=duration,
            )
        )
    return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))
