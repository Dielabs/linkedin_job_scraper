"""
Wrapper per la LinkedIn Guest API pubblica.
Non richiede login né cookie di sessione.
"""

import time
import random
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Endpoint pubblici LinkedIn (no auth required)
BASE_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
BASE_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# Headers che simulano un browser reale
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class GuestAPIError(Exception):
    """Errore generico della Guest API."""
    pass


class RateLimitError(GuestAPIError):
    """HTTP 429 - rate limit raggiunto."""
    pass


class LinkedInGuestAPI:
    """Client per la LinkedIn Guest API pubblica."""

    def __init__(self, delay_min=2, delay_max=5, max_retries=3, retry_delay=30):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _sleep(self):
        """Delay randomico tra richieste per evitare rate limit."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    def _request_with_retry(self, url, params=None):
        """Esegue una richiesta HTTP con retry su 429/503."""
        for attempt in range(1, self.max_retries + 1):
            try:
                self._sleep()
                resp = self.session.get(url, params=params, timeout=30)

                if resp.status_code == 200:
                    return resp

                if resp.status_code == 429:
                    logger.warning("Rate limit (429) - tentativo %d/%d - attesa %ds",
                                   attempt, self.max_retries, self.retry_delay)
                    time.sleep(self.retry_delay)
                    continue

                if resp.status_code in (503, 502):
                    logger.warning("Server error %d - tentativo %d/%d",
                                   resp.status_code, attempt, self.max_retries)
                    time.sleep(self.retry_delay)
                    continue

                # Altri errori: non ritentare
                logger.error("HTTP %d su %s", resp.status_code, url)
                return resp

            except requests.RequestException as e:
                logger.warning("Errore di rete (tentativo %d/%d): %s", attempt, self.max_retries, e)
                time.sleep(self.retry_delay)

        raise RateLimitError(f"Rate limit dopo {self.max_retries} tentativi su {url}")

    def search_jobs(self, keywords, location, start=0):
        """
        Cerca job postings tramite Guest API.
        Ritorna una lista di dizionari con i dati grezzi di ogni job.
        """
        params = {
            "keywords": keywords,
            "location": location,
            "start": start,
        }

        logger.info("Ricerca: keywords='%s' location='%s' start=%d", keywords, location, start)
        resp = self._request_with_retry(BASE_SEARCH_URL, params=params)

        soup = BeautifulSoup(resp.text, "lxml")
        job_cards = soup.find_all("li")

        jobs = []
        for card in job_cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        logger.info("Trovati %d risultati (page start=%d)", len(jobs), start)
        return jobs

    def search_all(self, keywords, location, max_results=50):
        """
        Cerca job postings con paginazione automatica fino a max_results.
        """
        all_jobs = []
        start = 0

        while len(all_jobs) < max_results:
            jobs = self.search_jobs(keywords, location, start=start)

            if not jobs:
                logger.info("Nessun altro risultato - stop paginazione")
                break

            all_jobs.extend(jobs)

            if len(jobs) < 25:
                # Meno di 25 risultati = ultima pagina
                logger.info("Ultima pagina raggiunta (%d risultati)", len(jobs))
                break

            start += 25

        # Tronca a max_results se necessario
        if len(all_jobs) > max_results:
            all_jobs = all_jobs[:max_results]

        logger.info("Totale raccolto: %d job per '%s' in '%s'",
                     len(all_jobs), keywords, location)
        return all_jobs

    def get_job_detail(self, job_id):
        """
        Recupera il dettaglio completo di un singolo job posting.
        """
        url = BASE_DETAIL_URL.format(job_id=job_id)
        resp = self._request_with_retry(url)

        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse_job_detail(soup, job_id)

    def _parse_job_card(self, card):
        """Estrae i dati base da una card job nella lista di ricerca."""
        try:
            # Job ID dal link
            link = card.find("a", class_="base-card__full-link")
            if not link:
                # Fallback: qualsiasi link con /jobs/view/
                link = card.find("a", href=True)
                if not link or "/jobs/view/" not in link.get("href", ""):
                    return None

            href = link.get("href", "")
            # Estrai job ID dall'URL (es. /jobs/view/python-developer-at-xxx-1234567890/?...)
            job_id = href.split("/jobs/view/")[1].split("/")[0].split("-")[-1].split("?")[0]

            title_elem = card.find("span", class_="sr-only")
            if not title_elem:
                title_elem = link

            title = title_elem.get_text(strip=True) if title_elem else "N/A"

            company_elem = card.find("a", class_="hidden-nested-link")
            if not company_elem:
                company_elem = card.find("h4", class_="base-search-card__subtitle")
            company = company_elem.get_text(strip=True) if company_elem else "N/A"

            location_elem = card.find("span", class_="job-search-card__location")
            if not location_elem:
                location_elem = card.find("span", class_="job-search-card__subtitle")
            job_location = location_elem.get_text(strip=True) if location_elem else "N/A"

            # Data pubblicazione
            time_elem = card.find("time", class_="job-search-card__listdate")
            posted_at = time_elem.get("datetime", "") if time_elem else ""

            return {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": job_location,
                "url": href.split("?")[0],
                "posted_at": posted_at,
            }
        except Exception as e:
            logger.debug("Errore parsing card: %s", e)
            return None

    def _parse_job_detail(self, soup, job_id):
        """Estrae i dettagli completi da una pagina di dettaglio job."""
        detail = {"job_id": job_id}

        # Titolo
        title_elem = soup.find("h1", class_="top-card-layout__title")
        if title_elem:
            detail["title"] = title_elem.get_text(strip=True)

        # Azienda
        company_elem = soup.find("a", class_="topcard__org-name-link")
        if not company_elem:
            company_elem = soup.find("span", class_="topcard__flavor")
        if company_elem:
            detail["company"] = company_elem.get_text(strip=True)

        # Location
        location_elem = soup.find("span", class_="topcard__flavor--bullet")
        if location_elem:
            detail["location"] = location_elem.get_text(strip=True)

        # Descrizione
        desc_elem = soup.find("div", class_="description__text")
        if not desc_elem:
            desc_elem = soup.find("div", class_="show-more-less-html__markup")
        if desc_elem:
            detail["description"] = desc_elem.get_text(separator="\n", strip=True)
        else:
            detail["description"] = ""

        # Tipo di impiego (se presente)
        criteria = soup.find_all("li", class_="description__job-criteria-item")
        for item in criteria:
            label_elem = item.find("h3", class_="description__job-criteria-subheader")
            value_elem = item.find("span", class_="description__job-criteria-text")
            if label_elem and value_elem:
                label = label_elem.get_text(strip=True).lower()
                value = value_elem.get_text(strip=True)
                if "level" in label:
                    detail["seniority_level"] = value
                elif "employment type" in label:
                    detail["employment_type"] = value
                elif "function" in label:
                    detail["job_function"] = value
                elif "industry" in label:
                    detail["industry"] = value

        return detail
