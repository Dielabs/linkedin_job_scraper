# Istruzioni persistenti — LinkedIn Job Scraper

Usare questo file come contesto operativo all'inizio di ogni nuova chat sul progetto. È una guida di continuità: prima di modificare qualcosa, verificare sempre lo stato effettivo dei file e dei processi sul server; questo documento non sostituisce il codice.

## Obiettivo

Scraper Python di annunci LinkedIn per ruoli Infrastructure / AI / Datacenter / Technical Presales in Italia, Svizzera e Lussemburgo. Raccoglie annunci dalla Guest API LinkedIn, li normalizza, filtra e deduplica, li salva in SQLite, genera snapshot CSV e li espone tramite una WebGUI Flask interna.

## Ambiente e regole operative

- Host di deploy: `dcserver` (`192.168.4.249`), utente `dcserver`.
- Root progetto: `/opt/linkedin_job_scraper`.
- Python: usare esclusivamente `./venv/bin/python` (Python 3.10 sul deploy corrente).
- Configurazione: `config.yaml`; DB: `data/jobs.db`; dati/log/export restano sotto `data/`.
- WebGUI interna: Flask su porta `5000`. Non esporla pubblicamente senza autenticazione, reverse proxy e HTTPS.
- Prima di una modifica: leggere i file coinvolti, effettuare backup dei file modificati, cambiare il minimo necessario e verificare sintassi/test pertinenti. Non eseguire scraping completo o riavviare/fermare processi senza necessità esplicita.
- Non modificare né cancellare `data/jobs.db`, export o log, salvo richiesta esplicita dell'utente.

## Repository Git e deploy

- **Repo Git**: \`/home/dcserver/linkedin_job_scraper\` (remote: \`origin = https://github.com/Dielabs/linkedin_job_scraper.git\`).
- **Deploy**: \`/opt/linkedin_job_scraper\` — **non è un repo Git**; è la copia di esecuzione (venv, data, config, servizi).
- I file sorgente del deploy e del repo coincidono; le differenze attese sono solo i file \`.bak\` di backup (presenti in \`/opt\`, **non** committare) e \`.gitignore\`/\`README.md\` (presenti solo nel repo).
- **Procedura di commit/push dopo modifiche al deploy**:
  1. Verificare il working tree: \`cd /home/dcserver/linkedin_job_scraper && git status --short\`.
  2. Confrontare deploy vs repo: \`diff -rq /opt/linkedin_job_scraper /home/dcserver/linkedin_job_scraper --exclude=.git --exclude=venv --exclude=data --exclude=__pycache__\`.
  3. Copiare i file modificati dal deploy al repo (es.: \`cp /opt/linkedin_job_scraper/<file> /home/dcserver/linkedin_job_scraper/<file>\`).
  4. \`git add\` dei soli file sorgente (mai \`.bak\`, \`venv/\`, \`data/\`).
  5. \`git commit -m "descrizione"\` e \`git push origin main\`.
  6. Verificare allineamento: \`git fetch origin && git log --oneline origin/main..main && git log --oneline main..origin/main\` (entrambi vuoti = allineati).
- **Regola di deduplica** (commit \`4b8519e\`): un unico record per \`job_id\`, anche se l annuncio matcha più keyword o location; \`search_keywords\` e \`search_location\` accumulano le origini multiple (separate da \` | \`).

## Architettura

```text
LinkedIn Guest API
  → scraper/guest_api.py             # ricerca e dettaglio annunci
  → scraper/parser.py                # normalizzazione/merge dei dettagli
  → scraper/filters.py               # keyword e deduplica
  → storage/database.py              # schema SQLite, upsert, ciclo di vita
  → data/jobs.db
  → storage/exporter.py              # snapshot CSV in data/exports/

main.py                              # orchestration dell'intero run
webapp/app.py + webapp/matching.py   # Flask, filtri e score CV
webapp/templates/ + webapp/static/   # UI
run_daily.sh                          # wrapper cron con flock
```

## Flussi principali

### Scraping

- Entry point: `./venv/bin/python main.py config.yaml`.
- `main.py` esegue tutte le combinazioni `keywords × locations` definite in `config.yaml`.
- L'identità logica di un annuncio è `job_id` (univoco per annuncio LinkedIn): lo stesso job trovato da query diverse confluisce in un **solo record**; `search_keywords` accumula le keyword che hanno trovato il job (separate da ` | `), `search_location` idem se diversa.
- `first_seen` non deve cambiare; `last_seen` si aggiorna a ogni ritrovamento.
- L'export è uno snapshot dell'intero DB al termine del run.
- `fetch_details: true` migliora i dati ma rende il run più lento.

### Ciclo di vita degli annunci — requisito vincolante

- Un annuncio appena inserito ha il badge/stato **Nuovo** (`is_new=1`). Quando viene ritrovato in un run successivo, perde il tag (`is_new=0`).
- Un annuncio assente deve essere **eliminato fisicamente dal DB**, non archiviato, dopo `scraping.absence_confirmation_runs` assenze consecutive valide a livello **globale** (valore attuale: `2`): un annuncio resta finché è trovato da almeno una query del run; sparisce solo se non è trovato da NESSUNA query dopo N run (`db.reconcile_global` in `storage/database.py`).
- Una ricerca fallita, rate-limited o senza card valide/non vuota affidabile **non deve** incrementare le assenze né eliminare annunci.
- Stato da verificare prima di lavorare: il codice presente potrebbe ancora applicare la vecchia semantica di soft archive (`is_active=0`, filtro “Archiviati”). Se così fosse, è una discrepanza con il requisito sopra: adeguare database, riconciliazione, export e WebGUI coerentemente quando si interviene su questa area; evitare che record inattivi restino nel DB.

### WebGUI

- `GET /`: lettura, filtri, paginazione, ordinamento e score CV.
- Salvataggio annunci: il flag persistente `jobs.is_saved` e le rotte `POST /saved`, `POST /saved/remove` alimentano `GET /saved` (pagina “Lavori salvati”). Il salvataggio è legato a `job_id` (chiave univoca) e non protegge dalla cancellazione: se la riconciliazione elimina l’annuncio dopo le assenze confermate, sparisce anche dai salvati.
- Filtro “Ruolo” della WebGUI: il dropdown legge le keyword originali da `config.yaml` (`load_search_roles`); il match su `search_keywords` (accumulato) avviene via `instr(search_keywords, ?) > 0`, non per uguaglianza esatta.
- Score CV: se nel titolo, descrizione, query di origine o funzione dell’annuncio compare `Azure` o `AWS`, il punteggio finale viene ridotto una sola volta del 40% (fattore `0,60`), anche se sono presenti entrambi i termini.
- `POST /update`: avvia `run_daily.sh` in background e salva il PID del wrapper in `data/scraper.pid`.
- Sia cron sia Update WebGUI usano `run_daily.sh`, che acquisisce `flock` su `data/scraper.lock`; quindi non possono eseguire scraping sovrapposti.
- I link LinkedIn in `webapp/templates/index.html` devono aprirsi in nuova scheda (`target="_blank"` / `noopener noreferrer`); la UI prova a mantenere il focus sulla pagina scraper, ma il comportamento finale dipende dal browser.
- Avvio persistente WebGUI: unità di sistema `linkedin-job-scraper-webgui.service` (`/etc/systemd/system/`), abilitata su `multi-user.target`; esegue come utente `dcserver` dalla root del progetto: `/opt/linkedin_job_scraper/venv/bin/python -m webapp.app`, con `WEBAPP_HOST=0.0.0.0`, `WEBAPP_PORT=5000`, riavvio `on-failure` dopo 5 secondi. Gestire con `sudo systemctl {status|restart|stop} linkedin-job-scraper-webgui.service`.
- Scraping pianificato: cron di sistema `/etc/cron.d/linkedin-job-scraper` (utente `dcserver`), ogni giorno alle `13:00` nel fuso del server (`Etc/UTC`, verificato), esegue `/opt/linkedin_job_scraper/run_daily.sh`. Il wrapper usa il lock `data/scraper.lock`, quindi non si sovrappone agli update avviati dalla WebGUI. **Non usare il crontab utente**: fino al 27/08/2026 esisteva una voce duplicata identica nel crontab di `dcserver` (stessa ora, stesso script), rimossa in quella data perche il progetto sta in `/opt` con servizio systemd e va gestito come servizio installato, non come script personale. Il `flock` mascherava la duplicazione, che non produceva danni ma sarebbe diventata due run reali al primo cambio di orario su uno solo dei due. Backup del crontab rimosso in `/home/dcserver/backup/linkedin_job_scraper/`.

## File da consultare per area

| Esigenza | File principali |
|---|---|
| Ruoli, Paesi, tempi, filtri | `config.yaml` |
| Orchestrazione | `main.py` |
| API/parsing/filtri | `scraper/` |
| Schema, deduplica, stato, delete | `storage/database.py` |
| CSV | `storage/exporter.py` |
| Rotte e query WebGUI | `webapp/app.py` |
| Layout/UI | `webapp/templates/`, `webapp/static/style.css` |
| Scheduling | `run_daily.sh`, `/etc/cron.d/linkedin-job-scraper` (unico scheduler) |

## Comandi sicuri di verifica

```bash
cd /opt/linkedin_job_scraper
./venv/bin/python -m py_compile main.py storage/database.py webapp/app.py
./venv/bin/python - <<'PY'
import sqlite3
conn = sqlite3.connect('data/jobs.db')
print(conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
PY
ps -fp "$(cat data/scraper.pid 2>/dev/null)" 2>/dev/null || true
tail -n 100 data/scraper.log
```

## Modalità di lavoro nelle nuove chat

1. Leggere questo file e ispezionare i file realmente interessati.
2. Dichiarare con precisione cosa viene modificato; non inventare stato di deploy/esecuzioni non verificati.
3. Salvare backup datati prima di edit manuali importanti.
4. Verificare almeno compilazione Python o controllo adatto alla modifica.
5. Riassumere file cambiati, verifiche effettuate e limiti/rischi residui.
6. Aggiornare questo file soltanto quando cambiano architettura, regole vincolanti, percorsi o flussi operativi persistenti.
