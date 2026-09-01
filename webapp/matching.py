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
# platforms are mentioned. The terms are deliberately checked across the
# whole announcement text, not only in the title.
UNSUPPORTED_CLOUD_TERMS = ("azure", "aws")
UNSUPPORTED_CLOUD_SCORE_FACTOR = 0.60

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
    if any(has_term(f"{title} {body}", term) for term in UNSUPPORTED_CLOUD_TERMS):
        total = round(total * UNSUPPORTED_CLOUD_SCORE_FACTOR)
    return total, matched
