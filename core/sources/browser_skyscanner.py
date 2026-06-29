from __future__ import annotations

import json
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


def _recursive_price_scan(
    obj: Any,
    out: list[dict[str, Any]],
    route: Route,
    seen: set[tuple[str, str, float]],
    start: date,
    end: date,
):
    if isinstance(obj, dict):
        price = obj.get("price") or obj.get("amount") or obj.get("totalPrice")
        dep = obj.get("departureDate") or obj.get("departure_date") or obj.get("date")
        ret = obj.get("returnDate") or obj.get("return_date")
        if price is not None:
            try:
                price_num = float(str(price).replace(".", "").replace(",", "."))
            except Exception:
                price_num = None
            if price_num is not None:
                dep_value = str(dep or start.isoformat())
                ret_value = str(ret or end.isoformat())
                key = (dep_value, ret_value, price_num)
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "origin": route.origin,
                        "destination": route.destination,
                        "snapshot_kind": "TOTAL",
                        "departure_date": dep_value,
                        "return_date": ret_value,
                        "trip_duration": (end - start).days,
                        "price": price_num,
                        "currency": route.currency,
                        "raw": obj,
                        "source": "skyscanner_browser",
                    })
        for value in obj.values():
            _recursive_price_scan(value, out, route, seen, start, end)
    elif isinstance(obj, list):
        for item in obj:
            _recursive_price_scan(item, out, route, seen, start, end)


class BrowserSkyscannerSource:
    name = "skyscanner_browser"

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
        total = self.search_total(route)
        return total, total

    def search_total(self, route: Route) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
            from playwright_stealth import Stealth
        except Exception as exc:
            raise RuntimeError("Playwright stealth nao disponivel.") from exc

        start = date.today() + timedelta(days=1)
        end = date.today() + timedelta(days=settings.sweep_days_ahead)
        profile_dir = settings.root / "data" / "browser_profiles" / "skyscanner"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_profile_locks(profile_dir)

        chrome_path = self._chrome_path()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        with sync_playwright() as p:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": True,
                "locale": "pt-BR",
                "timezone_id": "America/Sao_Paulo",
                "user_agent": user_agent,
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
            stealth = Stealth(
                navigator_user_agent_override=user_agent,
                navigator_languages_override=("pt-BR", "pt"),
                navigator_platform_override="Win32",
                navigator_vendor_override="Google Inc.",
            )
            stealth.apply_stealth_sync(page)

            captured: list[dict[str, Any]] = []

            def on_response(resp):
                try:
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "json" not in ctype:
                        return
                    url = resp.url.lower()
                    if "skyscanner" not in url and "flight" not in url and "result" not in url:
                        return
                    data = resp.json()
                    _recursive_price_scan(data, captured, route, set(), start, end)
                except Exception:
                    return

            page.on("response", on_response)

            try:
                url = self._url(route, start, end)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(7000)
                body = page.locator("body").inner_text(timeout=15000)
                if "are you a person or a robot" in body.lower():
                    raise RuntimeError("Skyscanner bloqueou o navegador com detecao de bot.")
                text_rows = self._extract_text_prices(body, route, start, end)
                all_rows = captured + text_rows
                if not all_rows:
                    raise RuntimeError("Skyscanner nao retornou precos.")
                return self._dedupe(all_rows)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Skyscanner timeout: {exc}") from exc
            finally:
                context.close()

    def _url(self, route: Route, start: date, end: date) -> str:
        s = start.strftime("%y%m%d")
        e = end.strftime("%y%m%d")
        return (
            "https://www.skyscanner.com.br/transport/flights/"
            f"{route.origin.lower()}/{route.destination.lower()}/{s}/{e}/"
            "?adultsv2=1&cabinclass=economy&preferdirects=false&outboundaltsenabled=false&inboundaltsenabled=false"
        )

    def _extract_text_prices(self, body: str, route: Route, start: date, end: date) -> list[dict[str, Any]]:
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

    def _dedupe(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[tuple[str, str, float], dict[str, Any]] = {}
        for row in rows:
            key = (str(row.get("departure_date")), str(row.get("return_date")), float(row["price"]))
            unique[key] = row
        return sorted(unique.values(), key=lambda item: (float(item["price"]), item.get("departure_date", ""), item.get("return_date", "")))
