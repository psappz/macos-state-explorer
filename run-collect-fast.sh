#!/usr/bin/env bash
set -euo pipefail
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -e ".[dev]"
mse collect --fast --out "$HOME/Desktop/mse-fast-report"
open "$HOME/Desktop/mse-fast-report/index.html"
