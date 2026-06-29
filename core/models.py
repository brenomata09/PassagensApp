from __future__ import annotations

from dataclasses import dataclass

@dataclass
class Route:
    id: str
    origin: str
    destination: str
    trip_type: str = "ROUND_TRIP"
    trip_duration: int = 7
    cabin_class: str = "ECONOMY"
    currency: str = "BRL"
    price_ceiling_total: float | None = None
    price_ceiling_outbound: float | None = None
    price_ceiling_return: float | None = None
    is_active: bool = True
    label: str | None = None
    split_legs: bool = True

def money(value, currency: str = "BRL") -> str:
    if value is None:
        return "-"
    try:
        n = float(value)
    except Exception:
        return "-"
    if currency.upper() == "BRL":
        return "R$ " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{currency} {n:,.2f}"

def route_label(route: Route) -> str:
    return route.label or f"{route.origin} -> {route.destination}"
