import csv
import json
import re
import sys
import threading
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk


IATA_CODE_RE = re.compile(r"^[A-Z]{3}$")


def is_iata_code(value: str) -> bool:
    return bool(IATA_CODE_RE.fullmatch(value.strip().upper()))


LOCAL_FAST_FLIGHTS = Path(__file__).resolve().parents[1] / "flights"
if LOCAL_FAST_FLIGHTS.exists():
    sys.path.insert(0, str(LOCAL_FAST_FLIGHTS))

try:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    HAS_FAST_FLIGHTS = True
except ImportError:
    HAS_FAST_FLIGHTS = False

try:
    from fli.models import (
        Airport as FliAirport,
        FlightSearchFilters as FliFlightSearchFilters,
        FlightSegment as FliFlightSegment,
        PassengerInfo as FliPassengerInfo,
        SeatType as FliSeatType,
        TripType as FliTripType,
    )
    from fli.search import SearchFlights as FliSearchFlights

    HAS_FLI = True
except ImportError:
    HAS_FLI = False


@dataclass
class FareCandidate:
    month: str
    depart_date: str
    return_date: str
    price: int
    airlines: str = ""
    stops: str = ""


@dataclass
class OneWayCandidate:
    depart_date: str
    price: int
    airlines: str = ""


class FlightExplorer:
    MIN_TRIP_DAYS = 4
    MAX_TRIP_DAYS = 15
    DEFAULT_MAX_ONE_WAY_PRICE = 500
    DEFAULT_MAX_ROUND_TRIP_PRICE = 900
    TOP_ONE_WAY_DATES = 3

    def __init__(
        self,
        origin: str,
        destination: str,
        top_per_month: int,
        max_one_way_price: int = DEFAULT_MAX_ONE_WAY_PRICE,
        max_round_trip_price: int = DEFAULT_MAX_ROUND_TRIP_PRICE,
        engine_mode: str = "fast+fli",
        currency: str = "BRL",
        language: str = "pt-BR",
    ) -> None:
        self.origin = origin.upper().strip()
        self.destination = destination.upper().strip()
        self.top_per_month = top_per_month
        self.max_one_way_price = max_one_way_price
        self.max_round_trip_price = max_round_trip_price
        self.engine_mode = engine_mode
        self.currency = currency
        self.language = language
        self.stopped_reason = ""
        self.cache_path = Path(f"cache_{self.origin}_{self.destination}_hybrid.json")
        self.cache = self._load_cache()

    def search(self, start_month: str, end_month: str, on_status=None) -> list[FareCandidate]:
        if not self._use_fast_flights() and not self._use_fli():
            raise RuntimeError(
                "Nenhum motor selecionado esta disponivel."
            )

        results: list[FareCandidate] = []
        months = list(self._month_range(start_month, end_month))
        total_queries = sum(self._month_query_count(month) for month in months)
        done_queries = 0

        for index, month in enumerate(months, start=1):
            self._status(on_status, done_queries, total_queries, f"Explorando {month}")
            candidates, used_queries = self._cached_month(month, on_status, done_queries, total_queries)
            done_queries += used_queries
            results.extend(candidates[: self.top_per_month])
            self._save_cache()
            if self.stopped_reason:
                self._status(on_status, done_queries, total_queries, "Busca interrompida")
                break
            self._status(on_status, done_queries, total_queries, f"Concluido {month}")

        if not self.stopped_reason:
            self._status(on_status, total_queries, total_queries, "Busca concluida")
        return sorted(results, key=lambda item: (item.month, item.price, item.depart_date))

    def _cached_month(
        self,
        month: str,
        on_status,
        done_queries: int,
        total_queries: int,
    ) -> tuple[list[FareCandidate], int]:
        cache_key = (
            f"hybrid-fli-v1|{month}|{self.origin}|{self.destination}|"
            f"{self.MIN_TRIP_DAYS}|{self.MAX_TRIP_DAYS}|{self.max_one_way_price}|"
            f"{self.max_round_trip_price}|{self.TOP_ONE_WAY_DATES}|{self.engine_mode}"
        )
        cached = self.cache.get(cache_key)
        if cached:
            visible = [
                FareCandidate(**item)
                for item in cached
                if int(item.get("price", self.max_round_trip_price + 1))
                <= self.max_round_trip_price
            ]
            return visible, self._month_query_count(month)

        candidates = self._explore_candidates(
            month,
            on_status=on_status,
            done_queries=done_queries,
            total_queries=total_queries,
        )
        if self.stopped_reason:
            return candidates, self._used_queries_in_month
        self.cache[cache_key] = [asdict(item) for item in candidates]
        return candidates, self._month_query_count(month)

    def _explore_candidates(
        self,
        month: str,
        on_status,
        done_queries: int,
        total_queries: int,
    ) -> list[FareCandidate]:
        candidates: list[FareCandidate] = []
        one_way_options: list[OneWayCandidate] = []
        self._used_queries_in_month = 0

        month_dates = self._month_dates(month)
        for offset, depart in enumerate(month_dates, start=1):
            self._used_queries_in_month += 1
            self._status(
                on_status,
                done_queries + offset,
                total_queries,
                f"Consultando ida {depart.strftime('%d/%m/%Y')}",
            )
            one_way_results = self._search_one_way(depart)
            if self.stopped_reason:
                return sorted(candidates, key=lambda item: (item.price, item.depart_date))
            one_way_options.extend(one_way_results)

        one_way_options.sort(key=lambda item: (item.price, item.depart_date))
        selected_departures = one_way_options[: self.TOP_ONE_WAY_DATES]
        round_trip_base = done_queries + len(month_dates)
        round_trip_offset = 0

        for one_way in selected_departures:
            depart = datetime.strptime(one_way.depart_date, "%Y-%m-%d").date()
            for trip_days in range(self.MIN_TRIP_DAYS, self.MAX_TRIP_DAYS + 1):
                round_trip_offset += 1
                self._used_queries_in_month += 1
                return_date = depart + timedelta(days=trip_days)
                self._status(
                    on_status,
                    round_trip_base + round_trip_offset,
                    total_queries,
                    f"Validando volta {return_date.strftime('%d/%m/%Y')}",
                )
                round_trip_results = self._search_round_trip(month, depart, return_date)
                if self.stopped_reason:
                    return sorted(candidates, key=lambda item: (item.price, item.depart_date))
                candidates.extend(round_trip_results)

        return sorted(candidates, key=lambda item: (item.price, item.depart_date))

    def _search_one_way(self, depart: date) -> list[OneWayCandidate]:
        errors: list[str] = []

        if self._use_fast_flights():
            try:
                results = self._from_one_way_results(
                    depart,
                    get_flights(self._one_way_query(depart)),
                )
                if results:
                    return results
            except Exception as error:
                errors.append(f"fast-flights: {error}")

        if self._use_fli():
            try:
                results = self._fli_one_way_results(depart)
                if results:
                    return results
            except Exception as error:
                errors.append(f"fli: {error}")

        if len(errors) >= int(self._use_fast_flights()) + int(self._use_fli()):
            self.stopped_reason = "Busca interrompida: " + " | ".join(errors)
        return []

    def _search_round_trip(
        self,
        month: str,
        depart: date,
        return_date: date,
    ) -> list[FareCandidate]:
        errors: list[str] = []

        if self._use_fast_flights():
            try:
                results = self._from_round_trip_results(
                    month,
                    depart,
                    return_date,
                    get_flights(self._round_trip_query(depart, return_date)),
                )
                if results:
                    return results
            except Exception as error:
                errors.append(f"fast-flights: {error}")

        if self._use_fli():
            try:
                results = self._fli_round_trip_results(month, depart, return_date)
                if results:
                    return results
            except Exception as error:
                errors.append(f"fli: {error}")

        if len(errors) >= int(self._use_fast_flights()) + int(self._use_fli()):
            self.stopped_reason = "Busca interrompida: " + " | ".join(errors)
        return []

    def _use_fast_flights(self) -> bool:
        return HAS_FAST_FLIGHTS and self.engine_mode in {"fast+fli", "fast-flights"}

    def _use_fli(self) -> bool:
        return HAS_FLI and self.engine_mode in {"fast+fli", "fli"}

    def _from_one_way_results(self, depart: date, response) -> list[OneWayCandidate]:
        flights = list(response or [])
        if not flights:
            return []

        best = min(flights, key=lambda item: item.price)
        if int(best.price) > self.max_one_way_price:
            return []

        return [
            OneWayCandidate(
                depart_date=depart.isoformat(),
                price=int(best.price),
                airlines=", ".join(best.airlines),
            )
        ]

    def _from_round_trip_results(
        self,
        month: str,
        depart: date,
        return_date: date,
        response,
    ) -> list[FareCandidate]:
        flights = list(response or [])
        if not flights:
            return []

        best = min(flights, key=lambda item: item.price)
        if int(best.price) > self.max_round_trip_price:
            return []

        return [
            FareCandidate(
                month=month,
                depart_date=depart.isoformat(),
                return_date=return_date.isoformat(),
                price=int(best.price),
                airlines=", ".join(best.airlines),
                stops=self._stops_label(best),
            )
        ]

    def _fli_one_way_results(self, depart: date) -> list[OneWayCandidate]:
        response = FliSearchFlights().search(
            FliFlightSearchFilters(
                trip_type=FliTripType.ONE_WAY,
                passenger_info=FliPassengerInfo(adults=1),
                flight_segments=[
                    self._fli_segment(self.origin, self.destination, depart)
                ],
                seat_type=FliSeatType.ECONOMY,
            ),
            top_n=5,
            currency=self.currency,
            language=self.language,
            country="BR",
        )
        results = list(response or [])
        if not results:
            return []

        best = min(results, key=lambda item: item.price or 10**9)
        price = int(round(best.price or 0))
        if price <= 0 or price > self.max_one_way_price:
            return []

        return [
            OneWayCandidate(
                depart_date=depart.isoformat(),
                price=price,
                airlines=self._fli_airlines(best),
            )
        ]

    def _fli_round_trip_results(
        self,
        month: str,
        depart: date,
        return_date: date,
    ) -> list[FareCandidate]:
        response = FliSearchFlights().search(
            FliFlightSearchFilters(
                trip_type=FliTripType.ROUND_TRIP,
                passenger_info=FliPassengerInfo(adults=1),
                flight_segments=[
                    self._fli_segment(self.origin, self.destination, depart),
                    self._fli_segment(self.destination, self.origin, return_date),
                ],
                seat_type=FliSeatType.ECONOMY,
            ),
            top_n=5,
            currency=self.currency,
            language=self.language,
            country="BR",
        )
        options = list(response or [])
        if not options:
            return []

        best = min(options, key=self._fli_option_price)
        price = int(round(self._fli_option_price(best)))
        if price <= 0 or price > self.max_round_trip_price:
            return []

        return [
            FareCandidate(
                month=month,
                depart_date=depart.isoformat(),
                return_date=return_date.isoformat(),
                price=price,
                airlines=self._fli_airlines(best),
                stops=self._fli_stops_label(best),
            )
        ]

    def _fli_segment(self, origin: str, destination: str, travel_date: date):
        return FliFlightSegment(
            departure_airport=[[self._fli_airport(origin), 0]],
            arrival_airport=[[self._fli_airport(destination), 0]],
            travel_date=travel_date.isoformat(),
        )

    @staticmethod
    def _fli_airport(code: str):
        try:
            return getattr(FliAirport, code.upper())
        except AttributeError as error:
            raise ValueError(f"Aeroporto nao encontrado no Fli: {code}") from error

    @staticmethod
    def _fli_option_legs(option) -> list:
        if isinstance(option, tuple):
            return list(option)
        return [option]

    def _fli_option_price(self, option) -> float:
        prices = [
            float(leg.price)
            for leg in self._fli_option_legs(option)
            if getattr(leg, "price", None)
        ]
        if not prices:
            return 10**9
        return min(prices)

    def _fli_airlines(self, option) -> str:
        airlines: list[str] = []
        for leg in self._fli_option_legs(option):
            airline = getattr(leg, "primary_airline_name", None)
            if airline and airline not in airlines:
                airlines.append(airline)
        return ", ".join(airlines)

    def _fli_stops_label(self, option) -> str:
        legs = self._fli_option_legs(option)
        stops = [int(getattr(leg, "stops", 0) or 0) for leg in legs]
        if not stops:
            return ""
        if len(stops) == 1 or all(item == stops[0] for item in stops):
            return self._single_stops_label(stops[0])
        if len(stops) >= 2:
            return (
                f"Ida {self._single_stops_label(stops[0]).lower()} / "
                f"volta {self._single_stops_label(stops[1]).lower()}"
            )
        return self._single_stops_label(sum(stops))

    def _from_current_results(self, month: str, depart: date, return_date: date, response):
        flights = list(response or [])
        if not flights:
            return []

        best = min(flights, key=lambda item: item.price)
        if int(best.price) > self.max_round_trip_price:
            return []

        return [
            FareCandidate(
                month=month,
                depart_date=depart.isoformat(),
                return_date=return_date.isoformat(),
                price=int(best.price),
                airlines=", ".join(best.airlines),
                stops=self._stops_label(best),
            )
        ]

    def _one_way_query(self, depart: date):
        return create_query(
            flights=[
                FlightQuery(
                    date=depart.isoformat(),
                    from_airport=self.origin,
                    to_airport=self.destination,
                ),
            ],
            seat="economy",
            trip="one-way",
            passengers=Passengers(adults=1),
            language=self.language,
            currency=self.currency,
        )

    def _round_trip_query(self, depart: date, return_date: date):
        return create_query(
            flights=[
                FlightQuery(
                    date=depart.isoformat(),
                    from_airport=self.origin,
                    to_airport=self.destination,
                ),
                FlightQuery(
                    date=return_date.isoformat(),
                    from_airport=self.destination,
                    to_airport=self.origin,
                ),
            ],
            seat="economy",
            trip="round-trip",
            passengers=Passengers(adults=1),
            language=self.language,
            currency=self.currency,
        )

    def _safe_get_flights(self, query):
        try:
            return get_flights(query)
        except Exception as error:
            self.stopped_reason = f"Busca interrompida: {error}"
            return None

    def _stops_label(self, option) -> str:
        legs = getattr(option, "flights", []) or []
        if not legs:
            return ""

        split_at = None
        for index, leg in enumerate(legs):
            if getattr(leg.from_airport, "code", "") == self.destination:
                split_at = index
                break

        if split_at is None:
            total_stops = max(0, len(legs) - 2)
            return self._single_stops_label(total_stops)

        outbound_stops = max(0, split_at - 1)
        return_stops = max(0, len(legs) - split_at - 1)
        if outbound_stops == return_stops:
            return self._single_stops_label(outbound_stops)

        return (
            f"Ida {self._single_stops_label(outbound_stops).lower()} / "
            f"volta {self._single_stops_label(return_stops).lower()}"
        )

    @staticmethod
    def _single_stops_label(stops: int) -> str:
        if stops <= 0:
            return "Direto"
        if stops == 1:
            return "1 escala"
        return f"{stops} escalas"

    @staticmethod
    def _month_range(start_month: str, end_month: str):
        current = datetime.strptime(start_month, "%Y-%m").date().replace(day=1)
        end = datetime.strptime(end_month, "%Y-%m").date().replace(day=1)
        while current <= end:
            yield current.strftime("%Y-%m")
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    def _month_dates(self, month: str) -> list[date]:
        year, month_number = (int(part) for part in month.split("-"))
        _, last_day = monthrange(year, month_number)
        return [date(year, month_number, day) for day in range(1, last_day + 1)]

    def _month_query_count(self, month: str) -> int:
        one_way_queries = len(self._month_dates(month))
        trip_lengths = self.MAX_TRIP_DAYS - self.MIN_TRIP_DAYS + 1
        round_trip_queries = self.TOP_ONE_WAY_DATES * trip_lengths
        return one_way_queries + round_trip_queries

    @staticmethod
    def _status(callback, current: int, total: int, text: str) -> None:
        if callback:
            callback(current, total, text)

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Explorador de Precos de Passagens")
        self.root.geometry("1040x640")
        self.results: list[FareCandidate] = []
        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(frame)
        form.pack(fill=tk.X)

        self.origin = tk.StringVar(value="BSB")
        self.destination = tk.StringVar(value="IGU")
        self.start_month = tk.StringVar(value="2026-08")
        self.end_month = tk.StringVar(value="2026-12")
        self.top_per_month = tk.IntVar(value=3)
        self.max_one_way_price = tk.IntVar(value=500)
        self.max_round_trip_price = tk.IntVar(value=900)
        self.engine_mode = tk.StringVar(value="fast+fli")

        fields = [
            ("Origem", self.origin, 8),
            ("Destino", self.destination, 8),
            ("Mes inicial", self.start_month, 10),
            ("Mes final", self.end_month, 10),
            ("Top/mes", self.top_per_month, 5),
            ("Teto ida", self.max_one_way_price, 7),
            ("Teto ida+volta", self.max_round_trip_price, 7),
        ]

        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky="w", padx=(0, 8))
            ttk.Entry(form, textvariable=variable, width=width).grid(
                row=1, column=column, sticky="w", padx=(0, 14)
            )

        engine_column = len(fields)
        ttk.Label(form, text="Motor").grid(row=0, column=engine_column, sticky="w", padx=(0, 8))
        self.engine_combo = ttk.Combobox(
            form,
            textvariable=self.engine_mode,
            values=("fast+fli", "fast-flights", "fli"),
            width=11,
            state="readonly",
        )
        self.engine_combo.grid(row=1, column=engine_column, sticky="w", padx=(0, 14))

        self.search_button = ttk.Button(form, text="Buscar", command=self._start)
        self.search_button.grid(row=1, column=engine_column + 1, sticky="w")

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(14, 4))

        self.status = ttk.Label(frame, text="Pronto")
        self.status.pack(anchor="w")

        columns = (
            "month",
            "depart",
            "return",
            "price",
            "airlines",
            "stops",
        )
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
            "airlines": 240,
            "stops": 220,
        }

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 8))

        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        for column in columns:
            self.table.heading(column, text=labels[column])
            self.table.column(column, width=widths[column], anchor="center")

        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Salvar CSV", command=self._save_csv).pack(side=tk.LEFT)

    def _start(self) -> None:
        try:
            origin = self.origin.get().strip().upper()
            destination = self.destination.get().strip().upper()
            if not is_iata_code(origin) or not is_iata_code(destination):
                raise ValueError("Origem e destino devem ser codigos IATA de 3 letras.")
            if self.top_per_month.get() <= 0:
                raise ValueError("Top/mes deve ser maior que zero.")
            if self.max_one_way_price.get() <= 0:
                raise ValueError("Teto ida deve ser maior que zero.")
            if self.max_round_trip_price.get() <= 0:
                raise ValueError("Teto ida+volta deve ser maior que zero.")
            if self.max_one_way_price.get() > self.max_round_trip_price.get():
                raise ValueError("Teto ida nao pode ser maior que teto ida+volta.")
            if self.engine_mode.get() not in {"fast+fli", "fast-flights", "fli"}:
                raise ValueError("Motor invalido.")
            datetime.strptime(self.start_month.get(), "%Y-%m")
            datetime.strptime(self.end_month.get(), "%Y-%m")
        except ValueError as error:
            messagebox.showerror("Entrada invalida", str(error))
            return

        self.search_button.configure(state=tk.DISABLED)
        self.progress["value"] = 0
        self.status.configure(text="Iniciando busca")
        self.table.delete(*self.table.get_children())
        self.results = []

        thread = threading.Thread(target=self._work, daemon=True)
        thread.start()

    def _work(self) -> None:
        try:
            explorer = FlightExplorer(
                origin=self.origin.get(),
                destination=self.destination.get(),
                top_per_month=self.top_per_month.get(),
                max_one_way_price=self.max_one_way_price.get(),
                max_round_trip_price=self.max_round_trip_price.get(),
                engine_mode=self.engine_mode.get(),
            )
            results = explorer.search(
                self.start_month.get(),
                self.end_month.get(),
                on_status=self._thread_status,
            )
            stopped_reason = explorer.stopped_reason
            self.root.after(0, lambda: self._show_results(results, stopped_reason))
        except Exception as error:
            self.root.after(0, lambda: self._show_error(error))

    def _thread_status(self, current: int, total: int, text: str) -> None:
        self.root.after(0, lambda: self._set_status(current, total, text))

    def _set_status(self, current: int, total: int, text: str) -> None:
        percent = 0 if total <= 0 else min(100, current / total * 100)
        self.progress["value"] = percent
        self.status.configure(text=f"{percent:.0f}% - {text} ({current}/{total})")

    def _show_results(self, results: list[FareCandidate], stopped_reason: str = "") -> None:
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

        self.search_button.configure(state=tk.NORMAL)
        if stopped_reason:
            self.status.configure(
                text=f"Busca interrompida. {len(results)} opcoes parciais encontradas"
            )
            messagebox.showwarning(
                "Busca interrompida",
                f"{stopped_reason}\n\nMostrando o que foi encontrado ate aqui.",
            )
            return

        self.progress["value"] = 100
        self.status.configure(text=f"100% - {len(results)} opcoes encontradas")
        if not results:
            messagebox.showinfo("Busca concluida", "Nenhum preco foi encontrado.")

    def _show_error(self, error: Exception) -> None:
        self.search_button.configure(state=tk.NORMAL)
        self.status.configure(text="Erro na busca")
        messagebox.showerror("Erro", str(error))

    def _save_csv(self) -> None:
        if not self.results:
            messagebox.showwarning("Sem dados", "Execute uma busca antes de salvar.")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not filename:
            return

        with open(filename, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["mes", "ida", "volta", "preco", "companhia", "escalas"])
            for item in self.results:
                writer.writerow(
                    [
                        item.month,
                        item.depart_date,
                        item.return_date,
                        item.price,
                        item.airlines,
                        item.stops,
                    ]
                )

        messagebox.showinfo("CSV salvo", filename)

    @staticmethod
    def _br_date(value: str) -> str:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        return parsed.strftime("%d/%m/%Y")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
