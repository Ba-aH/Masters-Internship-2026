#!/usr/bin/env python3
"""
find_missing_metadata.py
━━━━━━━━━━━━━━━━━━━━━━━━
Compares PDFs in a folder against a metadata CSV.
Outputs a new CSV listing every PDF that has no matching metadata row,
with its title (derived from the filename) ready for metadata scraping.

Usage:
    python find_missing_metadata.py
    python find_missing_metadata.py --papers papersCombined --csv argumentation_papers.csv
    python find_missing_metadata.py --papers papersCombined --csv argumentation_papers.csv --output missing.csv

Matching logic (in order):
    1. Normalised title from CSV  ↔  normalised PDF filename (stem)
    2. Fuzzy word-overlap ≥ 0.70  (catches minor wording differences)
"""

import os
import re
import csv
import argparse

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DEFAULT_PAPERS_FOLDER = "papersCombined"
DEFAULT_CSV           = "argumentation_papers.csv"
DEFAULT_OUTPUT        = "missing_metadata.csv"
FUZZY_THRESHOLD       = 0.70   # word-overlap Jaccard to count as a match
# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ''
    t = text.lower()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

STOPWORDS = {
    'a','an','the','of','in','on','with','to','and','or','for',
    'by','at','from','is','are','its','using','via','into','between',
}

def keywords(text: str) -> set[str]:
    return set(normalise(text).split()) - STOPWORDS

def jaccard(a: str, b: str) -> float:
    wa, wb = keywords(a), keywords(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

def pdf_stem(filename: str) -> str:
    """Return filename without .pdf extension."""
    return re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)

def title_from_filename(filename: str) -> str:
    """
    Convert a sanitized PDF filename back to a readable title.
    Reverses the sanitize_filename() logic used by download_papers.py:
      - strips .pdf
      - replaces underscores with spaces (if any)
    """
    stem = pdf_stem(filename)
    return stem.replace('_', ' ').strip()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def find_missing(papers_folder: str, csv_path: str, output_path: str) -> None:

    # ── 1. Collect all PDFs in the folder ─────────────────────────────────
    if not os.path.isdir(papers_folder):
        print(f'❌ Papers folder not found: {papers_folder}')
        return

    pdf_files = [
        f for f in os.listdir(papers_folder)
        if f.lower().endswith('.pdf')
    ]
    if not pdf_files:
        print(f'⚠️  No PDF files found in: {papers_folder}')
        return

    print(f'📂 Found {len(pdf_files)} PDF(s) in "{papers_folder}"')

    # ── 2. Load titles from the metadata CSV ──────────────────────────────
    if not os.path.exists(csv_path):
        print(f'❌ CSV file not found: {csv_path}')
        return

    csv_titles = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = (row.get('title') or '').strip()
            if t:
                csv_titles.append(t)

    print(f'📄 Loaded {len(csv_titles)} titled row(s) from "{csv_path}"')

    # Pre-normalise CSV titles for fast lookup
    csv_norm = [normalise(t) for t in csv_titles]

    # ── 3. Match each PDF against CSV titles ──────────────────────────────
    missing   = []   # (filename, derived_title)
    matched   = []

    for filename in sorted(pdf_files):
        stem        = pdf_stem(filename)
        norm_stem   = normalise(stem)
        derived     = title_from_filename(filename)

        # Step 1: exact normalised match
        if norm_stem in csv_norm:
            matched.append(filename)
            continue

        # Step 2: fuzzy match
        best_score = max((jaccard(norm_stem, ct) for ct in csv_norm), default=0.0)
        if best_score >= FUZZY_THRESHOLD:
            matched.append(filename)
        else:
            missing.append((filename, derived))

    # ── 4. Report ─────────────────────────────────────────────────────────
    print(f'\n{"="*60}')
    print(f'  ✅ Matched (metadata exists):  {len(matched):>4}')
    print(f'  ❌ Missing (no metadata):      {len(missing):>4}')
    print(f'{"="*60}')

    if not missing:
        print('\n🎉 Every PDF has a matching metadata row — nothing to do!')
        return

    # ── 5. Write output CSV ───────────────────────────────────────────────
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'filename'])
        writer.writeheader()
        for filename, derived_title in missing:
            writer.writerow({
                'title':    derived_title,
                'filename': filename,
            })

    print(f'\n📋 Missing papers written to: {os.path.abspath(output_path)}')
    print(f'   Columns: title (for scraping), filename (for reference)\n')

    # Preview first 10
    preview = missing[:10]
    print('Preview (first 10):')
    for filename, title in preview:
        print(f'   • {title[:70]}')
    if len(missing) > 10:
        print(f'   … and {len(missing) - 10} more')


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Find PDFs with no metadata row in the merged CSV.')
    parser.add_argument(
        '--papers', default=DEFAULT_PAPERS_FOLDER,
        help=f'Folder containing downloaded PDFs (default: {DEFAULT_PAPERS_FOLDER})')
    parser.add_argument(
        '--csv', default=DEFAULT_CSV,
        help=f'Merged metadata CSV (default: {DEFAULT_CSV})')
    parser.add_argument(
        '--output', '-o', default=DEFAULT_OUTPUT,
        help=f'Output CSV for missing papers (default: {DEFAULT_OUTPUT})')
    parser.add_argument(
        '--threshold', type=float, default=FUZZY_THRESHOLD,
        help=f'Fuzzy match threshold 0–1 (default: {FUZZY_THRESHOLD})')
    args = parser.parse_args()

    print(f'\n🔍 Comparing PDFs in "{args.papers}" against "{args.csv}"')
    print(f'   Fuzzy threshold: {args.threshold}\n')

    find_missing(args.papers, args.csv, args.output)


if __name__ == '__main__':
    main()
