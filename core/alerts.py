"""
Sistema de alertas do PassagensApp.
Envia notificações via Telegram com contexto completo:
rota, preço, datas, tipo do alerta, teto configurado e fonte.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from core.config import settings
from core.models import money
from core import storage
from core.source_check import verify_snapshot

MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

ALERT_LABELS = {
    "BELOW_CEILING": "ABAIXO DO TETO",
    "ABOVE_CEILING": "ACIMA DO TETO",
    "NEW_LOW":       "NOVO MINIMO",
}

TELEGRAM_SENT_DIR: Path = settings.root / "data" / "telegram_sent_batches"


def _claim_batch_send(batch_id: str) -> Path | None:
    TELEGRAM_SENT_DIR.mkdir(parents=True, exist_ok=True)
    marker = TELEGRAM_SENT_DIR / f"{batch_id}.sent"
    try:
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("claimed")
        return marker
    except FileExistsError:
        return None


def send_telegram(text: str) -> bool:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        print("[Telegram] nao configurado. Mensagem:")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"[Telegram] falha ao enviar: {exc}")
        return False


def ceiling_for(route, kind: str):
    if kind == "TOTAL":
        return route.price_ceiling_total
    if kind == "OUTBOUND":
        return route.price_ceiling_outbound
    if kind == "RETURN":
        return route.price_ceiling_return
    return None


def decide(route, snapshot, batch_id: str):
    if snapshot is None:
        return None

    route_id = str(snapshot["route_id"])
    kind = str(snapshot["snapshot_kind"])
    price = float(snapshot["price"])
    currency = snapshot["currency"] or route.currency

    # Só alertas TOTAL são válidos para Telegram
    if kind != "TOTAL":
        return None

    prev = storage.previous_best(route_id, batch_id, kind)
    prev_batch = storage.previous_batch_best(route_id, batch_id, kind)
    ceiling = ceiling_for(route, kind)

    if ceiling is not None and price <= float(ceiling):
        if storage.has_recent_alert_type(route_id, "BELOW_CEILING", settings.alert_silence_hours, kind):
            return None
        return ("BELOW_CEILING", prev, f"Preco abaixo do teto: {money(price, currency)} <= {money(ceiling, currency)}")

    if ceiling is not None and prev_batch is not None and prev_batch <= float(ceiling) and price > float(ceiling):
        if storage.has_recent_alert_type(route_id, "ABOVE_CEILING", settings.alert_silence_hours, kind):
            return None
        return ("ABOVE_CEILING", prev_batch, f"Preco superou o teto: {money(price, currency)} > {money(ceiling, currency)}")

    if prev is not None and price < prev:
        if storage.has_recent_alert_type(route_id, "NEW_LOW", settings.alert_silence_hours, kind):
            return None
        return ("NEW_LOW", prev, f"Novo menor preco: {money(price, currency)} < {money(prev, currency)}")

    return None


def monthly_best_text(route_id: str, batch_id: str, currency: str) -> str:
    rows = storage.monthly_best_in_batch(route_id, batch_id, "TOTAL")
    if not rows:
        return ""
    lines = ["", "<b>Menores por mes:</b>"]
    for row in rows:
        month = MONTH_NAMES.get(int(row["month_number"]), str(row["month_number"]))
        lines.append(
            f"  {month}: {money(row['price'], row['currency'] or currency)} "
            f"| ida {row['departure_date']} | volta {row['return_date'] or '-'}"
        )
    return "\n".join(lines)


def message(route, snapshot, batch_id: str, alert_type: str, reason: str, source_check: dict | None = None) -> str:
    currency = snapshot["currency"] or route.currency
    price = float(snapshot["price"])
    ceiling = ceiling_for(route, "TOTAL")
    label = ALERT_LABELS.get(alert_type, alert_type)
    source = str(snapshot.get("data_source") or "google_flights").replace("_", " ").title()

    lines = [
        f"<b>PassagensApp — {label}</b>",
        f"Rota: <b>{route.origin} → {route.destination}</b>",
        f"Preco: <b>{money(price, currency)}</b>",
        f"Ida:   {snapshot['departure_date']}",
        f"Volta: {snapshot['return_date'] or '-'}",
    ]

    if ceiling is not None:
        lines.append(f"Teto:  {money(ceiling, currency)}")

    lines.append(f"Fonte: {source}")

    if source_check and source_check.get("status") == "CONFIRMED":
        lines.append("Verificacao: confirmado no Google Flights")
    elif source_check and source_check.get("status") == "DIVERGENT":
        obs = source_check.get("observed_price")
        lines.append(f"Verificacao: divergente (Google Flights: {money(obs, currency)})")

    # Menores por mês
    monthly = monthly_best_text(str(snapshot["route_id"]), batch_id, currency)
    if monthly:
        lines.append(monthly)

    return "\n".join(lines)


def sweep_summary_message(batch_id: str, routes: list) -> str:
    lines = ["<b>PassagensApp — Resultado da busca</b>"]
    found = False
    for route in routes:
        snapshot = storage.best_in_batch(route.id, batch_id, "TOTAL")
        if not snapshot:
            lines.append(f"  {route.origin} → {route.destination}: sem resultado")
            continue
        found = True
        currency = snapshot["currency"] or route.currency
        ceiling = route.price_ceiling_total
        preco = money(float(snapshot["price"]), currency)
        teto = f" | teto {money(ceiling, currency)}" if ceiling else ""
        lines.append(
            f"  {route.origin} → {route.destination}: {preco}"
            f" | ida {snapshot['departure_date']} | volta {snapshot['return_date'] or '-'}{teto}"
        )
    return "\n".join(lines) if found else ""


def send_sweep_summary(batch_id: str, routes: list) -> bool:
    marker = _claim_batch_send(batch_id)
    if marker is None:
        print(f"[Telegram] batch {batch_id} ja enviado; ignorando reenvio.")
        return False

    text = sweep_summary_message(batch_id, routes)
    if not text:
        marker.unlink(missing_ok=True)
        return False
    sent = send_telegram(text)
    if not sent:
        marker.unlink(missing_ok=True)
    return sent


def process(route, snapshot, batch_id: str) -> bool:
    d = decide(route, snapshot, batch_id)
    if not d:
        return False
    alert_type, prev, reason = d

    # source_check roda em try/except para nunca travar o alerta
    source_check = None
    try:
        source_check = verify_snapshot(snapshot, batch_id)
    except Exception as exc:
        print(f"[source_check] erro (ignorado): {exc}")

    msg = message(route, snapshot, batch_id, alert_type, reason, source_check)

    storage.record_alert(
        route_id=str(snapshot["route_id"]),
        snapshot_id=int(snapshot["id"]),
        kind=str(snapshot["snapshot_kind"]),
        alert_type=alert_type,
        price=float(snapshot["price"]),
        previous_price=prev,
        message=msg,
    )
    return False
