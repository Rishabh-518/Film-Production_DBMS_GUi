$env:APP_DBNAME = "film_demo"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run "$PSScriptRoot\app.py"
