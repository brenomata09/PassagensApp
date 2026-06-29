"""
Verificação pontual de snapshots contra o Google Flights.
Nunca lança exceção para o caller — erros são capturados internamente.
"""
from __future__ import annotations

import json
import subprocess

from core.engine_fli import find_fli, parse_price
from core.models import money
from core import storage


def _run_one_way_check(origin: str, destination: str, departure_date: str, currency: str) -> float | None:
    try:
        cmd = [
            find_fli(), "dates", origin, destination,
            "--from", departure_date,
            "--to",   departure_date,
            "--currency", currency,
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
        dates = payload.get("dates", []) if isinstance(payload, dict) else payload
        for item in dates:
            if not isinstance(item, dict):
                continue
            dep = str(item.get("departure_date") or item.get("date") or "")[:10]
            if dep == str(departure_date)[:10] and item.get("price") is not None:
                return parse_price(item["price"])
    except Exception:
        pass
    return None


def _run_exact_google_flights_check(snapshot) -> float | None:
    if str(snapshot["snapshot_kind"]) != "TOTAL":
        return None

    try:
        raw = json.loads(snapshot["raw_json"] or "{}")
    except Exception:
        return None

    strategy = raw.get("raw", {}).get("strategy", "")
    currency = str(snapshot["currency"] or "BRL")

    # Snapshot de trechos combinados: verifica cada trecho separado
    if strategy in {"top_3_legs", "calendar_leg_combinations"}:
        try:
            outbound = raw["raw"]["outbound"]
            return_leg = raw["raw"]["return"]
            p_out = _run_one_way_check(
                str(outbound["origin"]), str(outbound["destination"]),
                str(outbound["departure_date"]), currency,
            )
            p_ret = _run_one_way_check(
                str(return_leg["origin"]), str(return_leg["destination"]),
                str(return_leg["departure_date"]), currency,
            )
            if p_out is not None and p_ret is not None:
                return p_out + p_ret
        except Exception:
            pass
        return None

    # Snapshot TOTAL direto (fli dates --round)
    duration = snapshot["trip_duration"]
    if not duration:
        return None

    try:
        cmd = [
            find_fli(), "dates",
            str(snapshot["origin"]), str(snapshot["destination"]),
            "--from", str(snapshot["departure_date"]),
            "--to",   str(snapshot["departure_date"]),
            "--round", "--duration", str(int(duration)),
            "--currency", currency,
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
        dates = payload.get("dates", []) if isinstance(payload, dict) else payload
        for item in dates:
            if not isinstance(item, dict):
                continue
            if str(item.get("departure_date"))[:10] != str(snapshot["departure_date"])[:10]:
                continue
            if str(item.get("return_date"))[:10] != str(snapshot["return_date"])[:10]:
                continue
            if item.get("price") is not None:
                return parse_price(item["price"])
    except Exception:
        pass
    return None


def verify_snapshot(snapshot, batch_id: str, tolerance: float = 1.0) -> dict:
    """
    Verifica o snapshot contra o Google Flights.
    Nunca lança exceção — erros retornam status ERROR.
    """
    expected = float(snapshot["price"])
    observed = None
    diff = None
    status = "NOT_CONFIRMED"
    msg = "Preco nao encontrado na verificacao pontual."

    try:
        observed = _run_exact_google_flights_check(snapshot)
        if observed is not None:
            diff = observed - expected
            if abs(diff) <= tolerance:
                status = "CONFIRMED"
                msg = f"Confirmado: {money(observed, snapshot['currency'])}."
            else:
                status = "DIVERGENT"
                msg = (
                    f"Divergente: esperado {money(expected, snapshot['currency'])}, "
                    f"observado {money(observed, snapshot['currency'])}."
                )
    except Exception as exc:
        status = "ERROR"
        msg = f"Erro na verificacao: {type(exc).__name__}: {exc}"

    try:
        storage.record_source_check(
            route_id=str(snapshot["route_id"]),
            snapshot_id=int(snapshot["id"]),
            batch_id=batch_id,
            source="google_flights_exact",
            status=status,
            expected_price=expected,
            observed_price=observed,
            difference=diff,
            message=msg,
        )
    except Exception:
        pass  # falha no registro não deve bloquear o alerta

    return {
        "status": status,
        "expected_price": expected,
        "observed_price": observed,
        "difference": diff,
        "message": msg,
    }
