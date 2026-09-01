"""
Parser per i risultati HTML/JSON della Guest API LinkedIn.
Contiene logica di normalizzazione e pulizia dei dati.
"""

import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def clean_text(text):
    """Pulisce testo: rimuove spazi multipli, righe vuote, caratteri speciali."""
    if not text:
        return ""
    # Rimuovi spazi multipli
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_salary(description):
    """
    Cerca di estrarre range salariale dalla descrizione.
    Pattern comuni: €50.000, 50k, 50.000 - 60.000€, CHF 80'000
    """
    if not description:
        return None

    patterns = [
        r'(?:EUR|€)\s?(\d{1,3}(?:[.,]\d{3})*)\s*[-–]\s*(?:EUR|€)?\s?(\d{1,3}(?:[.,]\d{3})*)',
        r'CHF\s?(\d{1,3}(?:[.,\']\d{3})*)\s*[-–]\s*CHF\s?(\d{1,3}(?:[.,\']\d{3})*)',
        r'(\d{1,3})k\s*[-–]\s*(\d{1,3})k',
        r'(\d{2,3}(?:[.,]\d{3})*)\s*[-–]\s*(\d{2,3}(?:[.,]\d{3})*)\s?(?:EUR|€|CHF)',
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return f"{match.group(1)} - {match.group(2)}"

    return None


def normalize_job(raw_job, search_keywords="", search_location=""):
    """
    Normalizza un job grezzo dalla Guest API in un record standardizzato.
    """
    return {
        "job_id": raw_job.get("job_id", ""),
        "title": clean_text(raw_job.get("title", "")),
        "company": clean_text(raw_job.get("company", "")),
        "location": clean_text(raw_job.get("location", "")),
        "url": raw_job.get("url", ""),
        "posted_at": raw_job.get("posted_at", ""),
        "description": clean_text(raw_job.get("description", "")),
        "seniority_level": raw_job.get("seniority_level", ""),
        "employment_type": raw_job.get("employment_type", ""),
        "job_function": raw_job.get("job_function", ""),
        "industry": raw_job.get("industry", ""),
        "salary": raw_job.get("salary") or extract_salary(raw_job.get("description", "")),
        "search_keywords": search_keywords,
        "search_location": search_location,
    }


def merge_search_and_detail(search_job, detail_job):
    """
    Unisce i dati della ricerca (lista) con quelli del dettaglio.
    I dati del dettaglio hanno priorità.
    """
    merged = search_job.copy()
    if detail_job:
        for key, value in detail_job.items():
            if value:  # sovrascrivi solo se il dettaglio ha il valore
                merged[key] = value
    return merged
