from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from core.engine_fli import find_fli

from core.sources.fli_source import FliSource


@dataclass(frozen=True)
class SourceSpec:
    name: str
    status: str
    factory: Callable[[], object] | None = None
    health_check: Callable[[], tuple[bool, str | None]] | None = None
    url: str | None = None
    category: str | None = None


def _playwright_health() -> tuple[bool, str | None]:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception as exc:
        return False, f"Playwright indisponivel: {exc}"
    return True, None


def _fli_health() -> tuple[bool, str | None]:
    try:
        find_fli()
    except Exception as exc:
        return False, f"fli indisponivel: {exc}"
    return True, None


EXECUTABLE_PRICE_SOURCES: list[SourceSpec] = [
    SourceSpec(
        name="Google Flights",
        url="https://www.google.com/travel/flights",
        category="metasearch",
        status="executable",
        factory=FliSource,
        health_check=_fli_health,
    ),
]

PENDING_PRICE_SOURCES = [
    {"name": "KAYAK", "url": "https://www.kayak.com.br/flights", "category": "metasearch", "status": "pending"},
    {"name": "Booking Flights", "url": "https://www.booking.com/flights", "category": "ota", "status": "pending"},
    {"name": "VoosBaratos", "url": "https://www.voosbaratos.com.br", "category": "metasearch", "status": "pending"},
    {"name": "Kiwi", "url": "https://www.kiwi.com/br", "category": "ota_metasearch", "status": "pending"},
    {"name": "Trabber", "url": "https://www.trabber.com.br", "category": "metasearch", "status": "pending"},
    {"name": "Skyscanner", "url": "https://www.skyscanner.com.br", "category": "metasearch", "status": "pending"},
    {"name": "Momondo", "url": "https://www.momondo.com.br", "category": "metasearch", "status": "pending"},
    {"name": "Mundi", "url": "https://www.mundi.com.br", "category": "metasearch_br", "status": "pending"},
    {"name": "Voopter", "url": "https://www.voopter.com.br", "category": "metasearch_br", "status": "pending"},
    {"name": "Decolar", "url": "https://www.decolar.com/passagens-aereas", "category": "ota", "status": "pending"},
    {"name": "ViajaNet", "url": "https://www.viajanet.com.br", "category": "ota", "status": "pending"},
    {"name": "Expedia", "url": "https://www.expedia.com.br/Flights", "category": "ota", "status": "pending"},
    {"name": "CVC", "url": "https://www.cvc.com.br/passagens-aereas", "category": "ota", "status": "pending"},
    {"name": "123Milhas", "url": "https://123milhas.com", "category": "miles_ota", "status": "pending"},
    {"name": "Skiplagged", "url": "https://skiplagged.com", "category": "metasearch", "status": "pending"},
    {"name": "Cheapflights", "url": "https://www.cheapflights.com", "category": "metasearch", "status": "pending"},
    {"name": "Wego", "url": "https://www.wego.com", "category": "metasearch", "status": "pending"},
    {"name": "FareCompare", "url": "https://www.farecompare.com", "category": "metasearch", "status": "pending"},
    {"name": "Trip.com", "url": "https://www.trip.com/flights", "category": "ota", "status": "pending"},
    {"name": "Priceline", "url": "https://www.priceline.com/flights", "category": "ota", "status": "pending"},
]

CATALOG_PRICE_SOURCES = [
    {"name": "Submarino Viagens", "url": "https://www.submarinoviagens.com.br", "category": "ota_br", "status": "catalog"},
    {"name": "Hurb", "url": "https://www.hurb.com", "category": "ota_packages_br", "status": "catalog"},
    {"name": "Omio", "url": "https://www.omio.com", "category": "multimodal", "status": "catalog"},
    {"name": "Zupper", "url": "https://www.zupper.com.br", "category": "ota_br", "status": "catalog"},
    {"name": "eDestinos", "url": "https://www.edestinos.com.br", "category": "ota_br", "status": "catalog"},
    {"name": "Passagens Promo", "url": "https://www.passagenspromo.com.br", "category": "ota_br", "status": "catalog"},
    {"name": "MaxMilhas", "url": "https://www.maxmilhas.com.br", "category": "miles_ota", "status": "catalog"},
    {"name": "Agoda Flights", "url": "https://www.agoda.com/flights", "category": "ota", "status": "catalog"},
    {"name": "Hopper", "url": "https://www.hopper.com/flights", "category": "ota_app", "status": "catalog"},
    {"name": "Orbitz", "url": "https://www.orbitz.com/Flights", "category": "ota", "status": "catalog"},
    {"name": "Travelocity", "url": "https://www.travelocity.com/Flights", "category": "ota", "status": "catalog"},
    {"name": "CheapOair", "url": "https://www.cheapoair.com/flights", "category": "ota", "status": "catalog"},
    {"name": "CheapTickets", "url": "https://www.cheaptickets.com/Flights", "category": "ota", "status": "catalog"},
    {"name": "Hotwire", "url": "https://www.hotwire.com/flights", "category": "ota", "status": "catalog"},
    {"name": "eDreams", "url": "https://www.edreams.com/flights", "category": "ota", "status": "catalog"},
    {"name": "Opodo", "url": "https://www.opodo.com/flights", "category": "ota", "status": "catalog"},
    {"name": "Lastminute", "url": "https://www.lastminute.com/flights", "category": "ota", "status": "catalog"},
    {"name": "Air France", "url": "https://wwws.airfrance.com.br", "category": "airline", "status": "catalog"},
    {"name": "KLM", "url": "https://www.klm.com.br", "category": "airline", "status": "catalog"},
    {"name": "TAP", "url": "https://www.flytap.com", "category": "airline", "status": "catalog"},
    {"name": "Copa Airlines", "url": "https://www.copaair.com", "category": "airline", "status": "catalog"},
    {"name": "Avianca", "url": "https://www.avianca.com", "category": "airline", "status": "catalog"},
    {"name": "American Airlines", "url": "https://www.aa.com", "category": "airline", "status": "catalog"},
    {"name": "Delta", "url": "https://www.delta.com", "category": "airline", "status": "catalog"},
    {"name": "United", "url": "https://www.united.com", "category": "airline", "status": "catalog"},
]

PROMOTION_SOURCES = [
    {"name": "Melhores Destinos", "url": "https://www.melhoresdestinos.com.br", "notify_always": True},
    {"name": "CVC", "url": "https://www.cvc.com.br", "notify_always": True},
    {"name": "123Milhas", "url": "https://123milhas.com", "notify_always": True},
    {"name": "Eurodicas", "url": "https://www.eurodicas.com.br", "notify_always": True},
    {"name": "Buenas Dicas", "url": "https://www.buenasdicas.com", "notify_always": True},
    {"name": "Viagem Caribe", "url": "https://viagemcaribe.com", "notify_always": True},
    {"name": "Passagens Imperdiveis", "url": "https://www.passagensimperdiveis.com.br", "notify_always": True},
    {"name": "PromoPassagens", "url": "https://www.promopassagens.com.br", "notify_always": True},
    {"name": "Viajar Barato", "url": "https://www.viajarbarato.com.br", "notify_always": True},
    {"name": "Passageiro de Primeira", "url": "https://passageirodeprimeira.com", "notify_always": True},
    {"name": "Secret Flying", "url": "https://www.secretflying.com", "notify_always": True},
    {"name": "Going", "url": "https://www.going.com", "notify_always": True},
    {"name": "Dollar Flight Club", "url": "https://dollarflightclub.com", "notify_always": True},
    {"name": "Jack's Flight Club", "url": "https://jacksflightclub.com", "notify_always": True},
    {"name": "Airfarewatchdog", "url": "https://www.airfarewatchdog.com", "notify_always": True},
    {"name": "The Flight Deal", "url": "https://www.theflightdeal.com", "notify_always": True},
    {"name": "HolidayPirates", "url": "https://www.holidaypirates.com", "notify_always": True},
    {"name": "Fly4free", "url": "https://www.fly4free.com", "notify_always": True},
    {"name": "Travelzoo", "url": "https://www.travelzoo.com", "notify_always": True},
]

INFO_SOURCES = [
    {"name": "SeatGuru", "url": "https://www.seatguru.com", "category": "flight_info"},
    {"name": "FlightConnections", "url": "https://www.flightconnections.com", "category": "route_info"},
    {"name": "FlightRadar24", "url": "https://www.flightradar24.com", "category": "flight_status"},
    {"name": "FlightAware", "url": "https://www.flightaware.com", "category": "flight_status"},
    {"name": "Eurodicas", "url": "https://www.eurodicas.com.br", "category": "reviews_lists"},
    {"name": "ViagemCaribe", "url": "https://viagemcaribe.com", "category": "reviews_lists"},
    {"name": "Buenas Dicas", "url": "https://www.buenasdicas.com", "category": "reviews_lists"},
    {"name": "Flypass", "url": "https://flypass.com.br", "category": "technical_content"},
    {"name": "Tailan Viajante", "url": "https://www.instagram.com/tailanviajante", "category": "creator_content"},
    {"name": "YouTube passagens", "url": "https://www.youtube.com/results?search_query=passagens+aereas+baratas", "category": "creator_content"},
    {"name": "Skyscanner app", "url": "https://www.skyscanner.com.br/app", "category": "mobile_app"},
    {"name": "MaxMilhas app", "url": "https://www.maxmilhas.com.br/app", "category": "mobile_app"},
]

INFRA_SOURCES = [
    {"name": "Bright Data", "url": "https://brightdata.com", "category": "managed_scraping"},
    {"name": "Apify", "url": "https://apify.com", "category": "managed_scraping"},
    {"name": "Zyte", "url": "https://www.zyte.com", "category": "managed_scraping"},
    {"name": "ScraperAPI", "url": "https://www.scraperapi.com", "category": "managed_scraping"},
    {"name": "Oxylabs", "url": "https://oxylabs.io", "category": "proxy_scraping"},
    {"name": "DataImpulse", "url": "https://dataimpulse.com", "category": "proxy"},
    {"name": "Browserbase", "url": "https://www.browserbase.com", "category": "browser_infra"},
    {"name": "Stagehand", "url": "https://github.com/browserbase/stagehand", "category": "browser_agent"},
    {"name": "browser-use", "url": "https://github.com/browser-use/browser-use", "category": "browser_agent"},
    {"name": "Playwright", "url": "https://playwright.dev", "category": "browser_framework"},
    {"name": "Selenium", "url": "https://www.selenium.dev", "category": "browser_framework"},
    {"name": "Puppeteer", "url": "https://pptr.dev", "category": "browser_framework"},
    {"name": "Amadeus for Developers", "url": "https://developers.amadeus.com", "category": "travel_api"},
    {"name": "Duffel", "url": "https://duffel.com", "category": "travel_api"},
    {"name": "Sabre APIs", "url": "https://developer.sabre.com", "category": "travel_api"},
    {"name": "Travelport", "url": "https://developer.travelport.com", "category": "travel_api"},
    {"name": "Kiwi Tequila API", "url": "https://tequila.kiwi.com", "category": "travel_api"},
    {"name": "SerpApi Google Flights", "url": "https://serpapi.com/google-flights-api", "category": "search_api"},
]

PRICE_SOURCES = EXECUTABLE_PRICE_SOURCES + PENDING_PRICE_SOURCES + CATALOG_PRICE_SOURCES


def executable_source_specs() -> list[SourceSpec]:
    return list(EXECUTABLE_PRICE_SOURCES)


def promotion_sources() -> list[dict]:
    return list(PROMOTION_SOURCES)


def always_notify_promotions() -> list[dict]:
    return [item for item in PROMOTION_SOURCES if item.get("notify_always")]
