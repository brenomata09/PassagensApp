from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.config import settings
from core.models import Route


_MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}


def _money_to_float(text: str) -> float | None:
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(?:R\$|\$|BRL)\s*([0-9\.\,]+)", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(value)
    except Exception:
        return None


def _parse_month(text: str) -> int | None:
    normalized = re.sub(r"[^a-z]", "", text.lower())[:3]
    return _MONTHS.get(normalized)


def _build_date(day_text: str, month_text: str, year: int) -> date | None:
    try:
        day = int(day_text)
    except Exception:
        return None
    month = _parse_month(month_text)
    if month is None:
        return None
    try:
        return date(year, month, day)
    except Exception:
        return None


def _parse_range_line(line: str, start: date) -> tuple[date, date] | None:
    match = re.search(
        r"(\d{1,2})\s+de\s+([a-zç\.]+)\s*-\s*(\d{1,2})\s+de\s+([a-zç\.]+)",
        line.lower(),
    )
    if not match:
        return None
    departure = _build_date(match.group(1), match.group(2), start.year)
    if departure is None:
        return None
    return_year = departure.year
    ret_month = _parse_month(match.group(4))
    dep_month = departure.month
    if ret_month is not None and ret_month < dep_month:
        return_year += 1
    return_date = _build_date(match.group(3), match.group(4), return_year)
    if return_date is None:
        return None
    if return_date < departure:
        try:
            return_date = date(return_date.year + 1, return_date.month, return_date.day)
        except Exception:
            return None
    return departure, return_date


class BrowserKiwiSource:
    name = "kiwi_browser"

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

    def _proxy(self) -> dict[str, str] | None:
        server = settings.browser_proxy_server
        if not server:
            return None
        proxy: dict[str, str] = {"server": server}
        if settings.browser_proxy_username:
            proxy["username"] = settings.browser_proxy_username
        if settings.browser_proxy_password:
            proxy["password"] = settings.browser_proxy_password
        return proxy

    def _cleanup_profile_locks(self, profile_dir: Path) -> None:
        for pattern in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_file = profile_dir / pattern
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except Exception:
                pass

    def _dismiss_privacy_modal(self, page) -> None:
        modal = page.locator('div[aria-label="Definições de privacidade"], div[aria-label*="privacidade"]')
        if modal.count() == 0:
            return
        locator = modal.locator("button")
        if locator.count() == 0:
            return
        for index in range(locator.count()):
            try:
                locator.nth(index).click(force=True, timeout=2000)
                page.wait_for_timeout(500)
                return
            except Exception:
                continue

    def _select_airport(self, page, field_selector: str, code: str) -> None:
        page.locator(field_selector).fill(code)
        page.wait_for_timeout(1500)
        try:
            page.get_by_text(f"{code} ", exact=False).first.click(timeout=10000)
            return
        except Exception:
            pass
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        total_rows = self.search_total(route)
        return total_rows, total_rows

    def search_total(self, route: Route) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise RuntimeError("Playwright nao disponivel.") from exc

        start = date.today() + timedelta(days=1)
        duration = int(getattr(route, "trip_duration", 10) or 10)
        end = start + timedelta(days=duration)
        profile_dir = settings.kiwi_profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_profile_locks(profile_dir)

        chrome_path = self._chrome_path()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": True,
                "locale": "pt-BR",
                "timezone_id": "America/Sao_Paulo",
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1440, "height": 1600},
                "args": launch_args,
            }
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path
            proxy = self._proxy()
            if proxy:
                launch_kwargs["proxy"] = proxy

            context = p.chromium.launch_persistent_context(**launch_kwargs)
            page = context.new_page()
            page.set_default_timeout(45000)

            try:
                url = self._url(route, start.isoformat(), end.isoformat())
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1200)
                self._dismiss_privacy_modal(page)

                self._select_airport(page, "#origin", route.origin)
                page.wait_for_timeout(1000)
                self._dismiss_privacy_modal(page)

                self._select_airport(page, "#destination", route.destination)
                self._dismiss_privacy_modal(page)

                try:
                    page.wait_for_function(
                        "() => document.body.innerText.includes('R$') || document.body.innerText.includes('Lamentamos')",
                        timeout=30000,
                    )
                except Exception:
                    page.wait_for_timeout(8000)
                page.wait_for_timeout(2000)
                body = page.locator("body").inner_text(timeout=15000)
                lowered = body.lower()
                if "lamentamos, mas não conseguimos encontrar sua viagem" in lowered:
                    raise RuntimeError("Kiwi nao encontrou precos para a rota.")

                rows = self._extract_total_prices(body, route, start, end)
                if not rows:
                    raise RuntimeError("Kiwi nao retornou precos.")
                return rows
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Kiwi timeout: {exc}") from exc
            finally:
                context.close()

    def _url(self, route: Route, start: str, end: str) -> str:
        return (
            "https://www.kiwi.com/br/search/results/"
            f"{route.origin.lower()}/{route.destination.lower()}/{start}/{end}/"
        )

    def _extract_total_prices(self, body: str, route: Route, start: date, end: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, float]] = set()
        lines = [line.strip() for line in body.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            range_pair = _parse_range_line(line, start)
            if not range_pair:
                continue
            price = None
            if index + 1 < len(lines):
                price = _money_to_float(lines[index + 1])
            if price is None:
                continue
            departure_date, return_date = range_pair
            key = (departure_date.isoformat(), return_date.isoformat(), price)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "origin": route.origin,
                "destination": route.destination,
                "snapshot_kind": "TOTAL",
                "departure_date": departure_date.isoformat(),
                "return_date": return_date.isoformat(),
                "trip_duration": (return_date - departure_date).days,
                "price": price,
                "currency": route.currency,
                "raw": {
                    "text": line,
                    "source": self.name,
                    "departure_date": departure_date.isoformat(),
                    "return_date": return_date.isoformat(),
                },
                "source": self.name,
            })

        if rows:
            return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))

        fallback: list[dict[str, Any]] = []
        for line in lines:
            price = _money_to_float(line)
            if price is None:
                continue
            key = (start.isoformat(), end.isoformat(), price)
            if key in seen:
                continue
            seen.add(key)
            fallback.append({
                "origin": route.origin,
                "destination": route.destination,
                "snapshot_kind": "TOTAL",
                "departure_date": start.isoformat(),
                "return_date": end.isoformat(),
                "trip_duration": (end - start).days,
                "price": price,
                "currency": route.currency,
                "raw": {
                    "text": line,
                    "source": self.name,
                    "departure_date": start.isoformat(),
                    "return_date": end.isoformat(),
                },
                "source": self.name,
            })
        return sorted(fallback, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))
