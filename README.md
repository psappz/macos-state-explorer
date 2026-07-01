# macOS State Explorer v1

Read-only macOS reverse-engineering and forensic state platform.

Initial case:

> Explain why apps appear in **System Settings → Privacy & Security → Local Network** even when no `kTCCServiceLocalNetwork` rows exist in `TCC.db`.

## Install

```bash
cd macos-state-explorer-v1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

## Commands

```bash
mse --help
mse collect ~/Desktop/mse-fast --fast-report
mse launchservices ~/Desktop/mse-ls
mse trace local-network ~/Desktop/mse-local-network-trace
mse experiment local-network --out ~/Desktop/mse-local-network-experiment
mse doctor
```

## Safety

The tool is read-only. It does not reset TCC, delete caches, unregister apps, or change system settings.
