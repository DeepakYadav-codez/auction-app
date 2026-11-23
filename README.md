# Player Auction + Match Scorecard (Flask + SQLite)

    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000

Flow: Teams -> Players -> Live Auction -> Matches (ball-by-ball scoring) -> Leaders -> Data.
Data page: Excel and PDF downloads, backup/restore, import players from CSV/Excel, new season.
Settings (MAX_SQUAD, currency label UNIT) are at the top of app.py.
Deploy: Render Web Service, build `pip install -r requirements.txt`, start `gunicorn app:app`.
