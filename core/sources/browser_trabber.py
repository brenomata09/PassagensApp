from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from core.models import Route


_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
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
    match = re.search(r"R\$\s*([0-9\.\,]+)", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(value)
    except Exception:
        return None


def _parse_month(text: str) -> int | None:
    return _MONTHS.get(text.lower().replace("ç", "c").strip())


def _parse_day_month(token: str) -> date | None:
    match = re.search(r"(\d{1,2})\s+([a-zç]+)", token.lower())
    if not match:
        return None
    month = _parse_month(match.group(2))
    if month is None:
        return None
    year = date.today().year if month >= date.today().month else date.today().year + 1
    try:
        return date(year, month, int(match.group(1)))
    except Exception:
        return None


class BrowserTrabberSource:
    name = "trabber_browser"

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

    def search_total(self, route: Route) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise RuntimeError("Playwright nao disponivel.") from exc

        origin_slug = _CITY_SLUGS.get(route.origin.upper())
        destination_slug = _CITY_SLUGS.get(route.destination.upper())
        if not origin_slug or not destination_slug:
            raise RuntimeError(f"Trabber sem slug conhecido para {route.origin}->{route.destination}.")

        url = (
            "https://www.trabber.com.br/passagem-"
            f"{origin_slug}-{destination_slug}-{route.origin.lower()}-{route.destination.lower()}/"
        )

        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {"headless": True}
            chrome_path = self._chrome_path()
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1280, "height": 1400})
            page = context.new_page()
            page.set_default_timeout(45000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                body = page.locator("body").inner_text(timeout=15000)
                rows = self._extract_rows(body, route)
                if not rows:
                    raise RuntimeError(f"Trabber nao retornou precos para {route.origin}->{route.destination}.")
                return rows
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Trabber timeout: {exc}") from exc
            finally:
                context.close()
                browser.close()

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        total = self.search_total(route)
        return total, total

    def _extract_rows(self, body: str, route: Route) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, float]] = set()
        lines = [line.strip() for line in body.splitlines() if line.strip()]

        for i, line in enumerate(lines):
            if "\tR$" in line:
                parts = [part.strip() for part in line.split("\t") if part.strip()]
                price = None
                dep_date = None
                if len(parts) >= 4:
                    dep_date = _parse_day_month(parts[-2])
                    price = _money_to_float(parts[-1])
                if dep_date is None or price is None:
                    continue
                key = (dep_date.isoformat(), price)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "origin": route.origin,
                    "destination": route.destination,
                    "snapshot_kind": "TOTAL",
                    "departure_date": dep_date.isoformat(),
                    "return_date": None,
                    "trip_duration": None,
                    "price": price,
                    "currency": route.currency,
                    "raw": {"text": line, "source": self.name, "route_url": f"{route.origin}->{route.destination}"},
                    "source": self.name,
                })

        if rows:
            return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"]))[:10]

        stats = re.findall(r"Preço (?:mínimo atual|médio)\s+R\$\s*([0-9\.\,]+)", body, re.IGNORECASE)
        if stats:
            value = _money_to_float(f"R$ {stats[0]}")
            if value is not None:
                return [{
                    "origin": route.origin,
                    "destination": route.destination,
                    "snapshot_kind": "TOTAL",
                    "departure_date": date.today().isoformat(),
                    "return_date": None,
                    "trip_duration": None,
                    "price": value,
                    "currency": route.currency,
                    "raw": {"text": "route_stats", "source": self.name, "route_url": f"{route.origin}->{route.destination}"},
                    "source": self.name,
                }]
        return []
