# linkedin_job_scraper

Scraper Python di annunci di lavoro LinkedIn per ruoli Infrastructure / AI / Datacenter / Technical Presales, con normalizzazione, deduplica, storage SQLite, export CSV e una WebGUI Flask interna per consultazione, matching e salvataggio.

Usa la **Guest API di LinkedIn**: nessun account o login richiesto, nessuna credentiale nel codice.

> ⚠️ **Disclaimer**: il progetto usa endpoint pubblici non documentati di LinkedIn, senza autenticazione. È pensato per uso **personale e non intensivo** (un run al giorno). Rispetta i termini di servizio di LinkedIn e i rate limit; usalo sotto la tua responsabilità.

## Caratteristiche

- **Scraping senza login** (Guest API): ricerca per combinazioni `keywords × locations` definite in `config.yaml`.
- **Normalizzazione e merge** dei dettagli annuncio (`scraper/parser.py`), filtri keyword e **deduplica** (`scraper/filters.py`).
- **Storage SQLite** (`storage/database.py`): schema versionato, upsert, snapshot CSV completo a fine run (`storage/exporter.py`).
- **Ciclo di vita degli annunci**: un nuovo annuncio entra con badge **Nuovo** (`is_new=1`) e lo perde al ritrovamento successivo; dopo `scraping.absence_confirmation_runs` (default `2`) assenze consecutive valide viene **eliminato fisicamente** dal DB. Le ricerche fallite o rate-limited **non** incrementano le assenze.
- **Identità logica**: ogni annuncio è identificato da `(job_id, search_keywords, search_location)`: lo stesso job trovato da query diverse genera record distinti.
- **WebGUI Flask** (`webapp/`): filtri, paginazione, ordinamento, **score CV** automatico, pagina "Lavori salvati" e avvio scraping in background con lock anti-sovrapposizione (`flock`).
- **Notifier** (`notifier/`).
- **Scheduling**: wrapper `run_daily.sh` pensato per cron, con `flock` che impedisce run sovrapposti (cron o WebGUI non possono eseguire insieme).

## Architettura

```text
LinkedIn Guest API
  → scraper/guest_api.py             # ricerca e dettaglio annunci
  → scraper/parser.py                # normalizzazione/merge dei dettagli
  → scraper/filters.py               # keyword e deduplica
  → storage/database.py              # schema SQLite, upsert, ciclo di vita
  → data/jobs.db
  → storage/exporter.py              # snapshot CSV in data/exports/

main.py                              # orchestrazione dell'intero run
webapp/app.py + webapp/matching.py   # Flask, filtri e score CV
webapp/templates/ + webapp/static/   # UI
run_daily.sh                         # wrapper con flock per cron / WebGUI
```

## Installazione

```bash
git clone https://github.com/Dielabs/linkedin_job_scraper.git
cd linkedin_job_scraper
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Configurazione: adattare `config.yaml` con le proprie ricerche (keyword, Paesi, timing, `fetch_details`, soglie di assenza). Nessun segreto richiesto.

## Uso

```bash
# run di scraping
./venv/bin/python main.py config.yaml

# oppure via wrapper (lock, log, PID)
./run_daily.sh

# WebGUI (porta 5000; non esporla pubblicamente senza auth + reverse proxy + HTTPS)
./venv/bin/python -m webapp.app
```

WebGUI principale: `GET /` con filtri, paginazione, ordinamento e score CV; `GET /saved` per gli annunci salvati; `POST /update` avvia lo scraping in background.

### Score CV

`webapp/matching.py` assegna un punteggio di compatibilità CV→annuncio. Nota: se nel titolo, descrizione, query di origine o funzione compare `Azure` o `AWS`, il punteggio finale viene ridotto una sola volta del 40% (fattore `0.60`), anche se entrambi i termini sono presenti.

## File per area

| Esigenza | File |
|---|---|
| Ricerche, Paesi, filtri | `config.yaml` |
| Orchestrazione | `main.py` |
| API/parsing/filtri | `scraper/` |
| Schema, deduplica, ciclo di vita | `storage/database.py` |
| Export CSV | `storage/exporter.py` |
| Rotte e query WebGUI | `webapp/app.py` |
| Layout/UI | `webapp/templates/`, `webapp/static/style.css` |
| Scheduling | `run_daily.sh` |

## Note

- Dati, log ed export restano tutti sotto `data/` (ignorato da git).
- `PROJECT_STATUS.md` contiene il contesto operativo interno del progetto (flussi, requisiti vincolanti, note di deploy).

## Licenza

Uso interno / personale. Nessuna garanzia.
