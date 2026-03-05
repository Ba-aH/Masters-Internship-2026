#!/usr/bin/env python3
"""
Script to create a single CSV file containing both failed and skipped papers.
"""

import csv
import os
import sys
import re

OUTPUT_FOLDER = "downloaded_papers"

def sanitize_filename(title):
    """Convert title to valid filename (same as download script)."""
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    title = title.strip('. ')
    if len(title) > 200:
        title = title[:200]
    return title + ".pdf"

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_not_downloaded.py <original_csv_file>")
        print("\nThis script will create:")
        print("  - not_downloaded_papers.csv (failed + skipped papers)")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    
    if not os.path.exists(csv_file):
        print(f"Error: File '{csv_file}' not found")
        sys.exit(1)
    
    # Read the original CSV
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        papers = list(reader)
    
    # Add status column to fieldnames if not present
    if 'status' not in fieldnames:
        fieldnames = list(fieldnames) + ['status']
    
    not_downloaded = []
    successful = 0
    
    print(f"Analyzing {len(papers)} papers...")
    print("=" * 80)
    
    # Check each paper
    for i, row in enumerate(papers, 1):
        title = row.get('title', '').strip()
        doi = row.get('doi', '').strip()
        
        if not title or not doi:
            # Papers without title or DOI are skipped
            row['status'] = 'skipped - missing DOI/title'
            not_downloaded.append(row)
            continue
        
        # Generate filename (same logic as download script)
        filename = sanitize_filename(title)
        filepath = os.path.join(OUTPUT_FOLDER, filename)
        
        # Check if file exists
        if os.path.exists(filepath):
            successful += 1
        else:
            row['status'] = 'failed - not downloaded'
            not_downloaded.append(row)
        
        if i % 100 == 0:
            print(f"Processed {i}/{len(papers)} papers...")
    
    print(f"\nProcessed all {len(papers)} papers")
    print("=" * 80)
    
    # Write not downloaded papers CSV (failed + skipped)
    output_file = 'not_downloaded_papers.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(not_downloaded)
    
    print(f"\n✓ Created: {output_file} ({len(not_downloaded)} papers)")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total papers in CSV: {len(papers)}")
    print(f"✓ Successfully downloaded: {successful}")
    print(f"✗ Not downloaded (failed + skipped): {len(not_downloaded)}")
    
    # Calculate percentages
    if len(papers) > 0:
        success_pct = (successful / len(papers)) * 100
        fail_pct = (len(not_downloaded) / len(papers)) * 100
        
        print(f"\nSuccess rate: {success_pct:.1f}%")
        print(f"Not downloaded rate: {fail_pct:.1f}%")
    
    # Count failed vs skipped
    failed_count = sum(1 for p in not_downloaded if p['status'] == 'failed - not downloaded')
    skipped_count = sum(1 for p in not_downloaded if p['status'] == 'skipped - missing DOI/title')
    
    print(f"\nBreakdown of not downloaded:")
    print(f"  Failed: {failed_count}")
    print(f"  Skipped: {skipped_count}")
    
    print(f"\n💡 TIP: You can retry downloading with:")
    print(f"  python download_papers_simple.py {output_file}")
    print(f"\n💡 Or try the full version with more sources:")
    print(f"  python download_papers.py {output_file}")

if __name__ == "__main__":
    main()
