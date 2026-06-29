"""
Adaptador Kiwi via MCP oficial (https://mcp.kiwi.com)
=====================================================
- Sem chave de API, sem navegador, sem CAPTCHA, gratuito.
- Substitui a antiga API Tequila (fechada para novos registros desde 2024).
- Retorna ofertas num formato canonico para encaixar no agregador.

Requer: pip install mcp
"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta
from typing import Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

KIWI_MCP_URL = "https://mcp.kiwi.com"


def _to_ddmmyyyy(date_str: str) -> str:
    """Aceita 'YYYY-MM-DD' (ISO) ou 'dd/mm/yyyy' e devolve sempre 'dd/mm/yyyy'."""
    if "/" in date_str:
        return date_str
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%d/%m/%Y")


def _normalise_offer(raw: dict) -> dict:
    """Converte uma oferta crua do Kiwi para o formato canonico do app."""
    return_leg = raw.get("return") or {}
    return {
        "source": "kiwi",
        "origin": raw.get("flyFrom"),
        "destination": raw.get("flyTo"),
        "city_from": raw.get("cityFrom"),
        "city_to": raw.get("cityTo"),
        "departure": (raw.get("departure") or {}).get("local"),
        "arrival": (raw.get("arrival") or {}).get("local"),
        "return_departure": (return_leg.get("departure") or {}).get("local"),
        "return_arrival": (return_leg.get("arrival") or {}).get("local"),
        "duration_seconds": raw.get("totalDurationInSeconds"),
        "price": raw.get("price"),
        "currency": raw.get("currency"),
        "stops": len(raw.get("layovers") or []),
        "layovers": [lo.get("cityCode") for lo in (raw.get("layovers") or [])],
        "booking_url": raw.get("deepLink"),
    }


async def search_flights_kiwi(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    departure_flex: int = 0,
    return_flex: int = 0,
    currency: str = "BRL",
) -> list[dict]:
    """
    Busca voos no Kiwi via MCP oficial e devolve lista de ofertas canonicas.
    Datas aceitam 'YYYY-MM-DD' ou 'dd/mm/yyyy'.
    Em qualquer falha, devolve [] para nao derrubar o agregador.
    """
    args = {
        "flyFrom": origin,
        "flyTo": destination,
        "departureDate": _to_ddmmyyyy(departure_date),
        "curr": currency,
        "passengers": {"adults": adults, "children": children, "infants": infants},
    }
    if return_date:
        args["returnDate"] = _to_ddmmyyyy(return_date)
    if departure_flex:
        args["departureDateFlexRange"] = departure_flex
    if return_flex:
        args["returnDateFlexRange"] = return_flex

    try:
        async with streamablehttp_client(KIWI_MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("search-flight", args)

                raw_text = ""
                for c in res.content:
                    raw_text += getattr(c, "text", "")
                if not raw_text.strip():
                    return []
                data = json.loads(raw_text)
                offers = data if isinstance(data, list) else data.get("data", [])
                return [_normalise_offer(o) for o in offers]
    except Exception as e:  # noqa: BLE001
        print(f"[kiwi] erro: {e}")
        return []


def search_flights_kiwi_sync(*args, **kwargs) -> list[dict]:
    return asyncio.run(search_flights_kiwi(*args, **kwargs))


class KiwiMcpSource:
    name = "kiwi"
    step_days = 7
    flex_days = 3
    call_delay_seconds = 0.7

    def search_total(self, route) -> list[dict]:
        from core.config import settings

        start = date.today() + timedelta(days=1)
        end = date.today() + timedelta(days=settings.sweep_days_ahead)
        duration = int(getattr(route, "trip_duration", 7) or 7)
        currency = getattr(route, "currency", "BRL") or "BRL"

        rows = []
        call_count = 0
        departure = start

        while departure <= end:
            expected_return = departure + timedelta(days=duration)
            offers = search_flights_kiwi_sync(
                route.origin,
                route.destination,
                departure.isoformat(),
                expected_return.isoformat(),
                adults=1,
                departure_flex=self.flex_days,
                return_flex=self.flex_days,
                currency=currency,
            )
            call_count += 1

            for offer in offers:
                if offer.get("price") is None or not offer.get("return_departure"):
                    continue

                departure_date = str(offer.get("departure") or "")[:10]
                return_date = str(offer.get("return_departure") or "")[:10]
                try:
                    dep = date.fromisoformat(departure_date)
                    ret = date.fromisoformat(return_date)
                except Exception:
                    continue

                trip_duration = (ret - dep).days
                if dep < start or dep > end or trip_duration != duration:
                    continue

                rows.append({
                    "origin": route.origin,
                    "destination": route.destination,
                    "snapshot_kind": "TOTAL",
                    "departure_date": dep.isoformat(),
                    "return_date": ret.isoformat(),
                    "trip_duration": trip_duration,
                    "price": float(offer["price"]),
                    "currency": offer.get("currency") or currency,
                    "raw": {
                        **offer,
                        "window_start": start.isoformat(),
                        "window_end": end.isoformat(),
                        "sample_departure": departure.isoformat(),
                        "sample_return": expected_return.isoformat(),
                        "kiwi_call_count": call_count,
                    },
                    "source": self.name,
                })

            departure += timedelta(days=self.step_days)
            if departure <= end:
                time.sleep(self.call_delay_seconds)

        return sorted(rows, key=lambda item: (float(item["price"]), item["departure_date"], item["return_date"]))


if __name__ == "__main__":
    results = search_flights_kiwi_sync("GRU", "MIA", "2026-08-15", adults=1)
    print(f"Ofertas encontradas: {len(results)}")
    for o in results[:3]:
        print(
            f"  {o['origin']}->{o['destination']} | {o['price']} {o['currency']} "
            f"| escalas: {o['stops']} ({','.join(o['layovers'])}) | {o['booking_url']}"
        )
