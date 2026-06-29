from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from core.models import Route


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_CITY_SLUGS = {
    "BSB": "brasilia",
    "IGU": "foz-do-iguacu",
    "CAC": "cascavel",
    "REC": "recife",
    "JPA": "joao-pessoa",
    "SSA": "salvador",
}


def _money_to_float(text: str) -> float | None:
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(?:R\$|\$|BRL)\s*([0-9\.\,]+)", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).replace(",", "").replace("$", "")
    try:
        return float(value)
    except Exception:
        return None


def _parse_month(text: str) -> int | None:
    normalized = re.sub(r"[^a-z]", "", text.lower())[:3]
    return _MONTHS.get(normalized)


def _parse_date_token(token: str, year_hint: int) -> date | None:
    match = re.search(r"([A-Za-z]{3}),\s+([A-Za-z]{3})\s+(\d{1,2})", token)
    if not match:
        return None
    month = _parse_month(match.group(2))
    if month is None:
        return None
    year = year_hint if month >= date.today().month else year_hint + 1
    try:
        return date(year, month, int(match.group(3)))
    except Exception:
        return None


class BrowserBookingSource:
    name = "booking_browser"

    def _chrome_path(self) -> str | None:
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Users\breno\AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        return None

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        outbound = self._search_route(route.origin, route.destination, route)
        return_rows = self._search_route(route.destination, route.origin, route)
        return outbound, return_rows

    def _search_route(self, origin: str, destination: str, route: Route) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise RuntimeError("Playwright nao disponivel.") from exc

        origin_slug = _CITY_SLUGS.get(origin.upper())
        destination_slug = _CITY_SLUGS.get(destination.upper())
        if not origin_slug or not destination_slug:
            raise RuntimeError(f"Booking sem slug conhecido para {origin}->{destination}.")

        url = (
            "https://www.booking.com/flights/route/city-to-city/"
            f"br-{origin_slug}-to-br-{destination_slug}.html?aid=304142"
        )

        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                "headless": True,
            }
            chrome_path = self._chrome_path()
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1280, "height": 1400},
            )
            page = context.new_page()
            page.set_default_timeout(45000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                body = page.locator("body").inner_text(timeout=15000)
                if "something went wrong" in body.lower():
                    raise RuntimeError(f"Booking falhou para {origin}->{destination}.")
                rows = self._extract_leg_prices(body, origin, destination, route)
                if not rows:
                    raise RuntimeError(f"Booking nao retornou precos para {origin}->{destination}.")
                return rows
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Booking timeout: {exc}") from exc
            finally:
                context.close()
                browser.close()

    def _extract_leg_prices(self, body: str, origin: str, destination: str, route: Route) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, float]] = set()
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if not re.match(r"^[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}$", line):
                continue
            price = None
            for offset in range(1, 5):
                if i + offset < len(lines):
                    price = _money_to_float(lines[i + offset])
                    if price is not None:
                        break
            if price is None:
                continue
            dep_date = _parse_date_token(line, date.today().year)
            if dep_date is None:
                continue
            key = (dep_date.isoformat(), price)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "origin": origin,
                "destination": destination,
                "snapshot_kind": "OUTBOUND" if origin == route.origin else "RETURN",
                "departure_date": dep_date.isoformat(),
                "return_date": None,
                "trip_duration": None,
                "price": price,
                "currency": route.currency,
                "raw": {
                    "text": line,
                    "source": self.name,
                    "route_url": f"{origin}->{destination}",
                },
                "source": self.name,
            })
        return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"]))[:12]
