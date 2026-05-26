"""
enrich_openalex.py
------------------
Enriches references.json with data from the OpenAlex API.

Enriches:
  - Missing DOIs (looked up by title)
  - Author details: ORCID, affiliations
  - Venue / journal details: ISSN, publisher, type

Usage:
    python enrich_openalex.py --input references.json --output references_enriched.json

OpenAlex API docs: https://docs.openalex.org
No API key required, but set your email via --email for the polite pool (faster).
"""

import argparse
import json
import time
import logging
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENALEX_BASE = "https://api.openalex.org"
RATE_LIMIT_DELAY = 0.1   # seconds between requests (polite pool: up to 10 req/s)
MAX_RETRIES = 3
RETRY_DELAY = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAlex helpers
# ---------------------------------------------------------------------------

def make_session(email: str | None) -> requests.Session:
    session = requests.Session()
    # Using email puts you in the "polite pool" — higher rate limits
    ua = "CiteKG-Enrichment/1.0"
    if email:
        ua += f" (mailto:{email})"
    session.headers.update({"User-Agent": ua})
    return session


def get_with_retry(session: requests.Session, url: str, params: dict) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                log.warning("Rate limited. Waiting %ss before retry %s/%s",
                            RETRY_DELAY, attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY)
            else:
                log.warning("HTTP %s for %s", resp.status_code, url)
                return None
        except requests.RequestException as e:
            log.warning("Request error (attempt %s/%s): %s", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY)
    return None


def fetch_by_openalex_id(session: requests.Session, openalex_id: str) -> dict | None:
    """Fetch a work directly by its OpenAlex ID (fastest path)."""
    # openalex_id may be a full URL like https://openalex.org/W123 or just W123
    work_id = openalex_id.split("/")[-1]
    url = f"{OPENALEX_BASE}/works/{work_id}"
    time.sleep(RATE_LIMIT_DELAY)
    return get_with_retry(session, url, {})


def fetch_by_doi(session: requests.Session, doi: str) -> dict | None:
    """Fetch a work by DOI."""
    # Normalise: strip https://doi.org/ prefix if present
    doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    url = f"{OPENALEX_BASE}/works/https://doi.org/{doi_clean}"
    time.sleep(RATE_LIMIT_DELAY)
    return get_with_retry(session, url, {})


def fetch_by_title(session: requests.Session, title: str, year: int | None) -> dict | None:
    """Search for a work by title (fallback when no ID or DOI is available)."""
    params = {
        "search": title,
        "per_page": 1,
    }
    if year:
        params["filter"] = f"publication_year:{year}"
    time.sleep(RATE_LIMIT_DELAY)
    data = get_with_retry(session, f"{OPENALEX_BASE}/works", params)
    if data and data.get("results"):
        return data["results"][0]
    return None


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_doi(work: dict) -> str | None:
    doi = work.get("doi")
    if doi:
        # Return clean DOI without URL prefix
        return doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return None


def extract_authors(work: dict) -> list[dict]:
    """
    Returns a list of author dicts:
    {
        author_id: str,        # OpenAlex author ID (short form)
        author_name: str,
        orcid: str | None,
        affiliations: list[str]
    }
    """
    authors = []
    for authorship in work.get("authorships", []):
        author_info = authorship.get("author", {})
        raw_id = author_info.get("id", "")
        short_id = raw_id.split("/")[-1] if raw_id else None

        institutions = [
            inst.get("display_name")
            for inst in authorship.get("institutions", [])
            if inst.get("display_name")
        ]

        authors.append({
            "author_id": short_id,
            "author_name": author_info.get("display_name", ""),
            "orcid": author_info.get("orcid"),          # full ORCID URL or None
            "affiliations": institutions,
        })
    return authors


def extract_venue(work: dict) -> dict:
    """
    Returns venue enrichment dict:
    {
        venue_name: str | None,
        issn: list[str],
        publisher: str | None,
        venue_type: str | None,   # "journal", "conference", "repository" …
        openalex_venue_id: str | None
    }
    """
    # primary_location → source is the canonical venue in OpenAlex
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}

    raw_id = source.get("id", "")
    short_id = raw_id.split("/")[-1] if raw_id else None

    return {
        "venue_name": source.get("display_name"),
        "issn": source.get("issn") or [],
        "publisher": source.get("host_organization_name"),
        "venue_type": source.get("type"),
        "openalex_venue_id": short_id,
    }


# ---------------------------------------------------------------------------
# Core enrichment logic
# ---------------------------------------------------------------------------

def enrich_paper(session: requests.Session, paper: dict) -> dict:
    """
    Try to fetch the OpenAlex work for a single paper entry and
    merge enrichment data into it. Returns the (possibly updated) paper dict.
    """
    title = paper.get("title", "")
    year = paper.get("year")
    doi = paper.get("doi")
    openalex_id = paper.get("openalex_id")

    work = None

    # Priority 1: use existing OpenAlex ID — fastest and most reliable
    if openalex_id:
        log.info("Fetching by OpenAlex ID: %s", openalex_id)
        work = fetch_by_openalex_id(session, openalex_id)

    # Priority 2: use DOI
    if work is None and doi:
        log.info("Fetching by DOI: %s", doi)
        work = fetch_by_doi(session, doi)

    # Priority 3: title search — least reliable, use with caution
    if work is None and title:
        log.info("Fetching by title search: '%s'", title[:60])
        work = fetch_by_title(session, title, year)

    if work is None:
        log.warning("No OpenAlex match found for: '%s'", title[:60])
        return paper  # return unchanged

    # ---- Fill missing DOI ----
    if not paper.get("doi"):
        found_doi = extract_doi(work)
        if found_doi:
            paper["doi"] = found_doi
            log.info("  + DOI filled: %s", found_doi)

    # ---- Fill/update OpenAlex ID ----
    if not paper.get("openalex_id") and work.get("id"):
        paper["openalex_id"] = work["id"].split("/")[-1]

    # ---- Author enrichment ----
    enriched_authors = extract_authors(work)
    if enriched_authors:
        # Merge: prefer existing author_id if already present in your data,
        # but add orcid and affiliations from OpenAlex
        existing = {a.get("author_name", "").lower(): a
                    for a in paper.get("authors", [])}

        if existing:
            # Update existing author entries with new fields
            for oa in enriched_authors:
                key = oa["author_name"].lower()
                if key in existing:
                    existing[key].setdefault("orcid", oa["orcid"])
                    existing[key].setdefault("affiliations", oa["affiliations"])
            paper["authors"] = list(existing.values())
        else:
            # No existing authors — write OpenAlex authors directly
            paper["authors"] = enriched_authors

        log.info("  + Authors enriched: %s author(s)", len(enriched_authors))

    # ---- Venue enrichment ----
    venue_data = extract_venue(work)
    if any(venue_data.values()):
        # Keep existing venue string, add structured fields
        paper.setdefault("venue", venue_data.get("venue_name"))
        paper["venue_details"] = venue_data
        log.info("  + Venue enriched: %s", venue_data.get("venue_name"))

    return paper


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enrich references.json via OpenAlex")
    parser.add_argument("--input",  default="references.json",
                        help="Path to input references.json")
    parser.add_argument("--output", default="references_enriched.json",
                        help="Path to write enriched output")
    parser.add_argument("--email",  default=None,
                        help="Your email for OpenAlex polite pool (recommended)")
    parser.add_argument("--only-refs", action="store_true",
                        help="Skip main paper, only enrich references[]")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        return

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    session = make_session(args.email)

    # ---- Enrich main paper ----
    if not args.only_refs and "paper" in data:
        log.info("=== Enriching main paper ===")
        data["paper"] = enrich_paper(session, data["paper"])

    # ---- Enrich each reference ----
    refs = data.get("references", [])
    log.info("=== Enriching %s references ===", len(refs))

    for i, ref in enumerate(refs, 1):
        log.info("[%s/%s] %s", i, len(refs), ref.get("title", "")[:60])
        refs[i - 1] = enrich_paper(session, ref)

    data["references"] = refs

    # ---- Write output ----
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("Done. Enriched data written to %s", output_path)


if __name__ == "__main__":
    main()
