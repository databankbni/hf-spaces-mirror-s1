@echo off
cd /d "%~dp0"
echo ============================================
echo   Private Credit Canary Monitoring - Start
echo ============================================
echo.

echo [1/6] Sync downloaded data (unpack ZIP / strip "(1)" suffix)...
venv\Scripts\python.exe tools\sync_data.py
echo.

echo [2/6] News summary...
venv\Scripts\python.exe tools\summarize_news.py
echo.

echo [3/6] SEC filing summary refine...
venv\Scripts\python.exe tools\summarize_filings.py
echo.

echo [4/6] Risk score calculation (multi-agent + combiner)...
venv\Scripts\python.exe tools\score_risk.py
echo.

echo [5/6] Push latest data to Hugging Face Space (auto-redeploys)...
git add data/ 2>nul
git commit -m "daily data update" 2>nul
git push 2>nul
echo.

echo [6/6] Starting Streamlit (local)...
echo Browser will open automatically.
echo To stop, press Ctrl + C twice in this window.
echo.
venv\Scripts\streamlit.exe run app.py
