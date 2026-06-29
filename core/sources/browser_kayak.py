from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.config import settings
from core.models import Route


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


class BrowserKayakSource:
    name = "kayak_browser"

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

    def search_legs(self, route: Route) -> tuple[list[dict], list[dict]]:
        total_rows = self.search_total(route)
        return total_rows, total_rows

    def search_total(self, route: Route) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            raise RuntimeError("Playwright nao disponivel.") from exc

        start = date.today() + timedelta(days=1)
        end = date.today() + timedelta(days=settings.sweep_days_ahead)
        profile_dir = settings.kayak_profile_dir
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
                page.wait_for_timeout(6000)
                body = page.locator("body").inner_text(timeout=15000)
                lowered = body.lower()
                if "acha que você é um \"bot\"" in lowered or "acha que voce e um \"bot\"" in lowered:
                    raise RuntimeError("KAYAK bloqueou o navegador com deteccao de bot.")
                rows = self._extract_total_prices(body, route, start, end)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"KAYAK timeout: {exc}") from exc
            finally:
                context.close()

        return rows

    def _url(self, route: Route, start: str, end: str) -> str:
        return (
            "https://www.kayak.com.br/flights/"
            f"{route.origin}-{route.destination}/{start}/{end}"
            "?sort=bestflight_a"
        )

    def _extract_prices(self, body: str, route: Route) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen = set()
        today = date.today()
        for line in body.splitlines():
            value = _money_to_float(line)
            if value is None or value in seen:
                continue
            seen.add(value)
            rows.append({
                "origin": route.origin,
                "destination": route.destination,
                "departure_date": str(today + timedelta(days=7)),
                "return_date": None,
                "trip_duration": None,
                "price": value,
                "currency": route.currency,
                "raw": {"text": line, "source": self.name},
                "source": self.name,
            })
        return rows

    def _extract_total_prices(self, body: str, route: Route, start: date, end: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen = set()
        duration = (end - start).days
        for line in body.splitlines():
            value = _money_to_float(line)
            if value is None or value in seen:
                continue
            seen.add(value)
            rows.append({
                "origin": route.origin,
                "destination": route.destination,
                "snapshot_kind": "TOTAL",
                "departure_date": start.isoformat(),
                "return_date": end.isoformat(),
                "trip_duration": duration,
                "price": value,
                "currency": route.currency,
                "raw": {"text": line, "source": self.name, "departure_date": start.isoformat(), "return_date": end.isoformat()},
                "source": self.name,
            })
        return rows
