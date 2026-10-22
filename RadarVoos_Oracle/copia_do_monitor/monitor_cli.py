import json
import os
import time
import fcntl
import logging
from request_guard import GUARD, search_lock, atomic_json, safe_error
from search_state import SearchJob, take_manual_request, fail_pending, prepare_run
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from app import FareCandidate, FlightExplorer


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
        os.environ[key.strip()] = value.strip().strip("\"\'")


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
            start_month=os.getenv("FLIGHT_START_MONTH", date.today().strftime("%Y-%m")).strip(),
            end_month=os.getenv("FLIGHT_END_MONTH", (date.today() + timedelta(days=365)).strftime("%Y-%m")).strip(),
            top_per_month=getenv_int("FLIGHT_TOP_PER_MONTH", 3),
            max_one_way_price=getenv_int("FLIGHT_MAX_ONE_WAY", 500),
            max_round_trip_price=getenv_int("FLIGHT_MAX_ROUND_TRIP", 900),
            engine_mode=os.getenv("FLIGHT_ENGINE", "fli").strip(),
            interval_minutes=getenv_int("MONITOR_INTERVAL_MINUTES", 240),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        )
        config.start_month = max(config.start_month, date.today().strftime('%Y-%m'))
        config.validate()
        return config

    def validate(self) -> None:
        if len(self.origin) != 3 or len(self.destination) != 3:
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
        if self.end_month < self.start_month:
            raise ValueError('Mes final anterior ao inicio; atualizar o periodo de busca.')


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
            return True
        return False

    def record_sent(self, monthly):
        for month, item in monthly.items():
            self.data[month] = asdict(item)
        self._save()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        atomic_json(self.path, self.data)


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
        "Menores precos encontrados por mes - ida e volta",
        f"Rota: {config.origin} -> {config.destination}",
        f"Teto ida: R$ {config.max_one_way_price}",
        f"Teto ida+volta: R$ {config.max_round_trip_price}",
        f"Motor: {config.engine_mode}",
        "Calendario: viagens de 5 e 7 dias; menores combinacoes confirmadas",
        "Teto de ida avulsa aplicado separadamente; nao restringe ida+volta.",
        f"Horário: {now}",
        "",
    ]

    if not monthly_best:
        lines.append("Nenhuma passagem de ida e volta dentro do teto entre as datas verificadas.")
        lines.extend(one_way_summary(config))
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

    lines.extend(one_way_summary(config))
    coverage = getattr(config, 'search_coverage', {})
    if coverage:
        lines.append('Datas de ida+volta verificadas: ' + ', '.join(
            '%s: %d/%d' % (month, item['checked'], item['planned'])
            for month, item in sorted(coverage.items())))
    return "\n".join(lines).strip()


def one_way_summary(config):
    best = {}
    for item in getattr(config, 'one_way_results', []):
        month = item.depart_date[:7]
        if month not in best or item.price < best[month].price:
            best[month] = item
    lines = ['', 'Ida avulsa - consulta independente:']
    if not best:
        lines.append('Nenhuma ida dentro do teto entre as datas verificadas.')
    for month, item in sorted(best.items()):
        lines.append('%s: %s - R$ %d - %s' % (month, br_date(item.depart_date), item.price, item.airlines))
    return lines


def _run_search(config: MonitorConfig, on_status=None) -> tuple[list[FareCandidate], str]:
    explorer = FlightExplorer(
        origin=config.origin,
        destination=config.destination,
        top_per_month=config.top_per_month,
        max_one_way_price=config.max_one_way_price,
        max_round_trip_price=config.max_round_trip_price,
        engine_mode=config.engine_mode,
    )
    config.engine_mode = explorer.selected_engines or config.engine_mode
    explorer.deadline = time.monotonic() + max(30, config.interval_minutes * 60 - 300)
    explorer.cache = {}
    explorer._save_cache = lambda: None

    def status(current: int, total: int, text: str) -> None:
        percent = 0 if total <= 0 else min(100, current / total * 100)
        print(f"{percent:5.1f}% ({current}/{total}) {text}", flush=True)
        if on_status:
            on_status(current,total,text)

    results = explorer.search(config.start_month, config.end_month, on_status=status)
    config.one_way_results = explorer.one_way_results
    config.search_coverage = explorer.coverage
    reason = explorer.stopped_reason
    if explorer.errors and not reason:
        reason = '%d consultas falharam. %s' % (len(explorer.errors), explorer.errors[-1])
    return results, reason


def run_search(config, source='automatic', request_id=None):
    with search_lock():
        job=SearchJob(BASE_DIR,config,source,request_id)
        job.start()
        try:
            if GUARD.paused_until() > time.time():
                raise RuntimeError('Google Flights em pausa apos HTTP 429; aguarde a proxima janela.')
            results,reason=_run_search(config,on_status=job.progress)
            job.finish(results,reason)
            return results,reason
        except Exception as error:
            job.fail(error)
            raise


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


def send_reliably(notifier, message):
    for attempt in range(3):
        try:
            notifier.send(message)
            return True
        except Exception as error:
            logging.error('Falha no Telegram (tentativa %d): %s', attempt + 1, safe_error(error))
            if attempt < 2:
                time.sleep(10 * 2 ** attempt)
    return False


def wait_until(target):
    last_message=0
    while target > time.time():
        request=take_manual_request(BASE_DIR)
        if request:
            return request
        seconds = target - time.time()
        if time.monotonic()-last_message>=300:
            print('Proxima busca em %dh %dmin' % (seconds // 3600, (seconds % 3600) // 60), flush=True)
            last_message=time.monotonic()
        time.sleep(min(2, seconds))
    return take_manual_request(BASE_DIR)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # Um unico agendador, mesmo se alguem tentar abrir outro manualmente.
    with (BASE_DIR / 'monitor_scheduler.lock').open('a') as scheduler_lock:
        try:
            fcntl.flock(scheduler_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.error('Outro monitor ja esta ativo.')
            return
        schedule_path = BASE_DIR / 'monitor_schedule.json'
        try:
            next_due = float(json.loads(schedule_path.read_text())['next_run'])
        except (OSError, ValueError, KeyError, TypeError):
            next_due = time.time()
        while True:
            interval = 240 * 60
            config = None
            try:
                config = MonitorConfig.from_env()
                interval = config.interval_minutes * 60
                target = max(next_due, GUARD.paused_until())
                print('Aguardando horario: ' + datetime.fromtimestamp(target).strftime('%d/%m/%Y %H:%M:%S'), flush=True)
                request=wait_until(target)
                # Recarrega configuracao e data depois da espera, sem reiniciar.
                config = MonitorConfig.from_env()
                interval = config.interval_minutes * 60
                config,source,request_id=prepare_run(BASE_DIR,config,request)
                started = time.time()
                if source=='manual':
                    if next_due<=started:
                        next_due=started+interval
                else:
                    next_due = started + interval
                atomic_json(schedule_path, {'next_run': next_due})
                print('Busca iniciada em ' + datetime.now().strftime('%d/%m/%Y %H:%M:%S'), flush=True)
                notifier = TelegramNotifier(config.telegram_token, config.telegram_chat_id)
                store = MonitorStore(BASE_DIR / ('monitor_alerts_' + config.origin + '_' + config.destination + '.json'))
                results, stopped_reason = run_search(config,
                    source=source,request_id=request_id)
                best = best_by_month(results)
                new = {month: item for month, item in best.items() if store.should_alert_month(month, item)}
                message = format_summary(config, best, new)
                if stopped_reason:
                    if not best:
                        message = message.replace('Nenhuma passagem de ida e volta dentro do teto entre as datas verificadas.',
                            'Busca incompleta: nao foi possivel concluir se existem ofertas dentro dos tetos.')
                    message += '\n\nBusca parcial: ' + stopped_reason
                if send_reliably(notifier, message):
                    store.record_sent(new)
                print('Ciclo finalizado: %d meses com resultado; parcial=%s.' % (len(best), bool(stopped_reason)), flush=True)
            except Exception as error:
                fail_pending(BASE_DIR,error)
                logging.error('Falha no ciclo: %s', safe_error(error))
                if config:
                    send_reliably(TelegramNotifier(config.telegram_token, config.telegram_chat_id),
                        'Monitor de passagens: busca nao concluida. ' + safe_error(error))
                if next_due <= time.time():
                    next_due = time.time() + interval
            # Pula horarios perdidos; nao dispara buscas em sequencia para compensar.
            while next_due <= time.time():
                next_due += interval
            atomic_json(schedule_path, {'next_run': next_due})


if __name__ == '__main__':
    main()
