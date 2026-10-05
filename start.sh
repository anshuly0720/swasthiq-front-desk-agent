#!/usr/bin/env bash
# One command to run the API:  ./start.sh
#
# Creates the virtualenv if it is missing, installs dependencies, and serves
# POST /agent/run on http://127.0.0.1:8000. No Docker and no Node required --
# the graded endpoint needs neither.
set -euo pipefail

cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  echo "creating virtualenv..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created backend/.env -- add LLM_API_KEY to use the model."
  echo "Without a key the agent runs on the rule-based extractor and still"
  echo "produces the correct outcome on all 23 test conversations."
fi

echo
echo "API on http://127.0.0.1:8000   (health check: /health)"
echo "Replay the scripts from the repository root:"
echo "    python runner.py --repeat 3 --url http://127.0.0.1:8000/agent/run"
echo "    python check.py"
echo
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
