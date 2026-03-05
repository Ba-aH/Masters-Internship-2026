#!/usr/bin/env python3
"""
merge_csvs.py — Merge two OpenAlex-style paper CSV files

Usage:
    python merge_csvs.py file1.csv file2.csv
    python merge_csvs.py file1.csv file2.csv --output merged.csv

Duplicate detection (in order):
    1. DOI match  (exact, case-insensitive, after stripping https://doi.org/)
    2. Title match (case-insensitive, after normalising whitespace)

When a duplicate is found:
    → Fields are MERGED: empty fields in CSV1 are filled from CSV2, and vice versa.
    → For numeric fields (cited_by_count), the higher value is kept.
    → 'citations' and 'cited_by_count' are treated as the same column; the max value is kept.
    → Source column records which file(s) the row came from.

Output column order follows CSV1 columns first, then any extras from CSV2.
"""

import csv
import os
import re
import sys
import argparse
from collections import OrderedDict

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Columns where the HIGHER numeric value should be kept on merge
PREFER_HIGHER = {'cited_by_count'}

# Treat these as the same column — normalise to the canonical name
COLUMN_ALIASES = {
    'cited_by_coun': 'cited_by_count',   # CSV1 typo → canonical name
    'citations':     'cited_by_count',   # CSV2 synonym → same column
}

# Similarity threshold for fuzzy title matching (0.0–1.0)
TITLE_SIMILARITY = 0.85
# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalise_doi(doi: str) -> str:
    """Strip URL prefix and lowercase for comparison."""
    if not doi:
        return ''
    return (doi
            .strip()
            .lower()
            .replace('https://doi.org/', '')
            .replace('http://doi.org/', '')
            .replace('doi:', ''))

def normalise_title(title: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation for comparison."""
    if not title:
        return ''
    t = title.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)   # remove punctuation
    t = re.sub(r'\s+', ' ', t)      # collapse spaces
    return t

def title_similarity(a: str, b: str) -> float:
    """Word-overlap Jaccard similarity between two normalised titles."""
    stopwords = {'a','an','the','of','in','on','with','to','and','or',
                 'for','by','at','from','is','are','its','using'}
    wa = set(normalise_title(a).split()) - stopwords
    wb = set(normalise_title(b).split()) - stopwords
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

def merge_rows(r1: dict, r2: dict, prefer_higher: set) -> dict:
    """
    Merge two rows representing the same paper.
    - r1 fields take priority; r2 fills in blanks.
    - For columns in prefer_higher, keep the larger numeric value.
    """
    merged = dict(r1)
    for key, val2 in r2.items():
        val1 = merged.get(key, '')
        # Fill blank fields from r2
        if not val1 and val2:
            merged[key] = val2
        # For numeric preference columns, keep the higher value
        elif key in prefer_higher and val1 and val2:
            try:
                merged[key] = str(max(int(val1), int(val2)))
            except ValueError:
                pass  # keep r1 value if not numeric
    return merged

def normalise_columns(rows: list[dict], fieldnames: list[str]) -> tuple[list[dict], list[str]]:
    """Rename aliased column names to their canonical form."""
    new_fields = [COLUMN_ALIASES.get(f, f) for f in fieldnames]
    new_rows = []
    for row in rows:
        new_row = {COLUMN_ALIASES.get(k, k): v for k, v in row.items()}
        new_rows.append(new_row)
    return new_rows, new_fields

def read_csv(path: str) -> tuple[list[dict], list[str]]:
    """Return (rows, fieldnames) from a CSV file, with column aliases resolved."""
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        fieldnames = list(reader.fieldnames or [])
    return normalise_columns(rows, fieldnames)

def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  MERGE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def build_merged_fieldnames(fields1: list[str], fields2: list[str]) -> list[str]:
    """
    Output columns = CSV1 columns (in order) + any extras from CSV2 + 'source'.
    """
    seen = set(fields1)
    extra = [f for f in fields2 if f not in seen]
    return fields1 + extra + ['source']

def merge(path1: str, path2: str, output_path: str) -> None:
    rows1, fields1 = read_csv(path1)
    rows2, fields2 = read_csv(path2)

    out_fields = build_merged_fieldnames(fields1, fields2)

    print(f'\n📄 CSV1: {os.path.basename(path1):40s} → {len(rows1):>5} rows, {len(fields1)} columns')
    print(f'📄 CSV2: {os.path.basename(path2):40s} → {len(rows2):>5} rows, {len(fields2)} columns')
    print(f'\n🔗 Output columns ({len(out_fields)}): {", ".join(out_fields)}')

    # ── Index CSV1 by DOI and normalised title ─────────────────────────────
    doi_index   = {}   # normalised_doi   → index in merged list
    title_index = {}   # normalised_title → index in merged list
    merged      = []

    for row in rows1:
        row['source'] = os.path.basename(path1)
        idx = len(merged)
        merged.append(row)

        ndoi = normalise_doi(row.get('doi', ''))
        if ndoi:
            doi_index[ndoi] = idx

        ntitle = normalise_title(row.get('title', ''))
        if ntitle:
            title_index[ntitle] = idx

    # ── Process CSV2 rows ──────────────────────────────────────────────────
    new_count  = 0
    dup_count  = 0

    for row2 in rows2:
        matched_idx = None

        # Step 1: DOI match
        ndoi2 = normalise_doi(row2.get('doi', ''))
        if ndoi2 and ndoi2 in doi_index:
            matched_idx = doi_index[ndoi2]

        # Step 2: Title match (if no DOI match)
        if matched_idx is None:
            ntitle2 = normalise_title(row2.get('title', ''))
            if ntitle2 in title_index:
                matched_idx = title_index[ntitle2]
            else:
                # Fuzzy title fallback
                for ntitle1, idx in title_index.items():
                    if title_similarity(ntitle2, ntitle1) >= TITLE_SIMILARITY:
                        matched_idx = idx
                        break

        if matched_idx is not None:
            # Duplicate — merge fields
            merged[matched_idx] = merge_rows(
                merged[matched_idx], row2, PREFER_HIGHER)
            merged[matched_idx]['source'] = (
                merged[matched_idx]['source'] + ' + ' + os.path.basename(path2)
                if os.path.basename(path2) not in merged[matched_idx]['source']
                else merged[matched_idx]['source']
            )
            dup_count += 1
        else:
            # New paper — add from CSV2
            row2['source'] = os.path.basename(path2)
            idx = len(merged)
            merged.append(row2)

            ndoi2 = normalise_doi(row2.get('doi', ''))
            if ndoi2:
                doi_index[ndoi2] = idx

            ntitle2 = normalise_title(row2.get('title', ''))
            if ntitle2:
                title_index[ntitle2] = idx

            new_count += 1

    # ── Ensure every row has all output fields ─────────────────────────────
    for row in merged:
        for field in out_fields:
            row.setdefault(field, '')

    write_csv(output_path, merged, out_fields)

    # ── Summary ────────────────────────────────────────────────────────────
    print(f'\n{"="*60}')
    print('MERGE SUMMARY')
    print(f'{"="*60}')
    print(f'  CSV1 rows:              {len(rows1):>6}')
    print(f'  CSV2 rows:              {len(rows2):>6}')
    print(f'  Duplicates merged:      {dup_count:>6}  (fields filled from both)')
    print(f'  New rows from CSV2:     {new_count:>6}')
    print(f'  Total output rows:      {len(merged):>6}')
    print(f'\n✅ Saved to: {os.path.abspath(output_path)}')


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Merge two OpenAlex-style paper CSV files.')
    parser.add_argument('file1', help='First CSV file (fields take priority)')
    parser.add_argument('file2', help='Second CSV file')
    parser.add_argument('--output', '-o', default='merged_papers.csv',
                        help='Output file name (default: merged_papers.csv)')
    args = parser.parse_args()

    for path in [args.file1, args.file2]:
        if not os.path.exists(path):
            print(f'❌ File not found: {path}')
            sys.exit(1)

    merge(args.file1, args.file2, args.output)


if __name__ == '__main__':
    main()