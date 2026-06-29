from core.sweep import run_sweep


if __name__ == "__main__":
    try:
        print(run_sweep())
    except RuntimeError as exc:
        print(str(exc))
