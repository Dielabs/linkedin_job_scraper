"""Flask interface for browsing the database and starting a configured full update."""
from __future__ import annotations

import math
import os
import sqlite3
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, flash, redirect, render_template, request, url_for

from webapp.matching import score_job

# The DB path is anchored to the project root, independently of cwd/process manager.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "jobs.db"
PER_PAGE = 20
MAX_PER_PAGE = 100
SCRAPER_PID_PATH = PROJECT_ROOT / "data" / "scraper.pid"
SCRAPER_LOCK_PATH = PROJECT_ROOT / "data" / "scraper.lock"
RUNNER_PATH = PROJECT_ROOT / "run_daily.sh"
ORDERING = {
    "last_seen": "last_seen DESC, title COLLATE NOCASE ASC",
    "first_seen": "first_seen DESC, title COLLATE NOCASE ASC",
    "posted_at": "posted_at DESC, last_seen DESC, title COLLATE NOCASE ASC",
    "title": "title COLLATE NOCASE ASC, last_seen DESC",
    "company": "company COLLATE NOCASE ASC, last_seen DESC",
    # Match is sorted in Python after score calculation.
    "match": "last_seen DESC, title COLLATE NOCASE ASC",
    "status": "is_new DESC, last_seen DESC, title COLLATE NOCASE ASC",
}

app = Flask(__name__)
app.config["DATABASE_PATH"] = str(DATABASE_PATH)
app.config["SECRET_KEY"] = os.environ.get("WEBAPP_SECRET_KEY", "local-job-scraper-update")


def lock_is_held() -> bool:
    """Return whether cron or the WebGUI currently owns the shared scraper lock."""
    result = subprocess.run(
        ["/usr/bin/flock", "-n", str(SCRAPER_LOCK_PATH), "/usr/bin/true"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode != 0


def scraper_running() -> bool:
    """Return whether a scraper run is active, regardless of who started it."""
    try:
        pid = int(SCRAPER_PID_PATH.read_text().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        SCRAPER_PID_PATH.unlink(missing_ok=True)
        return lock_is_held()


@app.post("/update")
def update():
    """Start the common lock-protected runner in background, if the lock is free."""
    if scraper_running():
        flash("Aggiornamento già in corso: attendi il completamento prima di avviarne un altro.", "warning")
        return redirect(request.referrer or url_for("index"))

    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(RUNNER_PATH)], cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    SCRAPER_PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    flash("Aggiornamento completo avviato in background.", "success")
    return redirect(request.referrer or url_for("index"))


def get_connection() -> sqlite3.Connection:
    """Open a short-lived, read-only-friendly SQLite connection."""
    conn = sqlite3.connect(app.config["DATABASE_PATH"], timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def split_keywords(value: str) -> list[str]:
    """Parse comma-separated filter terms, ignoring duplicates/empty entries."""
    seen = set()
    result = []
    for item in value.split(","):
        item = item.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def valid_date(value: str) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""



def is_valid_linkedin_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (hostname == "linkedin.com" or hostname.endswith(".linkedin.com"))


def job_key_from_form() -> tuple[str, str, str] | None:
    """Return a complete logical job key submitted by a save/remove form."""
    key = tuple(request.form.get(field, "").strip() for field in ("job_id", "search_keywords", "search_location"))
    return key if all(key) else None


@app.post("/saved")
def save_job():
    key = job_key_from_form()
    if key is None:
        flash("Impossibile salvare l'annuncio: identificativo non valido.", "danger")
    else:
        try:
            with get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET is_saved = 1 WHERE job_id = ? AND search_keywords = ? AND search_location = ?", key
                )
                conn.commit()
            flash("Annuncio salvato.", "success" if cursor.rowcount else "warning")
        except sqlite3.Error as exc:
            flash(f"Impossibile salvare l'annuncio: {exc}", "danger")
    return redirect(request.form.get("next") or url_for("index"))


@app.post("/saved/remove")
def remove_saved_job():
    key = job_key_from_form()
    if key is None:
        flash("Impossibile rimuovere il salvataggio: identificativo non valido.", "danger")
    else:
        try:
            with get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET is_saved = 0 WHERE job_id = ? AND search_keywords = ? AND search_location = ?", key
                )
                conn.commit()
            flash("Annuncio rimosso dai lavori salvati.", "success" if cursor.rowcount else "warning")
        except sqlite3.Error as exc:
            flash(f"Impossibile rimuovere il salvataggio: {exc}", "danger")
    return redirect(request.form.get("next") or url_for("saved_jobs"))



def db_where(filters: dict) -> tuple[str, list[str]]:
    clauses, params = [], []
    if filters["q"]:
        term = f"%{filters['q']}%"
        clauses.append("(title LIKE ? COLLATE NOCASE OR company LIKE ? COLLATE NOCASE)")
        params.extend([term, term])
    # Include means any term in title; exclude removes any title matching a term.
    if filters["include_keywords"]:
        clauses.append("(" + " OR ".join("title LIKE ? COLLATE NOCASE" for _ in filters["include_keywords"]) + ")")
        params.extend(f"%{term}%" for term in filters["include_keywords"])
    if filters["exclude_keywords"]:
        clauses.append("NOT (" + " OR ".join("title LIKE ? COLLATE NOCASE" for _ in filters["exclude_keywords"]) + ")")
        params.extend(f"%{term}%" for term in filters["exclude_keywords"])
    if filters["role"]:
        clauses.append("search_keywords = ?")
        params.append(filters["role"])
    if filters["country"]:
        clauses.append("search_location = ?")
        params.append(filters["country"])
    if filters["status"] == "new":
        clauses.append("is_new = 1")
    date_column = {"first_seen": "first_seen", "last_seen": "last_seen", "posted_at": "posted_at"}[filters["date_field"]]
    if filters["date_from"]:
        clauses.append(f"substr(COALESCE({date_column}, ''), 1, 10) >= ?")
        params.append(filters["date_from"])
    if filters["date_to"]:
        clauses.append(f"substr(COALESCE({date_column}, ''), 1, 10) <= ?")
        params.append(filters["date_to"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def build_filters() -> dict:
    date_field = request.args.get("date_field", "first_seen")
    return {
        "q": request.args.get("q", "").strip(),
        "include_raw": request.args.get("include", "").strip(),
        "exclude_raw": request.args.get("exclude", "").strip(),
        "include_keywords": split_keywords(request.args.get("include", "")),
        "exclude_keywords": split_keywords(request.args.get("exclude", "")),
        "role": request.args.get("role", "").strip(),
        "country": request.args.get("country", "").strip() if request.args.get("country", "") in {"Italy", "Switzerland", "Luxembourg"} else "",
        "status": request.args.get("status", "all") if request.args.get("status", "all") in {"all", "new"} else "all",
        "date_field": date_field if date_field in {"first_seen", "last_seen", "posted_at"} else "first_seen",
        "date_from": valid_date(request.args.get("date_from", "")),
        "date_to": valid_date(request.args.get("date_to", "")),
        "sort": request.args.get("sort", "last_seen") if request.args.get("sort", "last_seen") in ORDERING else "last_seen",
        "min_score": min(max(request.args.get("min_score", 0, type=int), 0), 100),
    }


@app.template_filter("display_date")
def display_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return date.fromisoformat(value[:10]).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return value


@app.route("/")
def index():
    filters = build_filters()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", PER_PAGE, type=int), 10), MAX_PER_PAGE)
    where, params = db_where(filters)

    try:
        with get_connection() as conn:
            total_db = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            new_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_new = 1").fetchone()[0]
            roles = [row[0] for row in conn.execute("SELECT DISTINCT search_keywords FROM jobs WHERE search_keywords <> '' ORDER BY search_keywords COLLATE NOCASE")]
            rows = conn.execute(f"SELECT * FROM jobs{where} ORDER BY {ORDERING[filters['sort']]}", params).fetchall()
    except sqlite3.Error as exc:
        return render_template("error.html", error=str(exc), database_path=app.config["DATABASE_PATH"]), 500

    jobs = []
    for row in rows:
        job = dict(row)
        job["is_new"] = bool(job["is_new"])
        job["match_score"], job["match_areas"] = score_job(job)
        job["valid_url"] = is_valid_linkedin_url(job.get("url"))
        jobs.append(job)
    if filters["min_score"]:
        jobs = [job for job in jobs if job["match_score"] >= filters["min_score"]]
    if filters["sort"] == "match":
        jobs.sort(key=lambda job: (job["match_score"], job.get("last_seen") or ""), reverse=True)

    filtered_total = len(jobs)
    countries = Counter(job.get("search_location") or "Altro" for job in jobs)
    total_pages = max(1, math.ceil(filtered_total / per_page))
    page = min(page, total_pages)
    page_jobs = jobs[(page - 1) * per_page: page * per_page]

    query_args = request.args.to_dict(flat=False)
    query_args.pop("page", None)
    def page_url(target_page: int) -> str:
        args = {key: list(values) for key, values in query_args.items()}
        args["page"] = target_page
        return url_for("index", **args)

    return render_template("index.html", jobs=page_jobs, filters=filters, roles=roles,
        total_db=total_db, filtered_total=filtered_total, countries=countries,
        page=page, per_page=per_page, total_pages=total_pages, page_url=page_url,
        database_path=app.config["DATABASE_PATH"], scraper_running=scraper_running(),
        new_total=new_count)


@app.route("/saved")
def saved_jobs():
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE is_saved = 1 ORDER BY last_seen DESC, title COLLATE NOCASE ASC").fetchall()
    except sqlite3.Error as exc:
        return render_template("error.html", error=str(exc), database_path=app.config["DATABASE_PATH"]), 500

    jobs = []
    for row in rows:
        job = dict(row)
        job["is_new"] = bool(job["is_new"])
        job["match_score"], job["match_areas"] = score_job(job)
        job["valid_url"] = is_valid_linkedin_url(job.get("url"))
        jobs.append(job)
    return render_template("saved_jobs.html", jobs=jobs, saved_total=len(jobs), scraper_running=scraper_running())


if __name__ == "__main__":
    # Development/testing only. Use a production WSGI server before external exposure.
    app.run(host=os.environ.get("WEBAPP_HOST", "127.0.0.1"), port=int(os.environ.get("WEBAPP_PORT", "5000")), debug=False)
