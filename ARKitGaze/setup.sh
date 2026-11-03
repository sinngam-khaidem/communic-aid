#!/usr/bin/env bash
# Sets up the Python environment for the gaze receiver.
set -euo pipefail
cd "$(dirname "$0")"

uv venv --python 3.11 .venv
uv pip install --python .venv --quiet "numpy<2" pyautogui

echo "Ready. Run with:  ./run.sh"
