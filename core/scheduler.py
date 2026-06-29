from __future__ import annotations

import argparse
import time
from datetime import datetime

from core.config import settings
from core.sweep import run_sweep


def run_forever(interval_hours: int | None = None) -> None:
    interval = interval_hours or settings.sweep_interval_hours
    interval_seconds = max(1, int(interval * 3600))

    print(f"[scheduler] iniciado com intervalo de {interval}h", flush=True)
    while True:
        started_at = datetime.now()
        print(f"[scheduler] sweep iniciado em {started_at:%Y-%m-%d %H:%M:%S}", flush=True)
        try:
            result = run_sweep()
            print(f"[scheduler] sweep concluido: {result}", flush=True)
        except RuntimeError as exc:
            print(f"[scheduler] sweep ignorado: {exc}", flush=True)
        except Exception as exc:
            print(f"[scheduler] erro no sweep: {type(exc).__name__}: {exc}", flush=True)

        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa o monitoramento de passagens em loop.")
    parser.add_argument("--interval-hours", type=int, default=settings.sweep_interval_hours)
    args = parser.parse_args()
    run_forever(args.interval_hours)


if __name__ == "__main__":
    main()
