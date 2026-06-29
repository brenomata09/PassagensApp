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


class BrowserVoosBaratosSource:
    name = "voosbaratos_browser"

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

        start = date.today() + timedelta(days=7)
        end = date.today() + timedelta(days=14)
        profile_dir = settings.root / "data" / "browser_profiles" / "voosbaratos"
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

            context = p.chromium.launch_persistent_context(**launch_kwargs)
            page = context.new_page()
            page.set_default_timeout(45000)

            try:
                page.goto(self._url(route, start, end), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_function(
                    "() => document.body.innerText.includes('R$') || document.body.innerText.includes('Resultados')",
                    timeout=30000,
                )
                page.wait_for_timeout(4000)
                body = page.locator("body").inner_text(timeout=15000)
                rows = self._extract_total_prices(body, route, start, end)
                if not rows:
                    raise RuntimeError("VoosBaratos nao retornou precos.")
                return rows
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"VoosBaratos timeout: {exc}") from exc
            finally:
                context.close()

    def _url(self, route: Route, start: date, end: date) -> str:
        return (
            "https://www.voosbaratos.com.br/Procurar/"
            f"{route.origin.upper()}-{route.destination.upper()}/"
            f"{start.year}-{start.month}-{start.day}/"
            f"{end.year}-{end.month}-{end.day}/BR/"
        )

    def _extract_total_prices(self, body: str, route: Route, start: date, end: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[float] = set()
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
                "trip_duration": (end - start).days,
                "price": value,
                "currency": route.currency,
                "raw": {
                    "text": line,
                    "source": self.name,
                    "departure_date": start.isoformat(),
                    "return_date": end.isoformat(),
                },
                "source": self.name,
            })
        return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))[:25]
