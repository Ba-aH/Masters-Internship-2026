#!/usr/bin/env python3
"""
Extract Damaged Papers from CSV
- Reads damaged_names_only.txt (output of check_pdfs.py)
- Matches against original argumentation CSV
- Outputs a new CSV with only the damaged papers (ready for re-download)
"""

import csv
import os
import sys


def sanitize_for_comparison(text):
    """Normalize text for fuzzy matching"""
    if not text:
        return ''
    # Lowercase, strip, remove special chars
    text = text.lower().strip()
    for char in '<>:"/\\|?*.,!()[]{}':
        text = text.replace(char, ' ')
    # Collapse spaces
    text = ' '.join(text.split())
    return text


def match_score(title_a, title_b):
    """Calculate word overlap score between two titles"""
    words_a = set(sanitize_for_comparison(title_a).split())
    words_b = set(sanitize_for_comparison(title_b).split())
    
    stopwords = {'a', 'an', 'the', 'for', 'on', 'in', 'with', 'to', 'of', 'and', 'or', 'at', 'by', 'from', 'is', 'are'}
    words_a -= stopwords
    words_b -= stopwords
    
    if not words_a or not words_b:
        return 0.0
    
    overlap = words_a & words_b
    # Score = overlap / smaller set (more strict)
    return len(overlap) / min(len(words_a), len(words_b))


def extract_damaged_entries(original_csv, damaged_txt, output_csv, threshold=0.75):
    """
    Match damaged PDF names to original CSV entries
    
    Args:
        original_csv: Path to full argumentation CSV
        damaged_txt:  Path to damaged_names_only.txt
        output_csv:   Output CSV path
        threshold:    Min match score to accept (0.0-1.0)
    """
    
    # Load damaged titles
    print(f"\n📄 Loading damaged list: {damaged_txt}")
    if not os.path.exists(damaged_txt):
        print(f"❌ File not found: {damaged_txt}")
        sys.exit(1)
    
    with open(damaged_txt, 'r', encoding='utf-8') as f:
        damaged_titles = [line.strip() for line in f if line.strip()]
    
    print(f"  ✓ {len(damaged_titles)} damaged papers to find")
    
    # Load original CSV
    print(f"\n📄 Loading original CSV: {original_csv}")
    if not os.path.exists(original_csv):
        print(f"❌ File not found: {original_csv}")
        sys.exit(1)
    
    original_rows = []
    with open(original_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            original_rows.append(row)
    
    print(f"  ✓ {len(original_rows)} total papers in CSV")
    print(f"  ✓ Columns: {fieldnames}")
    
    # Match damaged titles to CSV rows
    print(f"\n🔍 Matching damaged files to CSV entries (threshold: {threshold*100:.0f}%)...")
    
    matched = []
    unmatched = []
    
    for damaged_title in damaged_titles:
        best_row = None
        best_score = 0.0
        best_csv_title = ''
        
        for row in original_rows:
            csv_title = row.get('title', '')
            if not csv_title:
                continue
            
            score = match_score(damaged_title, csv_title)
            
            if score > best_score:
                best_score = score
                best_row = row
                best_csv_title = csv_title
        
        if best_row and best_score >= threshold:
            matched.append({
                'row': best_row,
                'damaged_title': damaged_title,
                'csv_title': best_csv_title,
                'score': best_score
            })
        else:
            unmatched.append({
                'damaged_title': damaged_title,
                'best_score': best_score,
                'best_csv_title': best_csv_title
            })
    
    # Write output CSV (same format as input, no status column)
    print(f"\n💾 Writing output CSV: {output_csv}")
    
    # Determine output columns (exclude 'status' column if present)
    out_fieldnames = [f for f in (fieldnames or []) if f.lower() != 'status']
    
    # Ensure standard columns exist
    for col in ['paper', 'doi', 'title', 'year', 'venue']:
        if col not in out_fieldnames:
            out_fieldnames.append(col)
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames, extrasaction='ignore')
        writer.writeheader()
        for match in matched:
            writer.writerow(match['row'])
    
    # Print results
    print(f"\n{'='*70}")
    print(f"RESULTS")
    print(f"{'='*70}")
    print(f"Damaged files:    {len(damaged_titles)}")
    print(f"✅ Matched:       {len(matched)} ({len(matched)/len(damaged_titles)*100:.1f}%)")
    print(f"❌ Unmatched:     {len(unmatched)}")
    print(f"{'='*70}")
    
    if matched:
        print(f"\n✅ MATCHED (sample of first 10):")
        for m in matched[:10]:
            print(f"  [{m['score']*100:.0f}%] {m['damaged_title'][:55]}")
    
    if unmatched:
        print(f"\n❌ UNMATCHED (not found in CSV):")
        for u in unmatched:
            print(f"  Score {u['best_score']*100:.0f}% | {u['damaged_title'][:55]}")
            if u['best_csv_title']:
                print(f"          Best guess: {u['best_csv_title'][:55]}")
    
    print(f"\n📁 Output saved to: {output_csv}")
    print(f"   → Feed this file into download_from_scholar.py to re-download!")
    
    return matched, unmatched


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python extract_damaged_from_csv.py <original_csv> <damaged_txt> <output_csv> [threshold]")
        print("\nExamples:")
        print("  python extract_damaged_from_csv.py argumentation.csv damaged_names_only.txt damaged_papers.csv")
        print("  python extract_damaged_from_csv.py argumentation.csv damaged_names_only.txt damaged_papers.csv 0.8")
        print("\nArguments:")
        print("  original_csv  - Your full argumentation CSV file")
        print("  damaged_txt   - damaged_names_only.txt from check_pdfs.py")
        print("  output_csv    - Output CSV filename")
        print("  threshold     - Match strictness 0.0-1.0 (default: 0.75)")
        print("\nWorkflow:")
        print("  1. python check_pdfs.py argumentation_papers/")
        print("  2. python extract_damaged_from_csv.py argumentation.csv damaged_names_only.txt damaged_papers.csv")
        print("  3. python download_from_scholar.py damaged_papers.csv re_downloaded/")
        sys.exit(1)
    
    original_csv = sys.argv[1]
    damaged_txt  = sys.argv[2]
    output_csv   = sys.argv[3]
    threshold    = float(sys.argv[4]) if len(sys.argv) > 4 else 0.75
    
    extract_damaged_entries(original_csv, damaged_txt, output_csv, threshold)
