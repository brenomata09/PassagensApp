from __future__ import annotations

import json
import uuid
from pathlib import Path
from core.config import settings
from core.models import Route

DEFAULT_ROUTES = [
    {
        "id": "bsb-igu-7",
        "origin": "BSB",
        "destination": "IGU",
        "trip_type": "ROUND_TRIP",
        "trip_duration": 7,
        "cabin_class": "ECONOMY",
        "currency": "BRL",
        "price_ceiling_total": 900,
        "price_ceiling_outbound": 500,
        "price_ceiling_return": 500,
        "is_active": True,
        "label": "Brasilia -> Foz do Iguacu",
        "split_legs": True
    },
    {
        "id": "bsb-cac-7",
        "origin": "BSB",
        "destination": "CAC",
        "trip_type": "ROUND_TRIP",
        "trip_duration": 7,
        "cabin_class": "ECONOMY",
        "currency": "BRL",
        "price_ceiling_total": 900,
        "price_ceiling_outbound": 500,
        "price_ceiling_return": 500,
        "is_active": True,
        "label": "Brasilia -> Cascavel",
        "split_legs": True
    },
    {
        "id": "bsb-rec-7",
        "origin": "BSB",
        "destination": "REC",
        "trip_type": "ROUND_TRIP",
        "trip_duration": 7,
        "cabin_class": "ECONOMY",
        "currency": "BRL",
        "price_ceiling_total": 1200,
        "price_ceiling_outbound": 650,
        "price_ceiling_return": 650,
        "is_active": True,
        "label": "Brasilia -> Recife",
        "split_legs": True
    }
]

def _num(v):
    if v in (None, ""):
        return None
    return float(v)

def write_default_routes() -> None:
    settings.routes_path.write_text(json.dumps(DEFAULT_ROUTES, indent=2, ensure_ascii=False), encoding="utf-8")

def load_raw_routes() -> list[dict]:
    if not settings.routes_path.exists():
        write_default_routes()
    return json.loads(settings.routes_path.read_text(encoding="utf-8-sig"))

def save_raw_routes(data: list[dict]) -> None:
    settings.routes_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def load_routes() -> list[Route]:
    raw = load_raw_routes()
    routes: list[Route] = []
    changed = False

    for item in raw:
        if "id" not in item or not item["id"]:
            item["id"] = str(uuid.uuid4())
            changed = True

        trip_type = str(item.get("trip_type", "ROUND_TRIP")).upper()
        if trip_type not in {"ROUND_TRIP", "ONE_WAY"}:
            raise ValueError(f"trip_type invalido para V2.1: {trip_type}")

        routes.append(Route(
            id=str(item["id"]),
            origin=str(item["origin"]).upper().strip(),
            destination=str(item["destination"]).upper().strip(),
            trip_type=trip_type,
            trip_duration=int(item.get("trip_duration", 7)),
            cabin_class=str(item.get("cabin_class", "ECONOMY")).upper(),
            currency=str(item.get("currency", "BRL")).upper(),
            price_ceiling_total=_num(item.get("price_ceiling_total", item.get("price_ceiling"))),
            price_ceiling_outbound=_num(item.get("price_ceiling_outbound")),
            price_ceiling_return=_num(item.get("price_ceiling_return")),
            is_active=bool(item.get("is_active", True)),
            label=item.get("label"),
            split_legs=bool(item.get("split_legs", True)),
        ))

    if changed:
        save_routes(routes)

    return routes

def route_to_dict(r: Route) -> dict:
    return {
        "id": r.id,
        "origin": r.origin,
        "destination": r.destination,
        "trip_type": r.trip_type,
        "trip_duration": r.trip_duration,
        "cabin_class": r.cabin_class,
        "currency": r.currency,
        "price_ceiling_total": r.price_ceiling_total,
        "price_ceiling_outbound": r.price_ceiling_outbound,
        "price_ceiling_return": r.price_ceiling_return,
        "is_active": r.is_active,
        "label": r.label,
        "split_legs": r.split_legs,
    }

def save_routes(routes: list[Route]) -> None:
    save_raw_routes([route_to_dict(r) for r in routes])

def add_route(route: Route) -> None:
    routes = load_routes()
    routes.append(route)
    save_routes(routes)

def update_route(route_id: str, updated: Route) -> None:
    routes = load_routes()
    out = []
    found = False
    for r in routes:
        if r.id == route_id:
            updated.id = route_id
            out.append(updated)
            found = True
        else:
            out.append(r)
    if not found:
        raise ValueError("Rota nao encontrada")
    save_routes(out)

def delete_route(route_id: str) -> None:
    routes = [r for r in load_routes() if r.id != route_id]
    save_routes(routes)

def toggle_route(route_id: str) -> None:
    routes = load_routes()
    for r in routes:
        if r.id == route_id:
            r.is_active = not r.is_active
            break
    save_routes(routes)

