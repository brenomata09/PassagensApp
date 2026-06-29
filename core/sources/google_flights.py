from __future__ import annotations

from core.config import settings
from core.engine_fli import search_dates
from core.models import Route


class GoogleFlightsSource:
    name = "google_flights"

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        outbound = search_dates(
            route,
            kind="OUTBOUND",
            origin=route.origin,
            destination=route.destination,
            start_offset_days=1,
            end_offset_days=settings.sweep_days_ahead,
        )
        returns = search_dates(
            route,
            kind="RETURN",
            origin=route.destination,
            destination=route.origin,
            start_offset_days=2,
            end_offset_days=settings.sweep_days_ahead,
        )
        return self._tag(outbound), self._tag(returns)

    def _tag(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            row["source"] = self.name
        return rows
