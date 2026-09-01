#!/usr/bin/env python3
"""
LinkedIn Job Scraper - Entry point principale.
Orchestrizza: Guest API → Parser → Filtri → SQLite → Export CSV/JSON
"""

import logging
import sys
import os
from datetime import datetime

import yaml

from scraper.guest_api import LinkedInGuestAPI
from scraper.parser import normalize_job, merge_search_and_detail
from scraper.filters import filter_by_keywords, deduplicate
from storage.database import JobDatabase
from storage.exporter import export

logger = logging.getLogger("linkedin_scraper")


def setup_logging(config: dict) -> logging.Logger:
    """Configura logging su file e console."""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "scraper.log")

    os.makedirs(os.path.dirname(log_file), exist_ok=True) if log_file else None

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file) if log_file else logging.NullHandler(),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("linkedin_scraper")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def run_scraper(config: dict):
    """Esegue il ciclo completo di scraping per ogni combinazione keyword×location."""
    scrape_cfg = config.get("scraping", {})
    db_cfg = config.get("database", {})
    export_cfg = config.get("export", {})

    # Inizializza componenti
    api = LinkedInGuestAPI(
        delay_min=scrape_cfg.get("delay_min_seconds", 2),
        delay_max=scrape_cfg.get("delay_max_seconds", 5),
        max_retries=scrape_cfg.get("max_retries", 3),
        retry_delay=scrape_cfg.get("retry_delay_seconds", 30),
    )
    db_path = db_cfg.get("path", "data/jobs.db")
    db_directory = os.path.dirname(db_path)
    if db_directory:
        os.makedirs(db_directory, exist_ok=True)
    db = JobDatabase(db_path=db_path)

    max_results = scrape_cfg.get("results_per_query", 50)
    searches = config.get("searches", [])

    fetch_details = scrape_cfg.get("fetch_details", False)
    filters_cfg = config.get("filters", {})
    total_new = 0
    total_updated = 0
    total_deleted = 0
    absence_confirmation_runs = scrape_cfg.get("absence_confirmation_runs", 2)

    for search in searches:
        keywords = search.get("keywords", "")
        locations = search.get("locations", [])

        for location in locations:
            logger.info("=== Ricerca: '%s' in '%s' ===", keywords, location)

            try:
                # 1. Scraping lista risultati (con paginazione)
                raw_jobs = api.search_all(keywords, location, max_results=max_results)
                logger.info("Ottenuti %d risultati grezzi", len(raw_jobs))
                # Gli ID grezzi, prima dei filtri, sono la fonte per la riconciliazione.
                # Una ricerca senza card non elimina nulla: puo' essere un errore temporaneo/API.
                seen_job_ids = {str(job.get("job_id", "")) for job in raw_jobs if job.get("job_id")}

                if not raw_jobs:
                    logger.info("Nessun risultato, salto")
                    continue

                # 2. Dettaglio opzionale: aumenta qualità dei dati, ma richiede una
                # richiesta aggiuntiva per annuncio. Disabilitato di default.
                if fetch_details:
                    enriched_jobs = []
                    for job in raw_jobs:
                        try:
                            detail = api.get_job_detail(job["job_id"])
                            enriched_jobs.append(merge_search_and_detail(job, detail))
                        except Exception as exc:
                            logger.warning("Dettaglio non disponibile per job %s: %s", job.get("job_id"), exc)
                            enriched_jobs.append(job)
                    raw_jobs = enriched_jobs

                # 3. Normalizzazione e filtri configurabili
                parsed_jobs = [
                    normalize_job(job, search_keywords=keywords, search_location=location)
                    for job in raw_jobs
                ]
                logger.info("Normalizzati %d annunci", len(parsed_jobs))

                filtered = filter_by_keywords(
                    parsed_jobs,
                    include_keywords=filters_cfg.get("include_keywords"),
                    exclude_keywords=filters_cfg.get("exclude_keywords"),
                )
                filtered = deduplicate(filtered)

                # 4. Dedup e salvataggio in DB
                logger.info("Dopo dedup: %d annunci", len(filtered))

                new_count, updated_count = db.upsert_jobs(filtered)
                total_new += new_count
                total_updated += updated_count
                deleted_count = db.reconcile_search_scope(
                    keywords, location, seen_job_ids, confirmation_runs=absence_confirmation_runs
                )
                total_deleted += deleted_count
                logger.info("DB: %d nuovi, %d aggiornati, %d eliminati", new_count, updated_count, deleted_count)

            except Exception as e:
                logger.error("Errore su '%s'/'%s': %s", keywords, location, e, exc_info=True)

    # Snapshot unico del database al termine del run, anziché un file per query.
    all_jobs = db.get_all_jobs()
    if all_jobs:
        export(
            jobs=all_jobs,
            export_dir=export_cfg.get("path", "data/exports"),
            prefix=export_cfg.get("filename_prefix", "linkedin_jobs"),
            fmt=export_cfg.get("format", "csv"),
        )
        logger.info("Export snapshot completato: %d record", len(all_jobs))
    else:
        logger.info("Database vuoto: nessun export generato")

    logger.info("=== Run completata: %d nuovi, %d aggiornati, %d eliminati ===", total_new, total_updated, total_deleted)
    return total_new, total_updated, total_deleted


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)
    setup_logging(config)
    logger.info("=== LinkedIn Job Scraper avviato - %s ===", datetime.now())
    run_scraper(config)


if __name__ == "__main__":
    main()
