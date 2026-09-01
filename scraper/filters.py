"""Filtri post-scraping per raffinare i risultati."""

import logging

logger = logging.getLogger(__name__)


def filter_by_keywords(jobs, include_keywords=None, exclude_keywords=None):
    """Filtra job per parole chiave nel titolo (include in OR)."""
    filtered = list(jobs)

    if include_keywords:
        filtered = [
            job for job in filtered
            if any(kw.lower() in job.get("title", "").lower() for kw in include_keywords)
        ]

    if exclude_keywords:
        filtered = [
            job for job in filtered
            if not any(kw.lower() in job.get("title", "").lower() for kw in exclude_keywords)
        ]

    logger.info("Filtro keyword: %d -> %d job", len(jobs), len(filtered))
    return filtered



def deduplicate(jobs):
    """Rimuove duplicati basati su job_id."""
    seen = set()
    unique = []
    for job in jobs:
        jid = job.get("job_id", "")
        if jid and jid not in seen:
            seen.add(jid)
            unique.append(job)
        elif not jid:
            unique.append(job)

    logger.info("Dedup: %d -> %d job", len(jobs), len(unique))
    return unique
