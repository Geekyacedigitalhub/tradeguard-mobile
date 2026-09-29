@echo off
setlocal
cd /d "%~dp0"

if not exist "config.json" (
  echo Missing config.json
  echo Copy config.example.json to config.json and fill in your TradeGuard values.
  pause
  exit /b 1
)

python -m pip install -r requirements.txt
python bridge.py
