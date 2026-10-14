"""
jobs/dedupe.py
Duplicate detection across different URLs, platforms, and job aggregators.
Uses canonical URL normalization, company + title normalization, and content SHA-256 fingerprinting.
"""
import re
import hashlib
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Application, ApplicationStatus


# Query parameters commonly used for tracking that don't change the job posting
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "refid", "source", "gh_src", "lever-source", "mode", "iis", "iisn",
    "fbclid", "gclid", "trackingid", "trk", "trkinfo", "originalsubdomain", "position", "pagenum"
}


def normalize_url(url: str) -> str:
    """
    Normalizes a job URL to its canonical form:
    - Strips query params related to tracking/utm
    - Normalizes scheme and domain (lowercase, remove trailing slashes)
    - Normalizes LinkedIn, Greenhouse, Lever, Ashby, Workday URLs
    """
    if not url:
        return ""
    
    url = url.strip()
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        # Filter out tracking query parameters
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        clean_pairs = [
            (k, v) for k, v in query_pairs
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
        ]
        # Sort query pairs for deterministic hashing
        clean_pairs.sort()
        query = urlencode(clean_pairs)

        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url.strip().rstrip("/")


def normalize_text(text: str) -> str:
    """
    Normalizes text (company name, job title, description) for comparison:
    - Lowercase
    - Remove extra whitespaces and punctuation
    """
    if not text:
        return ""
    text = text.lower()
    # Normalize common abbreviations
    text = re.sub(r"\b(?:inc|llc|corp|corporation|co)\b\.?", "", text)
    # Remove punctuation
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_job_fingerprint(company: str, job_title: str, job_description: Optional[str] = None) -> str:
    """
    Computes a deterministic SHA-256 fingerprint for a job posting based on:
    - Normalized company name
    - Normalized job title
    - Core description snippet (first 1000 normalized characters of description if available)
    """
    norm_company = normalize_text(company)
    norm_title = normalize_text(job_title)
    
    parts = [norm_company, norm_title]
    if job_description:
        norm_desc = normalize_text(job_description)[:1000]
        parts.append(norm_desc)
    
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def check_duplicate(
    session: AsyncSession,
    company: str,
    job_title: str,
    job_url: str,
    job_description: Optional[str] = None,
    external_job_id: Optional[str] = None,
) -> Tuple[bool, Optional[Application], str]:
    """
    Checks if this job has already been recorded in the database.
    Checks:
    1. Exact canonical URL match
    2. External job ID match (for same company)
    3. Company + normalized title match where status is already submitted/applying/ready
    4. Exact description fingerprint match
    
    Returns:
        (is_duplicate, existing_application, duplicate_reason)
    """
    canonical_url = normalize_url(job_url)
    fingerprint = compute_job_fingerprint(company, job_title, job_description)

    # 1. Match by canonical URL
    if canonical_url:
        result = await session.execute(
            select(Application).where(
                or_(
                    Application.canonical_job_url == canonical_url,
                    Application.job_url == job_url,
                    Application.job_url == canonical_url
                )
            )
        )
        existing = result.scalars().first()
        if existing:
            return True, existing, f"Exact URL match (App #{existing.id}, status: {existing.status.value})"

    # 2. Match by external job ID
    if external_job_id and company:
        norm_company = normalize_text(company)
        result = await session.execute(
            select(Application).where(
                Application.external_job_id == external_job_id
            )
        )
        for existing in result.scalars().all():
            if normalize_text(existing.company) == norm_company:
                return True, existing, f"External job ID match ({external_job_id}) for {company}"

    # 3. Match by description fingerprint
    if job_description:
        desc_hash = hashlib.sha256(job_description.encode("utf-8")).hexdigest()
        result = await session.execute(
            select(Application).where(
                or_(
                    Application.job_description_hash == desc_hash,
                    Application.job_description_hash == fingerprint
                )
            )
        )
        existing = result.scalars().first()
        if existing:
            return True, existing, f"Identical job description hash (App #{existing.id})"

    # 4. Match by normalized Company + Title (if submitted or in progress)
    norm_comp = normalize_text(company)
    norm_titl = normalize_text(job_title)
    if norm_comp and norm_titl:
        result = await session.execute(
            select(Application).where(
                Application.normalized_company == norm_comp,
                Application.normalized_job_title == norm_titl,
                Application.status.in_([
                    ApplicationStatus.SUBMITTED, ApplicationStatus.APPLYING, ApplicationStatus.READY,
                    ApplicationStatus.PAUSED, ApplicationStatus.NEEDS_ATTENTION, ApplicationStatus.NEEDS_REVIEW
                ])
            )
        )
        existing = result.scalars().first()
        if existing:
            return True, existing, f"Same company & title already applied/in-progress (App #{existing.id})"

    return False, None, ""
