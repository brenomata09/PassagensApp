import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

from app import FareCandidate, FlightExplorer, is_iata_code


ENV_PATH = Path(__file__).with_name(".env")
STATE_PATH = Path(__file__).with_name("monitor_alerts.json")


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token.strip()
        self.chat_id = chat_id.strip()

    def send(self, message: str) -> None:
        if not self.token or not self.chat_id:
            raise ValueError("Informe TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")

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

    def should_alert(self, item: FareCandidate) -> bool:
        key = f"{item.depart_date}|{item.return_date}|{item.airlines}|{item.stops}"
        previous = self.data.get(key)
        if previous is None or item.price < int(previous["price"]):
            self.data[key] = asdict(item)
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


class MonitorApp:
    def __init__(self) -> None:
        load_env_file()
        self.root = tk.Tk()
        self.root.title("Monitor de Passagens")
        self.root.geometry("1060x680")
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.results: list[FareCandidate] = []
        self.store = MonitorStore()
        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(frame)
        form.pack(fill=tk.X)

        self.origin = tk.StringVar(value=os.getenv("FLIGHT_ORIGIN", "BSB"))
        self.destination = tk.StringVar(value=os.getenv("FLIGHT_DESTINATION", "IGU"))
        self.start_month = tk.StringVar(value=os.getenv("FLIGHT_START_MONTH", "2026-08"))
        self.end_month = tk.StringVar(value=os.getenv("FLIGHT_END_MONTH", "2026-12"))
        self.top_per_month = tk.IntVar(value=int(os.getenv("FLIGHT_TOP_PER_MONTH", "3")))
        self.max_one_way_price = tk.IntVar(value=int(os.getenv("FLIGHT_MAX_ONE_WAY", "500")))
        self.max_round_trip_price = tk.IntVar(value=int(os.getenv("FLIGHT_MAX_ROUND_TRIP", "900")))
        self.engine_mode = tk.StringVar(value=os.getenv("FLIGHT_ENGINE", "fast+fli"))
        self.interval_minutes = tk.IntVar(value=int(os.getenv("MONITOR_INTERVAL_MINUTES", "60")))
        self.telegram_token = tk.StringVar(value=os.getenv("TELEGRAM_BOT_TOKEN", ""))
        self.telegram_chat_id = tk.StringVar(value=os.getenv("TELEGRAM_CHAT_ID", ""))

        fields = [
            ("Origem", self.origin, 8),
            ("Destino", self.destination, 8),
            ("Mes inicial", self.start_month, 10),
            ("Mes final", self.end_month, 10),
            ("Top/mes", self.top_per_month, 5),
            ("Teto ida", self.max_one_way_price, 7),
            ("Teto ida+volta", self.max_round_trip_price, 7),
            ("Intervalo min", self.interval_minutes, 8),
        ]

        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky="w", padx=(0, 8))
            ttk.Entry(form, textvariable=variable, width=width).grid(
                row=1,
                column=column,
                sticky="w",
                padx=(0, 12),
            )

        engine_column = len(fields)
        ttk.Label(form, text="Motor").grid(row=0, column=engine_column, sticky="w", padx=(0, 8))
        ttk.Combobox(
            form,
            textvariable=self.engine_mode,
            values=("fast+fli", "fast-flights", "fli"),
            width=11,
            state="readonly",
        ).grid(row=1, column=engine_column, sticky="w")

        telegram = ttk.Frame(frame)
        telegram.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(telegram, text="Bot token").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(telegram, textvariable=self.telegram_token, width=58, show="*").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 16),
        )
        ttk.Label(telegram, text="Chat ID").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(telegram, textvariable=self.telegram_chat_id, width=22).grid(
            row=0,
            column=3,
            sticky="w",
        )

        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(12, 0))
        self.start_button = ttk.Button(controls, text="Iniciar monitor", command=self._start)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(
            controls,
            text="Parar",
            command=self._stop,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Teste Telegram", command=self._test_telegram).pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(14, 4))
        self.status = ttk.Label(frame, text="Pronto")
        self.status.pack(anchor="w")

        columns = ("month", "depart", "return", "price", "airlines", "stops")
        labels = {
            "month": "Mes",
            "depart": "Ida",
            "return": "Volta",
            "price": "Preco",
            "airlines": "Companhia",
            "stops": "Escalas",
        }
        widths = {
            "month": 90,
            "depart": 120,
            "return": 120,
            "price": 100,
            "airlines": 260,
            "stops": 220,
        }

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        for column in columns:
            self.table.heading(column, text=labels[column])
            self.table.column(column, width=widths[column], anchor="center")
        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _start(self) -> None:
        try:
            self._validate()
        except ValueError as error:
            messagebox.showerror("Entrada invalida", str(error))
            return

        self.stop_event.clear()
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.configure(text="Monitor iniciado")
        self.worker = threading.Thread(target=self._monitor_loop, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.status.configure(text="Parando apos a chamada atual")

    def _monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            self._run_once()
            if self.stop_event.is_set():
                break
            seconds = self.interval_minutes.get() * 60
            for remaining in range(seconds, 0, -1):
                if self.stop_event.is_set():
                    break
                if remaining % 60 == 0:
                    minutes = remaining // 60
                    self.root.after(
                        0,
                        lambda m=minutes: self.status.configure(
                            text=f"Aguardando proxima busca: {m} min"
                        ),
                    )
                time.sleep(1)

        self.root.after(0, self._stopped)

    def _run_once(self) -> None:
        try:
            explorer = FlightExplorer(
                origin=self.origin.get(),
                destination=self.destination.get(),
                top_per_month=self.top_per_month.get(),
                max_one_way_price=self.max_one_way_price.get(),
                max_round_trip_price=self.max_round_trip_price.get(),
                engine_mode=self.engine_mode.get(),
            )
            explorer.cache = {}
            explorer._save_cache = lambda: None
            results = explorer.search(
                self.start_month.get(),
                self.end_month.get(),
                on_status=self._thread_status,
            )
            self.root.after(0, lambda: self._show_results(results))
            self._send_alerts(results)
            if explorer.stopped_reason:
                self.root.after(
                    0,
                    lambda: self.status.configure(
                        text=f"Busca parcial: {explorer.stopped_reason}"
                    ),
                )
        except Exception as error:
            self.root.after(0, lambda: self.status.configure(text=f"Erro: {error}"))

    def _send_alerts(self, results: list[FareCandidate]) -> None:
        notifier = TelegramNotifier(self.telegram_token.get(), self.telegram_chat_id.get())
        alerts = [item for item in results if self.store.should_alert(item)]
        if not alerts:
            return

        for item in alerts:
            notifier.send(self._format_alert(item))

    def _format_alert(self, item: FareCandidate) -> str:
        return (
            "Passagem encontrada\n"
            f"{self.origin.get().upper()} -> {self.destination.get().upper()}\n"
            f"Ida: {self._br_date(item.depart_date)}\n"
            f"Volta: {self._br_date(item.return_date)}\n"
            f"Preco: R$ {item.price:,.0f}\n".replace(",", ".")
            + f"Companhia: {item.airlines}\n"
            + f"Escalas: {item.stops}\n"
            + f"Motor: {self.engine_mode.get()}\n"
            + f"Horario: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )

    def _test_telegram(self) -> None:
        try:
            TelegramNotifier(self.telegram_token.get(), self.telegram_chat_id.get()).send(
                "Teste do monitor de passagens."
            )
            messagebox.showinfo("Telegram", "Mensagem de teste enviada.")
        except Exception as error:
            messagebox.showerror("Telegram", str(error))

    def _thread_status(self, current: int, total: int, text: str) -> None:
        self.root.after(0, lambda: self._set_status(current, total, text))

    def _set_status(self, current: int, total: int, text: str) -> None:
        percent = 0 if total <= 0 else min(100, current / total * 100)
        self.progress["value"] = percent
        self.status.configure(text=f"{percent:.0f}% - {text} ({current}/{total})")

    def _show_results(self, results: list[FareCandidate]) -> None:
        self.results = results
        self.table.delete(*self.table.get_children())
        for item in results:
            self.table.insert(
                "",
                tk.END,
                values=(
                    item.month,
                    self._br_date(item.depart_date),
                    self._br_date(item.return_date),
                    f"R$ {item.price:,.0f}".replace(",", "."),
                    item.airlines,
                    item.stops,
                ),
            )
        self.status.configure(text=f"Ultima busca: {len(results)} opcoes")

    def _stopped(self) -> None:
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status.configure(text="Monitor parado")

    def _validate(self) -> None:
        origin = self.origin.get().strip().upper()
        destination = self.destination.get().strip().upper()
        if not is_iata_code(origin) or not is_iata_code(destination):
            raise ValueError("Origem e destino devem ser codigos IATA de 3 letras.")
        if origin == destination:
            raise ValueError("Origem e destino devem ser diferentes.")
        if self.top_per_month.get() <= 0:
            raise ValueError("Top/mes deve ser maior que zero.")
        if self.max_one_way_price.get() <= 0:
            raise ValueError("Teto ida deve ser maior que zero.")
        if self.max_round_trip_price.get() <= 0:
            raise ValueError("Teto ida+volta deve ser maior que zero.")
        if self.max_one_way_price.get() > self.max_round_trip_price.get():
            raise ValueError("Teto ida nao pode ser maior que teto ida+volta.")
        if self.interval_minutes.get() <= 0:
            raise ValueError("Intervalo deve ser maior que zero.")
        if self.engine_mode.get() not in {"fast+fli", "fast-flights", "fli"}:
            raise ValueError("Motor invalido.")
        if not self.telegram_token.get().strip() or not self.telegram_chat_id.get().strip():
            raise ValueError("Informe token e chat ID do Telegram.")
        datetime.strptime(self.start_month.get(), "%Y-%m")
        datetime.strptime(self.end_month.get(), "%Y-%m")

    @staticmethod
    def _br_date(value: str) -> str:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        return parsed.strftime("%d/%m/%Y")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    MonitorApp().run()
