#!/usr/bin/env bash
# Runner comune per cron e WebGUI: un unico flock impedisce run concorrenti.
set -u

PROJECT_DIR="/opt/linkedin_job_scraper"
LOG_DIR="$PROJECT_DIR/data/cron"
LOCK_FILE="$PROJECT_DIR/data/scraper.lock"
RETENTION_DAYS=30

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data/exports"
cd "$PROJECT_DIR"

# Se un run è già attivo, flock restituisce subito: nessuna seconda istanza viene avviata.
/usr/bin/flock -n "$LOCK_FILE" \
  "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/main.py" "$PROJECT_DIR/config.yaml" \
  >> "$LOG_DIR/run_$(/bin/date +%F).log" 2>&1
status=$?

if [ "$status" -eq 1 ]; then
  echo "$(/bin/date -Is) run saltato: istanza già attiva" >> "$LOG_DIR/run_$(/bin/date +%F).log"
  exit 0
fi

# Conserva export e log cron per i 30 giorni più recenti.
/usr/bin/find "$PROJECT_DIR/data/exports" -maxdepth 1 -type f -mtime +"$RETENTION_DAYS" -delete
/usr/bin/find "$LOG_DIR" -maxdepth 1 -type f -mtime +"$RETENTION_DAYS" -delete
exit "$status"
