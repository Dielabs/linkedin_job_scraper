"""Deterministic CV-to-job proximity scoring for the read-only UI.

The score is an indication of technical/role overlap, not an application decision.
"""
from __future__ import annotations

import re
import unicodedata

# Derived from Diego Bardella's CV: AI inference/LLM serving, datacenter and
# hybrid cloud architecture, technical presales, infrastructure operations and
# IT leadership.  Category weights deliberately add up to 100.
# A job requiring Azure or AWS receives one 40% reduction, even if both
# platforms are mentioned.  The check is context-aware: mentions in the
# title always count, and mentions in the body only count when they
# appear in a sentence that is NOT boilerplate (company description,
# benefits, partner ecosystem, certification programmes, etc.).
UNSUPPORTED_CLOUD_TERMS = ("azure", "aws")
UNSUPPORTED_CLOUD_SCORE_FACTOR = 0.60

# Boilerplate context markers: when azure/aws appears in the same sentence
# chunk as one of these substrings, the mention is about company
# partnerships, certification ecosystems, benefits, or corporate
# boilerplate — not a hard job requirement.  The cloud penalty is skipped
# for such mentions.
_BOILERPLATE_MARKERS = (
    "partner", "partnership",
    "certif",
    "ecosystem",
    "campus",
    "recogni",
    "inclusive", "divers",
    "sustainab",
    "communit",
    "career path", "development path", "professional development",
    "apply now", "show more", "show less",
    "technology provider", "leading technology",
    "global ecosystem",
    "collective labour", "ccnl",
    "about us", "about the company", "about the group",
    "we are committed", "equal opportunity",
    "gender-neutral", "pay transparency",
    "salary", "ral", "compensation", "remuneration",
    "contract type", "permanent employment",
    "legislative decree", "protected categori",
    "personal data", "eu regulation",
    "flexible work", "work-life balance", "remote work",
    "social responsibility",
    "what youll love", "what we offer", "working here",
    "benefit", "values", "mission", "culture",
)

PROFILE_AREAS = (
    ("AI / LLM inference", 30, (
        "llm", "inference", "vllm", "llm serving", "generative ai", "genai",
        "gpu", "cuda", "nvidia", "machine learning infrastructure", "ai infrastructure",
        "prometheus", "grafana", "observability", "benchmark",
    )),
    ("Datacenter e cloud ibrido", 25, (
        "datacenter", "data center", "private cloud", "hybrid cloud", "neocloud",
        "vmware", "vsphere", "vcf", "nutanix", "storage", "netapp", "veeam",
        "virtualization", "virtualisation", "backup", "disaster recovery", "rpo", "rto",
    )),
    ("Architettura e presales", 20, (
        "solutions architect", "solution architect", "technical presales", "presales",
        "pre-sales", "rfp", "rfi", "rfq", "sizing", "capacity planning", "architect",
    )),
    ("Infrastructure / platform engineering", 15, (
        "devops", "docker", "kubernetes", "linux", "network", "nsx", "automation",
        "system engineer", "infrastructure engineer", "platform engineer",
    )),
    ("Responsabilità IT", 10, (
        "it manager", "responsabile it", "head of it", "it director", "it operations manager",
        "service delivery manager", "team lead", "leadership",
    )),
)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").casefold()


def has_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) is not None


def _has_marker(text: str, marker: str) -> bool:
    """Check if *marker* appears as a standalone word or word prefix.

    Unlike plain substring matching this respects word boundaries, so
    ``"ral"`` does not match inside ``"infrastrutturale"``.
    """
    return re.search(r"(?<!\w)" + re.escape(marker) + r"\w*", text) is not None


# Characters of context examined around each Azure/AWS occurrence.
_CLOUD_CONTEXT_WINDOW = 80


def _cloud_is_requirement(desc_norm: str) -> bool:
    """Return True if Azure or AWS is mentioned outside boilerplate context.

    For each occurrence of a cloud term in the description, the preceding
    _CLOUD_CONTEXT_WINDOW characters are examined (pure look-behind, so
    that section headers such as "what we offer" appearing after the
    mention do not cause false boilerplate detection).  If the window
    contains any boilerplate marker (partner, certification, ecosystem,
    ...) the occurrence is treated as boilerplate and skipped.  Only
    occurrences with no nearby boilerplate marker trigger the penalty.
    Title mentions are always significant and checked by the caller.
    """
    for term in UNSUPPORTED_CLOUD_TERMS:
        for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", desc_norm):
            start = max(0, m.start() - _CLOUD_CONTEXT_WINDOW)
            window = desc_norm[start:m.start()]
            if not any(_has_marker(window, marker) for marker in _BOILERPLATE_MARKERS):
                return True
    return False


def score_job(job: dict) -> tuple[int, list[str]]:
    """Return a 0–100 score and matched profile-area labels.

    An area earns its weight when one or more relevant terms occur in the
    title, description, or source query. Title hits receive a modest bonus,
    then the result is capped at 100.  Junior/intern jobs are penalised.
    """
    title = normalize(str(job.get("title") or ""))
    body = normalize(" ".join(str(job.get(key) or "") for key in ("description", "search_keywords", "job_function")))
    total, matched = 0, []
    for label, weight, terms in PROFILE_AREAS:
        body_hit = any(has_term(body, term) for term in terms)
        title_hit = any(has_term(title, term) for term in terms)
        if body_hit or title_hit:
            total += weight
            matched.append(label)
            if title_hit:
                total += 2
    if any(term in title for term in ("junior", "intern", "stage", "apprentice", "graduate")):
        total -= 15
    total = max(0, min(100, total))
    desc_norm = normalize(str(job.get("description") or ""))
    cloud_in_title = any(has_term(title, term) for term in UNSUPPORTED_CLOUD_TERMS)
    cloud_in_body = _cloud_is_requirement(desc_norm)
    if cloud_in_title or cloud_in_body:
        total = round(total * UNSUPPORTED_CLOUD_SCORE_FACTOR)
    return total, matched
