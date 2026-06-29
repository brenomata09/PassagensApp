"""
FliSource — adaptador Google Flights via biblioteca `fli` (punitarani/fli).
Implementa o protocolo FlightSource definido em core/sources/base.py.
"""
from __future__ import annotations

from core.engine_fli import search_dates_duration_range
from core.models import Route


class FliSource:
    name = "google_flights"
    min_duration = 4
    max_duration = 20

    def search_total(self, route: Route) -> list[dict]:
        """
        Retorna lista de snapshots TOTAL (ida+volta combinados pelo fli dates --round).
        Cada item já vem normalizado por engine_fli.normalize().
        """
        rows = search_dates_duration_range(
            route=route,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            kind="TOTAL",
            origin=route.origin,
            destination=route.destination,
        )
        # Garante que o campo source está preenchido
        for row in rows:
            row.setdefault("source", self.name)
        return rows
