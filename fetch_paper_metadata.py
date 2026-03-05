"""
Paper Metadata Fetcher
======================
Fetches abstracts and keywords for papers listed in a CSV file.
Sources tried (in order):
  1. OpenAlex      (https://api.openalex.org)
  2. Semantic Scholar (https://api.semanticscholar.org)
  3. CrossRef      (https://api.crossref.org)
  4. arXiv         (https://export.arxiv.org/api) — for arXiv DOIs/IDs

Usage:
    pip install requests pandas tqdm
    python fetch_paper_metadata.py --input argumentation_papers.csv --output results.csv

Optional flags:
    --email your@email.com   Passed to APIs as a polite-pool identifier (recommended)
    --delay 1.0              Seconds to wait between requests (default 1.0)
    --limit 0                Max papers to process; 0 = all
"""

import argparse
import csv
import json
import re
import time
import urllib.parse
from pathlib import Path

import requests
import pandas as pd
from tqdm import tqdm

# ─── helpers ────────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "PaperMetaFetcher/1.0 (research tool)"})


def get(url: str, params: dict = None, timeout: int = 15) -> dict | None:
    """GET a URL and return parsed JSON, or None on failure."""
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            print(f"  [rate-limit] {url} — sleeping 30 s")
            time.sleep(30)
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"  [error] {url}: {e}")
    return None


def clean(text: str | None) -> str:
    """Strip HTML tags and excess whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def invert_abstract(inv: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index."""
    if not inv:
        return ""
    pos_word = {}
    for word, positions in inv.items():
        for p in positions:
            pos_word[p] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))


def extract_arxiv_id(doi: str) -> str | None:
    """Return arXiv ID from a DOI like 10.48550/arXiv.2301.12345."""
    m = re.search(r"arxiv[./](\d{4}\.\d{4,5})", doi, re.IGNORECASE)
    return m.group(1) if m else None


# ─── per-source fetchers ─────────────────────────────────────────────────────

def from_openalex(doi: str, title: str, email: str) -> dict:
    """Query OpenAlex by DOI (preferred) or title."""
    result = {"abstract": "", "keywords": "", "source": ""}

    if doi:
        encoded = urllib.parse.quote(doi, safe="")
        data = get(
            f"https://api.openalex.org/works/https://doi.org/{encoded}",
            params={"mailto": email} if email else None,
        )
        if data:
            result["abstract"] = invert_abstract(data.get("abstract_inverted_index"))
            result["keywords"] = "; ".join(
                kw.get("display_name", "") for kw in data.get("keywords", [])
            )
            if not result["keywords"]:
                result["keywords"] = "; ".join(
                    c.get("display_name", "")
                    for c in data.get("concepts", [])
                    if c.get("score", 0) >= 0.3
                )
            result["source"] = "OpenAlex"
            return result

    if title:
        data = get(
            "https://api.openalex.org/works",
            params={
                "search": title,
                "per-page": 1,
                "mailto": email or "",
            },
        )
        if data and data.get("results"):
            item = data["results"][0]
            result["abstract"] = invert_abstract(item.get("abstract_inverted_index"))
            result["keywords"] = "; ".join(
                kw.get("display_name", "") for kw in item.get("keywords", [])
            )
            if not result["keywords"]:
                result["keywords"] = "; ".join(
                    c.get("display_name", "")
                    for c in item.get("concepts", [])
                    if c.get("score", 0) >= 0.3
                )
            result["source"] = "OpenAlex (title search)"

    return result


def from_semantic_scholar(doi: str, title: str) -> dict:
    """Query Semantic Scholar Graph API."""
    result = {"abstract": "", "keywords": "", "source": ""}
    fields = "abstract,keywords"

    if doi:
        data = get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": fields},
        )
        if data and (data.get("abstract") or data.get("keywords")):
            result["abstract"] = clean(data.get("abstract", ""))
            result["keywords"] = "; ".join(data.get("keywords") or [])
            result["source"] = "Semantic Scholar"
            return result

    if title:
        data = get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "limit": 1, "fields": fields},
        )
        if data and data.get("data"):
            item = data["data"][0]
            result["abstract"] = clean(item.get("abstract", ""))
            result["keywords"] = "; ".join(item.get("keywords") or [])
            result["source"] = "Semantic Scholar (title search)"

    return result


def from_crossref(doi: str) -> dict:
    """Query CrossRef for abstract (often not present, but worth trying)."""
    result = {"abstract": "", "keywords": "", "source": ""}
    if not doi:
        return result
    encoded = urllib.parse.quote(doi, safe="")
    data = get(f"https://api.crossref.org/works/{encoded}")
    if data and data.get("message"):
        msg = data["message"]
        result["abstract"] = clean(msg.get("abstract", ""))
        # CrossRef rarely returns keywords, but check
        subjects = msg.get("subject", [])
        result["keywords"] = "; ".join(subjects)
        if result["abstract"]:
            result["source"] = "CrossRef"
    return result


def from_arxiv(doi: str) -> dict:
    """Query arXiv API for arXiv-hosted papers."""
    result = {"abstract": "", "keywords": "", "source": ""}
    arxiv_id = extract_arxiv_id(doi or "")
    if not arxiv_id:
        return result
    data = get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id, "max_results": 1},
    )
    if data:
        # arXiv returns Atom XML; parse it minimally via text
        # Requests returns text for XML — re-fetch as text
        try:
            r = SESSION.get(
                "https://export.arxiv.org/api/query",
                params={"id_list": arxiv_id, "max_results": 1},
                timeout=15,
            )
            xml = r.text
            m_abs = re.search(r"<summary[^>]*>(.*?)</summary>", xml, re.DOTALL)
            if m_abs:
                result["abstract"] = clean(m_abs.group(1))
                result["source"] = "arXiv"
        except Exception:
            pass
    return result


# ─── main logic ─────────────────────────────────────────────────────────────

def fetch_metadata(doi: str, title: str, email: str, delay: float) -> dict:
    """Try each source in order; stop as soon as we get an abstract."""
    # Strip trailing dot from title if present
    title = title.rstrip(".").strip() if title else ""
    doi = doi.strip() if doi else ""

    # 1. arXiv (fast for arXiv DOIs)
    if doi and "arxiv" in doi.lower():
        r = from_arxiv(doi)
        if r["abstract"]:
            time.sleep(delay)
            return r

    # 2. OpenAlex
    r = from_openalex(doi, title, email)
    if r["abstract"]:
        time.sleep(delay)
        return r

    # 3. Semantic Scholar
    time.sleep(delay)
    r = from_semantic_scholar(doi, title)
    if r["abstract"]:
        time.sleep(delay)
        return r

    # 4. CrossRef (abstract rarely present but worth it)
    time.sleep(delay)
    r = from_crossref(doi)
    if r["abstract"]:
        return r

    time.sleep(delay)
    return {"abstract": "", "keywords": "", "source": "not found"}


def main():
    parser = argparse.ArgumentParser(description="Fetch paper abstracts & keywords.")
    parser.add_argument("--input", default="argumentation_papers.csv", help="Input CSV path")
    parser.add_argument("--output", default="papers_with_metadata.csv", help="Output CSV path")
    parser.add_argument("--email", default="", help="Your email for API polite pool")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (s)")
    parser.add_argument("--limit", type=int, default=0, help="Max papers (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip already-fetched rows in output")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    if args.limit:
        df = df.head(args.limit)

    # Resume support: load existing output and skip done rows
    done_titles = set()
    if args.resume and Path(args.output).exists():
        existing = pd.read_csv(args.output)
        done_titles = set(existing["title"].dropna())
        print(f"Resuming — {len(done_titles)} papers already processed.")

    rows = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Fetching"):
        title = str(row.get("title", "")).strip()
        doi = str(row.get("doi", "")).strip()
        doi = "" if doi.lower() in ("nan", "none", "") else doi

        if title in done_titles:
            continue

        meta = fetch_metadata(doi, title, args.email, args.delay)
        rows.append({
            "paper": row.get("paper", ""),
            "doi": doi,
            "title": title,
            "year": row.get("year", ""),
            "venue": row.get("venue", ""),
            "abstract": meta["abstract"],
            "keywords": meta["keywords"],
            "metadata_source": meta["source"],
        })

    result_df = pd.DataFrame(rows)

    if args.resume and Path(args.output).exists():
        existing = pd.read_csv(args.output)
        result_df = pd.concat([existing, result_df], ignore_index=True)

    result_df.to_csv(args.output, index=False, encoding="utf-8")
    total = len(result_df)
    found = result_df["abstract"].astype(bool).sum()
    print(f"\nDone. {found}/{total} papers have abstracts.")
    print(f"Results saved to: {args.output}")

    # Print source breakdown
    print("\nMetadata source breakdown:")
    print(result_df["metadata_source"].value_counts().to_string())


if __name__ == "__main__":
    main()
