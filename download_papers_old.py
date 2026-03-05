#!/usr/bin/env python3
"""
Download Papers from Google Scholar using CSV input
"""

import csv
import os
import time
import requests
import sys
import random
from urllib.parse import urlparse

def download_papers_from_csv(csv_file, output_dir='downloaded_papers', start_from=1):
    """Download papers from CSV file using Google Scholar"""
    
    print(f"\n📖 Loading papers from: {csv_file}")
    
    # Read CSV file
    papers = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows without title
            if row.get('title') and row['title'].strip():
                papers.append({
                    'title': row['title'].strip(),
                    'year': row.get('year', '').strip(),
                    'venue': row.get('venue', '').strip(),
                    'doi': row.get('doi', '').strip()
                })
    
    total = len(papers)
    print(f"✓ Found {total} papers with titles to download")
    
    if start_from > 1:
        print(f"📌 Starting from paper #{start_from}")
    print()
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Track results
    downloaded = 0
    not_found = 0
    failed = 0
    
    # Try to import scholarly
    try:
        from scholarly import scholarly
        print("✓ Google Scholar library loaded\n")
    except ImportError:
        print("❌ ERROR: 'scholarly' library not found!")
        print("Install it with: pip install scholarly")
        sys.exit(1)
    
    # Process each paper
    for idx, paper in enumerate(papers, 1):
        # Skip if starting from a later index
        if idx < start_from:
            continue
        
        title = paper['title']
        year = paper['year']
        
        print(f"\n[{idx}/{total}] {title[:70]}...")
        if year:
            print(f"  📅 Year: {year}")
        
        # Check if already downloaded (check BEFORE any API calls)
        filename = f"{sanitize_filename(title)}.pdf"
        filepath = os.path.join(output_dir, filename)
        
        if os.path.exists(filepath):
            print(f"  ✅ Already downloaded: {filename}")
            downloaded += 1
            continue
        
        # Random delay to avoid rate limiting (Google Scholar is strict)
        time.sleep(random.uniform(5, 10))
        
        print(f"  🔍 Searching Google Scholar...")
        
        # Search Google Scholar
        pdf_urls = search_google_scholar(title, scholarly)
        
        if pdf_urls:
            print(f"    ✓ Found {len(pdf_urls)} potential PDF source(s)")
            
            print(f"  📥 Attempting download...")
            
            success = False
            for i, pdf_url in enumerate(pdf_urls, 1):
                pdf_url = convert_to_pdf_url(pdf_url)
                domain = get_domain(pdf_url)
                print(f"    [{i}/{len(pdf_urls)}] Trying {domain}...", end=" ")
                
                if download_pdf(pdf_url, filepath):
                    print(f"✓")
                    print(f"  ✅ Downloaded: {filename}")
                    downloaded += 1
                    success = True
                    break
                else:
                    print(f"✗")
                
                time.sleep(2)
            
            if not success:
                print(f"  ❌ All {len(pdf_urls)} download attempts failed")
                failed += 1
        else:
            print(f"  ❌ No PDF found (likely paywalled or not indexed)")
            not_found += 1
    
    # Print summary
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    print(f"Total papers:       {total}")
    print(f"Downloaded PDFs:    {downloaded} ({downloaded/total*100:.1f}%)")
    print(f"Failed downloads:   {failed}")
    print(f"No PDFs found:      {not_found}")
    print("="*60)
    
    if downloaded > 0:
        print(f"\n✓ {downloaded} PDFs saved to: {output_dir}/")


def search_google_scholar(title, scholarly):
    """Search Google Scholar for PDFs"""
    try:
        # Search for the paper
        search_query = scholarly.search_pubs(title)
        result = next(search_query, None)
        
        if not result:
            return []
        
        pdf_urls = []
        
        # Try to get eprint_url (usually free PDFs)
        if result.get('eprint_url'):
            pdf_urls.append(result['eprint_url'])
        
        # Try pub_url if it looks like a PDF
        if result.get('pub_url'):
            pub_url = result['pub_url']
            # Check if URL likely points to PDF
            if any(x in pub_url.lower() for x in ['.pdf', 'arxiv.org', 'biorxiv.org', 'medrxiv.org', 'researchgate.net']):
                pdf_urls.append(pub_url)
        
        return pdf_urls
        
    except StopIteration:
        return []
    except Exception as e:
        # Google Scholar may block if too many requests
        print(f"    ⚠️  Scholar error: {str(e)[:50]}")
        return []


def convert_to_pdf_url(url):
    """Convert various URLs to direct PDF links"""
    # ArXiv: convert abstract to PDF
    if 'arxiv.org/abs/' in url:
        return url.replace('/abs/', '/pdf/') + '.pdf'
    
    # bioRxiv/medRxiv
    if ('biorxiv.org/content/' in url or 'medrxiv.org/content/' in url) and '.full.pdf' not in url:
        if url.endswith('/'):
            return url + 'full.pdf'
        return url + '.full.pdf'
    
    # ResearchGate - try to get PDF
    if 'researchgate.net' in url and '/publication/' in url:
        # ResearchGate PDFs are often behind login, but sometimes work
        return url
    
    return url


def get_domain(url):
    """Extract domain from URL"""
    try:
        domain = urlparse(url).netloc
        # Remove www.
        return domain.replace('www.', '')
    except:
        return url[:30]


def sanitize_filename(filename):
    """Clean filename for saving"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    # Remove trailing period and spaces
    filename = filename.rstrip('. ')
    return filename[:150]


def download_pdf(url, filepath):
    """Download PDF with validation"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,*/*',
        }
        
        response = requests.get(url, headers=headers, timeout=30, stream=True, allow_redirects=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type and 'pdf' not in url.lower():
            return False
        
        # Download
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Validate file size
        if os.path.getsize(filepath) < 1000:
            os.remove(filepath)
            return False
        
        # Check PDF header
        with open(filepath, 'rb') as f:
            header = f.read(4)
            if header != b'%PDF':
                os.remove(filepath)
                return False
        
        return True
        
    except Exception as e:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python download_from_scholar.py <csv_file> [output_dir] [start_from]")
        print("\nExamples:")
        print("  python download_from_scholar.py papers.csv")
        print("  python download_from_scholar.py papers.csv my_pdfs/")
        print("  python download_from_scholar.py papers.csv downloaded_papers/ 7")
        print("\nCSV Format:")
        print("  Required columns: 'title'")
        print("  Optional columns: 'year', 'venue', 'doi', 'status'")
        print("\nNote: Install 'scholarly' library first:")
        print("  pip install scholarly")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'downloaded_papers'
    start_from = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    
    download_papers_from_csv(csv_file, output_dir, start_from)