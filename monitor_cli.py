import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app import FareCandidate, FlightExplorer, is_iata_code


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / "monitor_cli_alerts.json"


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} deve ser um numero inteiro.") from error


@dataclass
class MonitorConfig:
    origin: str
    destination: str
    start_month: str
    end_month: str
    top_per_month: int
    max_one_way_price: int
    max_round_trip_price: int
    engine_mode: str
    interval_minutes: int
    telegram_token: str
    telegram_chat_id: str

    @classmethod
    def from_env(cls) -> "MonitorConfig":
        load_env_file()
        config = cls(
            origin=os.getenv("FLIGHT_ORIGIN", "BSB").strip().upper(),
            destination=os.getenv("FLIGHT_DESTINATION", "IGU").strip().upper(),
            start_month=os.getenv("FLIGHT_START_MONTH", "2026-08").strip(),
            end_month=os.getenv("FLIGHT_END_MONTH", "2026-12").strip(),
            top_per_month=getenv_int("FLIGHT_TOP_PER_MONTH", 3),
            max_one_way_price=getenv_int("FLIGHT_MAX_ONE_WAY", 500),
            max_round_trip_price=getenv_int("FLIGHT_MAX_ROUND_TRIP", 900),
            engine_mode=os.getenv("FLIGHT_ENGINE", "fast+fli").strip(),
            interval_minutes=getenv_int("MONITOR_INTERVAL_MINUTES", 240),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not is_iata_code(self.origin) or not is_iata_code(self.destination):
            raise ValueError("FLIGHT_ORIGIN e FLIGHT_DESTINATION devem ter 3 letras.")
        if self.origin == self.destination:
            raise ValueError("Origem e destino devem ser diferentes.")
        if self.top_per_month <= 0:
            raise ValueError("FLIGHT_TOP_PER_MONTH deve ser maior que zero.")
        if self.max_one_way_price <= 0:
            raise ValueError("FLIGHT_MAX_ONE_WAY deve ser maior que zero.")
        if self.max_round_trip_price <= 0:
            raise ValueError("FLIGHT_MAX_ROUND_TRIP deve ser maior que zero.")
        if self.max_one_way_price > self.max_round_trip_price:
            raise ValueError("FLIGHT_MAX_ONE_WAY nao pode ser maior que FLIGHT_MAX_ROUND_TRIP.")
        if self.engine_mode not in {"fast+fli", "fast-flights", "fli"}:
            raise ValueError("FLIGHT_ENGINE deve ser fast+fli, fast-flights ou fli.")
        if self.interval_minutes <= 0:
            raise ValueError("MONITOR_INTERVAL_MINUTES deve ser maior que zero.")
        if not self.telegram_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID sao obrigatorios.")
        datetime.strptime(self.start_month, "%Y-%m")
        datetime.strptime(self.end_month, "%Y-%m")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()


class MonitorStore:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.data = self._load()

    def should_alert_month(self, month: str, item: FareCandidate) -> bool:
        previous = self.data.get(month)
        if previous is None or item.price < int(previous["price"]):
            self.data[month] = asdict(item)
            self._save()
            return True
        return False

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def best_by_month(results: list[FareCandidate]) -> dict[str, FareCandidate]:
    best: dict[str, FareCandidate] = {}
    for item in results:
        current = best.get(item.month)
        if current is None or item.price < current.price:
            best[item.month] = item
    return dict(sorted(best.items()))


def br_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")


def format_summary(
    config: MonitorConfig,
    monthly_best: dict[str, FareCandidate],
    only_new_alerts: dict[str, FareCandidate],
) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = [
        "Menores preços por mês",
        f"Rota: {config.origin} -> {config.destination}",
        f"Teto ida: R$ {config.max_one_way_price}",
        f"Teto ida+volta: R$ {config.max_round_trip_price}",
        f"Motor: {config.engine_mode}",
        f"Horário: {now}",
        "",
    ]

    if not monthly_best:
        lines.append("Nenhuma passagem dentro dos tetos foi encontrada.")
        return "\n".join(lines)

    for month, item in monthly_best.items():
        marker = "NOVO/MENOR" if month in only_new_alerts else "sem mudança"
        lines.extend(
            [
                f"{month} - {marker}",
                f"{br_date(item.depart_date)} -> {br_date(item.return_date)}",
                f"R$ {item.price:,.0f}".replace(",", ".")
                + f" - {item.airlines} - {item.stops}",
                "",
            ]
        )

    return "\n".join(lines).strip()


def run_search(config: MonitorConfig) -> tuple[list[FareCandidate], str]:
    explorer = FlightExplorer(
        origin=config.origin,
        destination=config.destination,
        top_per_month=config.top_per_month,
        max_one_way_price=config.max_one_way_price,
        max_round_trip_price=config.max_round_trip_price,
        engine_mode=config.engine_mode,
    )
    explorer.cache = {}
    explorer._save_cache = lambda: None

    def status(current: int, total: int, text: str) -> None:
        percent = 0 if total <= 0 else min(100, current / total * 100)
        print(f"{percent:5.1f}% ({current}/{total}) {text}", flush=True)

    results = explorer.search(config.start_month, config.end_month, on_status=status)
    return results, explorer.stopped_reason


def seconds_until_next_run(interval_minutes: int) -> int:
    return interval_minutes * 60


def sleep_until_next_run(interval_minutes: int) -> None:
    seconds = seconds_until_next_run(interval_minutes)
    while seconds > 0:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        print(f"Próxima busca em {hours}h {minutes}min", flush=True)
        step = min(300, seconds)
        time.sleep(step)
        seconds -= step


def main() -> None:
    config = MonitorConfig.from_env()
    notifier = TelegramNotifier(config.telegram_token, config.telegram_chat_id)
    store = MonitorStore()

    notifier.send(
        "Monitor de passagens iniciado.\n"
        "Telegram configurado corretamente.\n"
        f"Busca a cada {config.interval_minutes} minutos."
    )

    while True:
        print(f"\nBusca iniciada em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", flush=True)
        try:
            results, stopped_reason = run_search(config)
            monthly_best = best_by_month(results)
            new_alerts = {
                month: item
                for month, item in monthly_best.items()
                if store.should_alert_month(month, item)
            }
            message = format_summary(config, monthly_best, new_alerts)
            if stopped_reason:
                message += f"\n\nBusca parcial: {stopped_reason}"
            notifier.send(message)
            print(f"Busca concluída. {len(monthly_best)} meses com resultado.", flush=True)
        except Exception as error:
            error_message = f"Erro no monitor de passagens: {error}"
            print(error_message, flush=True)
            notifier.send(error_message)

        sleep_until_next_run(config.interval_minutes)


if __name__ == "__main__":
    main()
