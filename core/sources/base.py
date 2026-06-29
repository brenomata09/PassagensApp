from __future__ import annotations

from typing import Protocol

from core.models import Route


class FlightSource(Protocol):
    name: str

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        """Return outbound and return calendar prices normalized as leg rows."""
        ...
