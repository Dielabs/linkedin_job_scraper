"""
Export dei risultati in CSV e JSON.
"""

import csv
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Campi nell'ordine di esportazione
EXPORT_FIELDS = [
    "job_id", "title", "company", "location", "url",
    "posted_at", "description", "seniority_level",
    "employment_type", "job_function", "industry", "salary",
    "search_keywords", "search_location", "first_seen", "last_seen"
]


def export_csv(jobs, filepath):
    """Esporta una lista di job in CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow(job)

    logger.info("Export CSV: %s (%d righe)", filepath, len(jobs))


def export_json(jobs, filepath):
    """Esporta una lista di job in JSON."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False, default=str)

    logger.info("Export JSON: %s (%d record)", filepath, len(jobs))


def export(jobs, export_dir, prefix="linkedin_jobs", fmt="csv"):
    """
    Esporta in uno o più formati con timestamp nel nome file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    exported = []

    if fmt in ("csv", "both"):
        path = os.path.join(export_dir, f"{prefix}_{timestamp}.csv")
        export_csv(jobs, path)
        exported.append(path)

    if fmt in ("json", "both"):
        path = os.path.join(export_dir, f"{prefix}_{timestamp}.json")
        export_json(jobs, path)
        exported.append(path)

    return exported
