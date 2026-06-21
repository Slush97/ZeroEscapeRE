@echo off
REM One-time setup. Needs Python 3.11 (bpy is pinned to it) and nothing else.
py -3.11 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e helper
echo.
echo Setup done. Now run:
echo   .venv\Scripts\activate
echo   python run_all.py "C:\path\to\ze2_data_en_us.bin"
