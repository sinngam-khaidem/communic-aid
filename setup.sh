#!/usr/bin/env bash
# Set up the Python environment for Communic-aid.
#
#   ./setup.sh          create .venv and install the app with its test tools
#   ./setup.sh --test   the same, then run the tests
#
# Safe to run again: an existing .venv is kept and only updated.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x .venv/bin/python ]]; then
  echo "Using the existing .venv"
elif command -v uv >/dev/null 2>&1; then
  echo "Creating .venv with Python 3.11 (uv)"
  uv venv --python 3.11 .venv
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Creating .venv with $(python3 --version)"
  python3 -m venv .venv
else
  echo "Needs uv or Python 3.11 or newer. The easiest fix is to install uv:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "Installing Communic-aid and its dependencies"
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python .venv/bin/python -e ".[dev]"
else
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e ".[dev]"
fi

if [[ "${1:-}" == "--test" ]]; then
  echo "Running the tests"
  .venv/bin/python -m pytest -q
fi

echo
echo "Done. To try it without the phone:"
echo "  .venv/bin/python -m communicaid --person P01 --source mouse"
echo "then open http://localhost:8080"
