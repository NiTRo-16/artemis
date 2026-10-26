#!/bin/sh
# Sets up and starts Artemis on this computer (macOS or Linux). Run it again any time to start Artemis.
set -e
cd "$(dirname "$0")"

PYTHON=python3
if ! $PYTHON -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
  echo "Artemis needs Python 3.12 or later. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating the Python environment..."
  $PYTHON -m venv .venv
fi
. .venv/bin/activate

echo "Installing packages. The first run downloads about 200 MB; later runs are quick."
python -m pip install --disable-pip-version-check -q -r requirements.txt
python -m playwright install chromium

echo
echo "Artemis is starting. Open http://localhost:8000 in your browser."
echo "Account emails are printed in this window. Press Ctrl+C to stop."
echo
exec python -m uvicorn main:app --port 8000
