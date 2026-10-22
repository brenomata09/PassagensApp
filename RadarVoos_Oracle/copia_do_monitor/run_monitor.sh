#!/usr/bin/env bash
set -Eeuo pipefail
cd "/home/ubuntu/PassagensApp"
exec "/home/ubuntu/PassagensApp/.venv/bin/python" "/home/ubuntu/PassagensApp/monitor_cli.py"
