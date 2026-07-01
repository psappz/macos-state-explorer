#!/usr/bin/env bash
set -euo pipefail
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -e ".[dev]"
sudo true
mse trace local-network --out "$HOME/Desktop/mse-local-network-trace"
