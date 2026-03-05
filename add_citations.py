#!/usr/bin/env python3
"""
add_citations.py
────────────────
Fetches citation counts using:
  - Semantic Scholar (primary  — best for CS/AI/NLP papers)
  - OpenAlex        (fallback  — for anything S2 misses)

Output column added: citations  (best available count)

Usage:
  python add_citations.py
  python add_citations.py --input my_papers.csv --output out.csv
  python add_citations.py --resume
"""

import argparse, json, time
from pathlib import Path
import pandas as pd
import requests

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_INPUT   = "papers_with_metadata.csv"
DEFAULT_OUTPUT  = "argumentation_papers_with_citations.csv"
CHECKPOINT_FILE = "citations_checkpoint.json"
TIMEOUT         = 30
MAX_RETRIES     = 3
OPENALEX_EMAIL  = "behantous@gmail.com"   #
S2_API_KEY      = ""                       # optional — get free key at semanticscholar.org/product/api

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
OA_URL       = "https://api.openalex.org/works"

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_doi(raw) -> str | None:
    if pd.isna(raw) or not str(raw).strip():
        return None
    doi = str(raw).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "DOI:", "doi:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi.strip() or None


def bar(done, total, w=35):
    pct = done / total if total else 0
    return f"[{'█'*int(w*pct)+'░'*(w-int(w*pct))}] {done}/{total}"


def load_checkpoint(path: str) -> dict:
    p = Path(path)
    if p.exists():
        data = json.loads(p.read_text())
        # ensure both keys exist (handles old checkpoint format)
        data.setdefault("s2", {})
        data.setdefault("openalex", {})
        return data
    return {"s2": {}, "openalex": {}}


def save_checkpoint(data: dict, path: str):
    Path(path).write_text(json.dumps(data))

# ── Semantic Scholar ──────────────────────────────────────────────────────────

def fetch_s2_batch(dois: list, api_key: str = "") -> dict:
    """Fetch citation counts for up to 500 DOIs in one S2 batch request."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(
                S2_BATCH_URL,
                params={"fields": "externalIds,citationCount"},
                headers=headers,
                json={"ids": [f"DOI:{d}" for d in dois]},
                timeout=TIMEOUT,
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"\n  [S2 rate-limit] waiting {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            out = {}
            for item in r.json():
                if not item:
                    continue
                doi = (item.get("externalIds") or {}).get("DOI")
                if doi and item.get("citationCount") is not None:
                    out[doi.lower()] = item["citationCount"]
            return out
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return {}


def fetch_all_s2(dois: list, cache: dict, api_key: str) -> dict:
    todo = [d for d in dois if d.lower() not in cache]
    if not todo:
        return cache

    batch_size = 500  # S2 allows up to 500 per batch
    batches = [todo[i:i+batch_size] for i in range(0, len(todo), batch_size)]

    for i, batch in enumerate(batches):
        print(f"\r  Semantic Scholar {bar(i+1, len(batches))}", end="", flush=True)
        cache.update(fetch_s2_batch(batch, api_key))
        time.sleep(3.0)  # S2 asks for ~1 req/s without key; 3s is safe

    print(f"\r  Semantic Scholar {bar(len(batches), len(batches))}  ✓          ")
    return cache

# ── OpenAlex ──────────────────────────────────────────────────────────────────

def fetch_oa_one(doi: str, headers: dict) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                OA_URL,
                params={"filter": f"doi:{doi}", "select": "doi,cited_by_count"},
                headers=headers,
                timeout=TIMEOUT,
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"\n  [OA rate-limit] waiting {wait}s…")
                time.sleep(wait)
                continue
            if r.status_code in (400, 404):
                return {}
            r.raise_for_status()
            out = {}
            for work in r.json().get("results", []):
                raw = work.get("doi")
                if raw:
                    bare = clean_doi(raw)
                    if bare:
                        out[bare.lower()] = work.get("cited_by_count", 0)
            return out
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return {}


def fetch_oa_batch(dois: list, headers: dict) -> dict:
    try:
        filter_str = "|".join(f"doi:{d}" for d in dois)
        r = requests.get(
            OA_URL,
            params={"filter": filter_str, "select": "doi,cited_by_count", "per-page": len(dois)},
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            out = {}
            for work in r.json().get("results", []):
                raw = work.get("doi")
                if raw:
                    bare = clean_doi(raw)
                    if bare:
                        out[bare.lower()] = work.get("cited_by_count", 0)
            return out
    except Exception:
        pass

    # fallback: one-by-one
    out = {}
    for doi in dois:
        out.update(fetch_oa_one(doi, headers))
        time.sleep(0.2)
    return out


def fetch_all_oa(dois: list, cache: dict, email: str) -> dict:
    """Only fetch DOIs that S2 missed."""
    todo = [d for d in dois if d.lower() not in cache]
    if not todo:
        print("  OpenAlex: nothing left to fetch.")
        return cache

    headers = {"User-Agent": f"CitationEnrichment/1.0 (mailto:{email or 'anon'})"}
    batch_size = 25
    batches = [todo[i:i+batch_size] for i in range(0, len(todo), batch_size)]

    for i, batch in enumerate(batches):
        print(f"\r  OpenAlex (fallback) {bar(i+1, len(batches))}", end="", flush=True)
        cache.update(fetch_oa_batch(batch, headers))
        time.sleep(1.0)

    print(f"\r  OpenAlex (fallback) {bar(len(batches), len(batches))}  ✓          ")
    return cache

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Add citation counts to a papers CSV.")
    parser.add_argument("--input",  default=DEFAULT_INPUT,  help="Input CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV")
    parser.add_argument("--email",  default=OPENALEX_EMAIL, help="Email for OpenAlex polite pool")
    parser.add_argument("--s2key",  default=S2_API_KEY,     help="Semantic Scholar API key (optional)")
    parser.add_argument("--resume", action="store_true",    help="Resume from checkpoint")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df["_doi"] = df["doi"].apply(clean_doi)
    has_doi  = df["_doi"].notna()
    all_dois = df.loc[has_doi, "_doi"].dropna().unique().tolist()

    print(f"✓ {len(df):,} papers  |  {has_doi.sum():,} with DOI  |  {(~has_doi).sum():,} without DOI\n")

    cp = load_checkpoint(CHECKPOINT_FILE) if args.resume else {"s2": {}, "openalex": {}}

    # Step 1 — Semantic Scholar (primary)
    print("Step 1/2 — Semantic Scholar")
    cp["s2"] = fetch_all_s2(all_dois, cp["s2"], args.s2key)
    save_checkpoint(cp, CHECKPOINT_FILE)

    # Step 2 — OpenAlex for whatever S2 missed
    s2_found  = set(cp["s2"].keys())
    oa_needed = [d for d in all_dois if d.lower() not in s2_found]
    print(f"\nStep 2/2 — OpenAlex fallback ({len(oa_needed):,} DOIs not found in S2)")
    cp["openalex"] = fetch_all_oa(oa_needed, cp["openalex"], args.email)
    save_checkpoint(cp, CHECKPOINT_FILE)

    # Merge: S2 wins, OA fills gaps → single `citations` column
    def best_citation(doi):
        if pd.isna(doi):
            return None
        key = doi.lower()
        if key in cp["s2"]:
            return cp["s2"][key]
        if key in cp["openalex"]:
            return cp["openalex"][key]
        return None

    df["citations"] = df["_doi"].apply(best_citation)
    df.drop(columns=["_doi"], inplace=True)

    # Ensure column order matches target schema
    target_cols = ["paper", "doi", "title", "year", "venue", "abstract", "keywords", "citations"]
    existing    = [c for c in target_cols if c in df.columns]
    extra       = [c for c in df.columns if c not in target_cols]
    df = df[existing + extra]

    # Summary
    found   = df["citations"].notna().sum()
    missing = has_doi.sum() - found
    cited   = df["citations"].dropna()
    print(f"\n── Results ───────────────────────────────────────")
    print(f"  Found   : {found:,}")
    print(f"  Missing : {missing:,}  (no DOI or not indexed)")
    if len(cited):
        print(f"  Max     : {cited.max():.0f}")
        print(f"  Median  : {cited.median():.0f}")
        print(f"  Mean    : {cited.mean():.1f}")
        print(f"  Zero    : {(cited==0).sum():,}")

    df.to_csv(args.output, index=False)
    print(f"\n✓ Saved → {args.output}")
    Path(CHECKPOINT_FILE).unlink(missing_ok=True)


if __name__ == "__main__":
    main()