# Player Auction + Match Scorecard (Flask + SQLite)

    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000

Flow: Teams -> Players -> Live Auction -> Matches (new match, choose XI, ball-by-ball scoring, scorecard).
Settings (MAX_SQUAD, currency label UNIT) are at the top of app.py.
Deploy: Render Web Service, build `pip install -r requirements.txt`, start `gunicorn app:app`.
