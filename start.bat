@echo off
REM Pass --lan to also allow phones/other devices on your Wi-Fi to connect.
set HOST=127.0.0.1
if "%1"=="--lan" set HOST=0.0.0.0

IF NOT EXIST .venv (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

IF NOT EXIST .env (
  copy .env.example .env
  echo Created .env from .env.example
)

echo.
echo Starting Garmin AI Coach...
echo Open: http://localhost:8000
echo.
uvicorn app.main:app --reload --host %HOST% --port 8000
