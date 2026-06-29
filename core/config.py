from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "passagens.db"
ROUTES_PATH = ROOT / "routes.json"

load_dotenv(ENV_PATH)
DATA_DIR.mkdir(exist_ok=True)

@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    db_path: Path = DB_PATH
    routes_path: Path = ROUTES_PATH

    telegram_bot_token: str | None = (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_TOKEN")
        or os.getenv("BOT_TOKEN")
    )
    telegram_chat_id: str | None = (
        os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("CHAT_ID")
    )

    sweep_days_ahead: int = int(os.getenv("SWEEP_DAYS_AHEAD", "245"))
    sweep_interval_hours: int = int(os.getenv("SWEEP_INTERVAL_HOURS", "4"))
    browser_proxy_server: str | None = os.getenv("BROWSER_PROXY_SERVER")
    browser_proxy_username: str | None = os.getenv("BROWSER_PROXY_USERNAME")
    browser_proxy_password: str | None = os.getenv("BROWSER_PROXY_PASSWORD")
    kayak_profile_dir: Path = Path(os.getenv("KAYAK_PROFILE_DIR", str(DATA_DIR / "browser_profiles" / "kayak")))
    kiwi_profile_dir: Path = Path(os.getenv("KIWI_PROFILE_DIR", str(DATA_DIR / "browser_profiles" / "kiwi")))
    route_delay_seconds: float = float(os.getenv("ROUTE_DELAY_SECONDS", "1.5"))
    alert_silence_hours: int = int(os.getenv("ALERT_SILENCE_HOURS", "6"))
    allow_experimental_sources: bool = os.getenv("ALLOW_EXPERIMENTAL_SOURCES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "sim",
    }

settings = Settings()
