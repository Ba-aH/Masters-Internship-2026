#!/usr/bin/env python3
"""
scrape_missing_metadata.py
━━━━━━━━━━━━━━━━━━━━━━━━━━
Fetches OpenAlex metadata for papers listed in missing_metadata.csv.
Input:  missing_metadata.csv  (columns: title, filename)
Output: missing_metadata_enriched.csv  (all original columns + OpenAlex fields)

Resume: python scrape_missing_metadata.py --resume
        → skips papers already present in the output file
"""

import pandas as pd
import requests
import time
import os
import argparse

# ─── CONFIG ───────────────────────────────────────────────────────────────────
INPUT_CSV   = "not_found_papers.csv"
OUTPUT_CSV  = "not_found_papers_enriched.csv"
MAILTO      = "behantous@gmail.com"
DELAY       = 0.15   # seconds between requests (polite pool allows ~10 req/s)
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": f"MyScraper/1.0 (mailto:{MAILTO})"}


# ══════════════════════════════════════════════════════════════════════════════
#  OPENALEX QUERY  — title-only (missing_metadata has no DOIs)
# ══════════════════════════════════════════════════════════════════════════════

def query_openalex(title: str) -> dict | None:
    """Search OpenAlex by title. Returns the best-matching work dict or None."""
    if not title or not str(title).strip():
        return None

    clean_title = str(title).strip()
    url = (
        f"https://api.openalex.org/works"
        f"?filter=title.search:{requests.utils.quote(clean_title)}"
        f"&per_page=1"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                return results[0]
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  FIELD EXTRACTION  — mirrors your original script exactly
# ══════════════════════════════════════════════════════════════════════════════

def extract_fields(work: dict | None) -> dict:
    if not work:
        return {
            "doi": "", "year": "", "venue": "", "abstract": "",
            "keywords": "", "authors": "",
            "primary_topic": "", "primary_subfield": "",
            "primary_field": "", "primary_domain": "",
            "referenced_works": "", "related_works": "",
            "cited_by_count": "",
        }

    # Authors
    authorships = work.get("authorships", [])
    authors = "; ".join(
        a["author"]["display_name"]
        for a in authorships if a.get("author")
    )

    # Primary topic (new OpenAlex schema)
    topics_raw = work.get("topics", [])
    primary    = topics_raw[0] if topics_raw else {}

    # Venue / source
    primary_location = work.get("primary_location") or {}
    source           = primary_location.get("source") or {}
    venue            = source.get("display_name", "")

    # Abstract (inverted index → plain text)
    abstract = ""
    inv_index = work.get("abstract_inverted_index")
    if inv_index:
        try:
            length = max(pos for positions in inv_index.values() for pos in positions) + 1
            words  = [""] * length
            for word, positions in inv_index.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words)
        except Exception:
            abstract = ""

    # Keywords
    keywords = "; ".join(
        kw.get("display_name", "") for kw in work.get("keywords", [])
    )

    return {
        "doi":              work.get("doi", ""),
        "year":             work.get("publication_year", ""),
        "venue":            venue,
        "abstract":         abstract,
        "keywords":         keywords,
        "authors":          authors,
        "primary_topic":    primary.get("display_name", ""),
        "primary_subfield": primary.get("subfield", {}).get("display_name", ""),
        "primary_field":    primary.get("field",    {}).get("display_name", ""),
        "primary_domain":   primary.get("domain",   {}).get("display_name", ""),
        "referenced_works": "; ".join(work.get("referenced_works", [])),
        "related_works":    "; ".join(work.get("related_works",    [])),
        "cited_by_count":   work.get("cited_by_count", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Scrape OpenAlex metadata for papers in missing_metadata.csv')
    parser.add_argument('--input',  default=INPUT_CSV,  help=f'Input CSV  (default: {INPUT_CSV})')
    parser.add_argument('--output', default=OUTPUT_CSV, help=f'Output CSV (default: {OUTPUT_CSV})')
    parser.add_argument('--resume', action='store_true',
                        help='Skip papers already in the output file')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'❌ Input file not found: {args.input}')
        return

    df = pd.read_csv(args.input, encoding='utf-8-sig')
    print(f'📄 Loaded {len(df)} rows from "{args.input}"')

    # ── Resume: skip already-processed titles ─────────────────────────────
    already_done = set()
    if args.resume and os.path.exists(args.output):
        done_df = pd.read_csv(args.output, encoding='utf-8-sig')
        already_done = set(done_df['title'].dropna().str.strip())
        print(f'⏭  Resuming — {len(already_done)} already done, '
              f'{len(df) - len(already_done)} remaining')

    # ── Process ───────────────────────────────────────────────────────────
    enriched_rows = []
    found = not_found = skipped = 0

    for i, row in df.iterrows():
        title = str(row.get('title', '') or '').strip()
        short = title[:55]

        if title in already_done:
            skipped += 1
            continue

        print(f'[{i+1}/{len(df)}] {short}...', end=' ', flush=True)

        work  = query_openalex(title)
        extra = extract_fields(work)

        if work:
            found += 1
            print('✓')
        else:
            not_found += 1
            print('✗ not found')

        enriched_rows.append({**row.to_dict(), **extra})
        time.sleep(DELAY)

    # ── Save ──────────────────────────────────────────────────────────────
    result_df = pd.DataFrame(enriched_rows)

    # Append to existing output if resuming
    if args.resume and os.path.exists(args.output) and not result_df.empty:
        existing = pd.read_csv(args.output, encoding='utf-8-sig')
        result_df = pd.concat([existing, result_df], ignore_index=True)

    result_df.to_csv(args.output, index=False, encoding='utf-8')

    print(f'\n{"="*60}')
    print('SCRAPING SUMMARY')
    print(f'{"="*60}')
    print(f'  Total rows:      {len(df)}')
    print(f'  ✅ Found:        {found}')
    print(f'  ❌ Not found:    {not_found}')
    print(f'  ⏭  Skipped:     {skipped}')
    print(f'\n✅ Saved to: {os.path.abspath(args.output)}')


if __name__ == '__main__':
    main()