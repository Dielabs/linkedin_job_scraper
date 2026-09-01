# linkedin_job_scraper

Scraper di offerte di lavoro LinkedIn (guest API, nessun login richiesto), con:
- storage SQLite (`storage/`) ed export CSV
- webapp Flask per consultazione/matching (`webapp/`)
- notifier
- esecuzione giornaliera via `run_daily.sh` (cron)

Installazione: `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
Config: copiare `config.yaml` e adattare le ricerche.
Stato del progetto: vedi `PROJECT_STATUS.md`.
