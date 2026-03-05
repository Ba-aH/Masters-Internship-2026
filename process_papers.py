#!/usr/bin/env python3
"""
Process argumentation papers:
1. Scans all PDFs in argumentation_papers/ and splits them into healthy/damaged
2. Matches each group to rows in argumentation.csv by fuzzy title matching
3. Moves healthy PDFs → argumentation_papers_clean/  + writes argumentation_clean.csv
4. Moves damaged PDFs → argumentation_papers_damaged/ + writes argumentation_damaged.csv

Usage:
    python process_papers.py
    python process_papers.py --papers my_papers/ --csv my_data.csv
    python process_papers.py --copy   # copy instead of move
"""

import os
import re
import csv
import shutil
import argparse
from pathlib import Path


# ── Config (edit these or use command-line args) ─────────────────────────────
DEFAULT_PAPERS_FOLDER   = "argumentation_papers/argumentation_papers_clean"
DEFAULT_CSV             = "argumentation.csv"
DEFAULT_CLEAN_FOLDER    = "argumentation_papers_clean"
DEFAULT_CLEAN_CSV       = "argumentation_clean.csv"
DEFAULT_DAMAGED_FOLDER  = "argumentation_papers_damaged"
DEFAULT_DAMAGED_CSV     = "argumentation_damaged.csv"
# ─────────────────────────────────────────────────────────────────────────────


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/spaces for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_valid_pdf(filepath: str) -> bool:
    """Quick check: valid PDF header and size > 1KB."""
    try:
        if os.path.getsize(filepath) < 1000:
            return False
        with open(filepath, "rb") as f:
            header = f.read(16).lstrip()   # strip leading whitespace/newlines
            return header[:4] == b"%PDF"
    except Exception:
        return False


def load_csv(csv_path: str) -> list[dict]:
    """Load argumentation.csv into a list of dicts."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_title_index(rows: list[dict]) -> dict[str, dict]:
    """Build a normalized-title → row lookup."""
    index = {}
    for row in rows:
        title = row.get("title", "")
        key = normalize(title)
        if key:
            index[key] = row
    return index


def find_best_match(norm_filename: str, title_index: dict[str, dict]) -> dict | None:
    """
    Try exact normalized match first, then token-overlap fallback.
    Returns the matching row or None.
    """
    # 1. Exact match
    if norm_filename in title_index:
        return title_index[norm_filename]

    # 2. Token-overlap match (Jaccard-like)
    fn_tokens = set(norm_filename.split())
    if len(fn_tokens) < 3:
        return None   # too short to match reliably

    best_row, best_score = None, 0.0
    for key, row in title_index.items():
        key_tokens = set(key.split())
        intersection = fn_tokens & key_tokens
        union = fn_tokens | key_tokens
        score = len(intersection) / len(union)
        if score > best_score:
            best_score = score
            best_row = row

    # Require at least 80% token overlap to accept
    return best_row if best_score >= 0.80 else None


def process_group(pdf_files, papers_folder, dest_folder, title_index,
                  csv_fieldnames, move_fn, label):
    """Move a group of PDFs to dest_folder and collect their matching CSV rows."""
    os.makedirs(dest_folder, exist_ok=True)

    matched_rows   = []
    no_match_files = []

    for pdf_file in pdf_files:
        filepath = os.path.join(papers_folder, pdf_file)

        # Derive title from filename
        raw_title  = Path(pdf_file).stem.replace("_", " ")
        norm_title = normalize(raw_title)

        # Match to CSV
        row = find_best_match(norm_title, title_index)
        if row is not None:
            matched_rows.append(row)
        else:
            no_match_files.append(pdf_file)

        # Move/copy regardless of CSV match
        dest = os.path.join(dest_folder, pdf_file)
        move_fn(filepath, dest)

    return matched_rows, no_match_files


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Split argumentation PDFs into clean/damaged, match to CSV")
    parser.add_argument("--papers",       default=DEFAULT_PAPERS_FOLDER,
                        help=f"Folder with PDFs (default: {DEFAULT_PAPERS_FOLDER})")
    parser.add_argument("--csv",          default=DEFAULT_CSV,
                        help=f"Input CSV file (default: {DEFAULT_CSV})")
    parser.add_argument("--clean-out",    default=DEFAULT_CLEAN_FOLDER,
                        help=f"Destination for healthy PDFs (default: {DEFAULT_CLEAN_FOLDER})")
    parser.add_argument("--clean-csv",    default=DEFAULT_CLEAN_CSV,
                        help=f"Output CSV for healthy papers (default: {DEFAULT_CLEAN_CSV})")
    parser.add_argument("--damaged-out",  default=DEFAULT_DAMAGED_FOLDER,
                        help=f"Destination for damaged PDFs (default: {DEFAULT_DAMAGED_FOLDER})")
    parser.add_argument("--damaged-csv",  default=DEFAULT_DAMAGED_CSV,
                        help=f"Output CSV for damaged papers (default: {DEFAULT_DAMAGED_CSV})")
    parser.add_argument("--copy",         action="store_true",
                        help="Copy files instead of moving them")
    args = parser.parse_args()

    move_fn = shutil.copy2 if args.copy else shutil.move

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not os.path.isdir(args.papers):
        print(f"❌ Papers folder not found: {args.papers}")
        return
    if not os.path.isfile(args.csv):
        print(f"❌ CSV file not found: {args.csv}")
        return

    # ── Load CSV ──────────────────────────────────────────────────────────────
    rows = load_csv(args.csv)
    title_index    = build_title_index(rows)
    csv_fieldnames = list(rows[0].keys()) if rows else []
    print(f"📄 Loaded {len(rows)} rows from {args.csv}")

    # ── Scan & split PDFs ─────────────────────────────────────────────────────
    all_pdfs = sorted(f for f in os.listdir(args.papers) if f.lower().endswith(".pdf"))
    print(f"📂 Found {len(all_pdfs)} PDF files in '{args.papers}'")

    healthy_pdfs = []
    damaged_pdfs = []
    for pdf_file in all_pdfs:
        filepath = os.path.join(args.papers, pdf_file)
        if is_valid_pdf(filepath):
            healthy_pdfs.append(pdf_file)
        else:
            damaged_pdfs.append(pdf_file)

    print(f"   ✅ Healthy : {len(healthy_pdfs)}")
    print(f"   ❌ Damaged : {len(damaged_pdfs)}")

    # ── Process healthy ───────────────────────────────────────────────────────
    print(f"\n➡️  Moving healthy PDFs → '{args.clean_out}' ...")
    clean_rows, clean_no_match = process_group(
        healthy_pdfs, args.papers, args.clean_out,
        title_index, csv_fieldnames, move_fn, "clean"
    )
    write_csv(args.clean_csv, csv_fieldnames, clean_rows)

    # ── Process damaged ───────────────────────────────────────────────────────
    print(f"➡️  Moving damaged PDFs → '{args.damaged_out}' ...")
    damaged_rows, damaged_no_match = process_group(
        damaged_pdfs, args.papers, args.damaged_out,
        title_index, csv_fieldnames, move_fn, "damaged"
    )
    write_csv(args.damaged_csv, csv_fieldnames, damaged_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    action = "Copied" if args.copy else "Moved"
    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Total PDFs scanned    : {len(all_pdfs)}")
    print(f"")
    print(f"✅ CLEAN  ({len(healthy_pdfs)} files) → '{args.clean_out}'")
    print(f"   Matched to CSV     : {len(clean_rows)}")
    print(f"   No CSV match       : {len(clean_no_match)}")
    print(f"   Output CSV         : {args.clean_csv}")
    print(f"")
    print(f"❌ DAMAGED ({len(damaged_pdfs)} files) → '{args.damaged_out}'")
    print(f"   Matched to CSV     : {len(damaged_rows)}")
    print(f"   No CSV match       : {len(damaged_no_match)}")
    print(f"   Output CSV         : {args.damaged_csv}")

    for label, no_match in [("clean", clean_no_match), ("damaged", damaged_no_match)]:
        if no_match:
            print(f"\n⚠️  {label.capitalize()} PDFs with no CSV match ({len(no_match)}):")
            for f in no_match:
                print(f"   - {f}")

    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
