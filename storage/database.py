"""Gestione database SQLite, deduplicazione e ciclo di vita degli annunci."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    url TEXT,
    posted_at TEXT,
    description TEXT,
    seniority_level TEXT,
    employment_type TEXT,
    job_function TEXT,
    industry TEXT,
    salary TEXT,
    search_keywords TEXT,
    search_location TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_new INTEGER NOT NULL DEFAULT 1,
    missing_runs INTEGER NOT NULL DEFAULT 0,
    is_saved INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, search_keywords, search_location)
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at);
"""

# Migration for databases created before availability/new-state tracking existed.
MIGRATION_COLUMNS = {
    "is_active": "INTEGER NOT NULL DEFAULT 1",
    "is_new": "INTEGER NOT NULL DEFAULT 0",
    "missing_runs": "INTEGER NOT NULL DEFAULT 0",
    "is_saved": "INTEGER NOT NULL DEFAULT 0",
}


class JobDatabase:
    """Wrapper SQLite per persistenza, dedup e ciclo di vita dei job posting."""

    def __init__(self, db_path="data/jobs.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(SCHEMA)
            existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            for column, definition in MIGRATION_COLUMNS.items():
                if column not in existing_columns:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(is_active, is_new, last_seen)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_saved ON jobs(is_saved, last_seen)")
        logger.info("Database inizializzato: %s", self.db_path)

    @staticmethod
    def _params(job, now):
        return {
            "job_id": job.get("job_id", ""), "title": job.get("title", ""),
            "company": job.get("company", ""), "location": job.get("location", ""),
            "url": job.get("url", ""), "posted_at": job.get("posted_at", ""),
            "description": job.get("description", ""),
            "seniority_level": job.get("seniority_level", ""),
            "employment_type": job.get("employment_type", ""),
            "job_function": job.get("job_function", ""), "industry": job.get("industry", ""),
            "salary": job.get("salary", ""),
            "search_keywords": job.get("search_keywords", ""),
            "search_location": job.get("search_location", ""),
            "first_seen": now, "last_seen": now,
        }

    def upsert_jobs(self, jobs):
        """Salva una lista; nuovi record ricevono il tag ``is_new``, gli altri lo perdono."""
        if not jobs:
            return 0, 0
        now = datetime.utcnow().isoformat()
        new_count = updated_count = 0
        sql = """
            INSERT INTO jobs (
                job_id, title, company, location, url, posted_at, description,
                seniority_level, employment_type, job_function, industry, salary,
                search_keywords, search_location, first_seen, last_seen,
                is_active, is_new, missing_runs
            ) VALUES (
                :job_id, :title, :company, :location, :url, :posted_at, :description,
                :seniority_level, :employment_type, :job_function, :industry, :salary,
                :search_keywords, :search_location, :first_seen, :last_seen, 1, 1, 0
            ) ON CONFLICT(job_id, search_keywords, search_location) DO UPDATE SET
                last_seen = excluded.last_seen, title = excluded.title, company = excluded.company,
                location = excluded.location, url = excluded.url, posted_at = excluded.posted_at,
                description = excluded.description, salary = excluded.salary,
                seniority_level = excluded.seniority_level, employment_type = excluded.employment_type,
                job_function = excluded.job_function, industry = excluded.industry,
                is_active = 1, is_new = 0, missing_runs = 0
        """
        with self._get_conn() as conn:
            for job in jobs:
                key = (job.get("job_id", ""), job.get("search_keywords", ""), job.get("search_location", ""))
                exists = conn.execute(
                    "SELECT 1 FROM jobs WHERE job_id = ? AND search_keywords = ? AND search_location = ?", key
                ).fetchone() is not None
                conn.execute(sql, self._params(job, now))
                if exists:
                    updated_count += 1
                else:
                    new_count += 1
        logger.info("DB: %d nuovi, %d aggiornati", new_count, updated_count)
        return new_count, updated_count

    def reconcile_search_scope(self, search_keywords, search_location, seen_job_ids, confirmation_runs=2):
        """Elimina gli annunci assenti dopo N ricerche valide consecutive nello scope.

        Non va chiamato quando la ricerca fallisce o restituisce zero card: in quei casi
        l'assenza non e' una prova affidabile che l'annuncio sia stato rimosso.
        """
        if not seen_job_ids:
            logger.info("Riconciliazione %r/%r saltata: nessun risultato affidabile", search_keywords, search_location)
            return 0
        confirmation_runs = max(int(confirmation_runs), 1)
        placeholders = ", ".join("?" for _ in seen_job_ids)
        base = [search_keywords, search_location, *seen_job_ids]
        missing_where = (
            "search_keywords = ? AND search_location = ? "
            f"AND job_id NOT IN ({placeholders})"
        )
        with self._get_conn() as conn:
            conn.execute(f"UPDATE jobs SET missing_runs = missing_runs + 1 WHERE {missing_where}", base)
            cursor = conn.execute(
                f"DELETE FROM jobs WHERE {missing_where} AND missing_runs >= ?",
                [*base, confirmation_runs],
            )
            deleted = cursor.rowcount
        if deleted:
            logger.info("Eliminati %d annunci non piu' presenti per %r/%r", deleted, search_keywords, search_location)
        return deleted

    def get_all_jobs(self, limit=None):
        """Recupera tutti i job per lo snapshot corrente."""
        with self._get_conn() as conn:
            query = "SELECT * FROM jobs ORDER BY last_seen DESC"
            if limit:
                query += " LIMIT ?"
                rows = conn.execute(query, (limit,)).fetchall()
            else:
                rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_new_jobs(self, since_date):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE first_seen >= ? ORDER BY first_seen DESC", (since_date,)).fetchall()
            return [dict(r) for r in rows]

    def get_job(self, job_id, search_keywords, search_location):
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ? AND search_keywords = ? AND search_location = ?", (job_id, search_keywords, search_location)).fetchone()
            return dict(row) if row else None

    def get_stats(self):
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            by_location = conn.execute("SELECT search_location, COUNT(*) AS count FROM jobs GROUP BY search_location ORDER BY count DESC").fetchall()
            by_keyword = conn.execute("SELECT search_keywords, COUNT(*) AS count FROM jobs GROUP BY search_keywords ORDER BY count DESC").fetchall()
            by_company = conn.execute("SELECT company, COUNT(*) AS count FROM jobs GROUP BY company ORDER BY count DESC LIMIT 10").fetchall()
            return {"total_jobs": total, "by_location": [dict(r) for r in by_location], "by_keyword": [dict(r) for r in by_keyword], "top_companies": [dict(r) for r in by_company]}
