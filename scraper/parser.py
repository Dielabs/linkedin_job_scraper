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



# Alias città → regione per validare la coerenza tra query di ricerca e
# location reale restituita da LinkedIn (che può restituire risultati fuori area).
_REGION_CITY_ALIASES = {
    "piedmont":           ["turin", "torino"],
    "lombardy":           ["milan", "milano"],
    "latium":             ["rome", "roma"],
    "tuscany":            ["florence", "firenze", "pisa", "empoli", "livorno"],
    "emilia-romagna":     ["bologna", "modena", "rimini", "parma", "reggio"],
    "veneto":             ["venice", "venezia", "verona", "vicenza", "padua", "padova", "rubano"],
    "apulia":             ["bari", "taranto", "lecce", "brindisi"],
    "campania":           ["naples", "napoli", "salerno"],
    "abruzzi":            ["pescara", "l'aquila", "chieti"],
    "friuli-venezia giulia": ["udine", "trieste", "gorizia"],
    "trentino-alto adige": ["trento", "bolzano", "merano"],
    "liguria":            ["genoa", "genova", "savona", "la spezia"],
    "piemonte":           ["turin", "torino", "novara", "alessandria"],
    "sicily":             ["palermo", "catania", "messina", "siracusa"],
    "sardinia":           ["cagliari", "sassari", "olbia"],
    "calabria":           ["reggio calabria", "catanzaro", "cosenza"],
    "marche":             ["ancona", "pesaro", "urbino"],
    "umbria":             ["perugia", "terni"],
    "basilicata":         ["potenza", "matera"],
    "molise":             ["campobasso", "isernia"],
    "aosta valley":       ["aosta"],
    "romande":            ["lausanne", "geneva", "genève", "vevey", "montreux", "sion", "nyon", "morges"],
    "zurich":             ["zurich", "zürich"],
    " Ticino":            ["lugano", "bellinzona", "locarno"],
}


def validate_search_location(search_location, job_location):
    """Verifica che la *search_location* (query di ricerca) sia coerente con la
    *job_location* (posizione reale restituita da LinkedIn).

    LinkedIn Guest API ha un matching geografico ampio: una query
    ``"Piedmont, Italy"`` può restituire annunci a Milano o Roma.
    Se la regione della query non compare nella location reale (né come
    regione né come città alias), si fa fallback al paese generico.

    Esempi::

        validate_search_location("Piedmont, Italy", "Milan, Lombardy, Italy")  → "Italy"
        validate_search_location("Piedmont, Italy", "Turin, Piedmont, Italy")  → "Piedmont, Italy"
        validate_search_location("Piedmont, Italy", "Greater Turin Metropolitan Area") → "Piedmont, Italy"
        validate_search_location("Italy", "Milan, Lombardy, Italy")            → "Italy"
        validate_search_location("Remote, Italy", "Italy")                     → "Remote, Italy"
    """
    if not search_location:
        return search_location

    parts = [p.strip() for p in search_location.split(",")]
    # Paese generico (es. "Italy", "Switzerland"): sempre compatibile
    if len(parts) <= 1:
        return search_location

    region = parts[0]
    country = parts[-1]

    # "Remote" è sempre compatibile
    if region.lower() == "remote":
        return search_location

    # Se la regione compare nella location reale, compatibile
    if job_location and region.lower() in job_location.lower():
        return search_location

    # Alias: città principali di quella regione
    aliases = _REGION_CITY_ALIASES.get(region.lower(), [])
    if job_location and any(alias in job_location.lower() for alias in aliases):
        return search_location

    # Non compatibile: fallback al paese generico
    return country


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
        "search_location": validate_search_location(search_location, clean_text(raw_job.get("location", ""))),
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
