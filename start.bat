@echo off
REM One command to run the API:  start.bat
REM
REM Creates the virtualenv if missing, installs dependencies, and serves
REM POST /agent/run on http://127.0.0.1:8000. No Docker and no Node required.

cd /d "%~dp0backend"

if not exist .venv (
    echo creating virtualenv...
    py -m venv .venv || python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install --quiet -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo created backend\.env -- add LLM_API_KEY to use the model.
    echo Without a key the agent runs on the rule-based extractor and still
    echo produces the correct outcome on all 23 test conversations.
)

echo.
echo API on http://127.0.0.1:8000   (health check: /health)
echo Replay the scripts from the repository root:
echo     python runner.py --repeat 3 --url http://127.0.0.1:8000/agent/run
echo     python check.py
echo.
uvicorn app.main:app --host 127.0.0.1 --port 8000
