# Pulse Finance

Modern single-user personal finance web app with secure login, transaction tracking, budgets, and charts. Built with Flask, SQLite, and Chart.js.

## Features
- Secure auth (Flask-Login + bcrypt). Register/login/logout, password change.
- Transactions: expense/income with date, category, description, amount; filter/sort; edit/delete.
- Budgets: overall or per-category per period with progress bars.
- Dashboard & Reports: category pie, monthly net bar, balance line, summaries, recent items.
- SQLite persistence; service layer helpers; seed script with demo data.

## Stack
- Python 3.11+ (tested), Flask 3, Flask-Login, Flask-Bcrypt, Flask-SQLAlchemy, Chart.js, Bootstrap 5.

## Setup
```bash
py -m pip install -r requirements.txt
```

Optional: copy `.env.example` to `.env` and set a strong `SECRET_KEY` and a custom `DATABASE_URL` (defaults to `finance_app/finance.db`).

## Run
```bash
py app.py
```
Visit http://localhost:5000. First user: go to Register, create account, then log in.

## Deploy (Render/Fly/Railway style)
- Add env vars in your host: `SECRET_KEY=<strong secret>`, `DATABASE_URL=<your db url>`. Use Postgres for multi-user hosting; set `DATABASE_URL` accordingly. SQLite can work only if the host provides a persistent disk.
- Entrypoint: `gunicorn app:app --preload --workers 3 --threads 2`.
- Files included: `Procfile` already set for common PaaS hosts.
- For Postgres, create the DB on the platform, set `DATABASE_URL`, deploy; the app will `create_all()` on boot.

## Seed sample data (demo user)
```bash
py scripts/seed.py
# user: demo / password: demo123
```

## Tests
```bash
py -m pytest
```

## Project structure
- `app.py` – entrypoint.
- `finance_app/` – app factory, models, routes, services, config.
- `templates/` – Jinja2 pages.
- `static/` – CSS/JS/assets.
- `scripts/seed.py` – populate demo user, transactions, budgets.
- `tests/` – basic app/DB flow tests.

## Notes
- SQLite file lives at `finance_app/finance.db` by default.
- All passwords are hashed with bcrypt; no plaintext storage.
