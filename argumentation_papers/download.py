import os
import pandas as pd
import requests
import re
import time
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from multiprocessing import Pool, cpu_count
from functools import partial
from urllib.parse import urlparse

# ==================== CONFIG ====================
CSV_FILE = 'argumentation.csv'
DOWNLOAD_FOLDER = 'argumentation paper'
API_KEY = 'h2VQLBHlgD4wBNOuroywew'           # ← Replace with your real OpenAlex API key
MAX_WORKERS = min(8, cpu_count() * 2)   # Adjust: 8–16 usually good balance
REQUEST_TIMEOUT = 20                    # seconds
RATE_LIMIT_PAUSE = 0.4                  # small delay per request

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
session = requests.Session()            # reuse connection
session.headers.update({'User-Agent': 'OpenAlexPaperDownloader/1.0 (your.email@example.com)'})

if API_KEY and API_KEY != 'your_api_key_here':
    session.params['api_key'] = API_KEY
# ================================================


def sanitize_filename(title):
    if pd.isna(title) or not title:
        return None
    clean = re.sub(r'[^\w\s-]', '', str(title)).strip().replace(' ', '_')
    return (clean[:120] + '.pdf') if len(clean) > 120 else clean + '.pdf'


def is_valid_pdf(content: bytes) -> bool:
    if len(content) < 100:
        return False
    try:
        PdfReader(BytesIO(content))
        return True
    except (PdfReadError, ValueError, TypeError, Exception):
        return False


def download_one(row, download_folder: str):
    """Worker function — processes one row with OpenAlex ID lookup + enhanced title+DOI search fallback"""
    try:
        # Extract OpenAlex work ID (Wxxxxxxxx)
        work_id = str(row['id']).split('/')[-1] if '/' in str(row['id']) else str(row['id'])

        # Skip if not open access
        is_oa = row.get('open_access.is_oa', False)
        if isinstance(is_oa, str):
            is_oa = is_oa.lower() in ('true', '1', 'yes')
        if not is_oa:
            return work_id, "skipped (not open access)"

        # Prepare filename
        title = row.get('display_name', '').strip()
        filename = sanitize_filename(title) or f"{work_id}.pdf"
        target_path = Path(download_folder) / filename

        if target_path.exists():
            return work_id, f"already exists → {filename}"

        pdf_url = None

        # ── 1. Primary: lookup by work ID ──
        api_url = f"https://api.openalex.org/works/{work_id}"
        resp = session.get(api_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        best = data.get('best_oa_location') or {}
        pdf_url = best.get('pdf_url')

        if not pdf_url:
            landing = best.get('landing_page_url', '')
            if landing and landing.lower().endswith('.pdf'):
                pdf_url = landing

        # Optional: check other OA locations
        if not pdf_url:
            for loc in data.get('locations', []):
                if loc.get('is_oa', False):
                    pdf_url = loc.get('pdf_url')
                    if pdf_url:
                        break
                    landing_loc = loc.get('landing_page_url', '')
                    if landing_loc and landing_loc.lower().endswith('.pdf'):
                        pdf_url = landing_loc
                        break

        # ── 2. Fallback: search OpenAlex by DOI + title (exact) if still no PDF ──
        if not pdf_url and title and len(title) > 15:
            print(f"  [{work_id}] No PDF from ID → trying DOI+title search fallback")

            # Build precise search query — DOI first for exactness
            search_parts = []

            # Add DOI if available in CSV
            doi = row.get('doi', None)
            if pd.notna(doi) and isinstance(doi, str) and doi.strip() and '10.' in doi:
                # Clean DOI: remove https://doi.org/ prefix if present
                doi_clean = doi.replace('https://doi.org/', '').replace('http://doi.org/', '').strip()
                search_parts.append(f'doi:"{doi_clean}"')

            # Always add title as phrase (backup/exact match)
            search_parts.append(f'"{title}"')

            # Add year if available
            year = row.get('publication_year')
            if pd.notna(year):
                search_parts.append(f'publication_year:{int(year)}')

            # Add first author if available
            authors_raw = row.get('authorships.author.display_name', '')
            if authors_raw:
                first_author = str(authors_raw).split(',')[0].strip()
                if first_author:
                    search_parts.append(f'author.display_name:"{first_author}"')

            # Combine with AND
            search_query = ' AND '.join(search_parts)

            search_url = "https://api.openalex.org/works"
            params = {
                'search': search_query,
                'per-page': 1,                # Best/relevant match only
                'select': 'id,display_name,doi,best_oa_location',  # Useful fields
            }
            if API_KEY:
                params['api_key'] = API_KEY

            time.sleep(RATE_LIMIT_PAUSE + 0.6)  # Extra politeness for fallback
            search_resp = session.get(search_url, params=params, timeout=REQUEST_TIMEOUT)
            search_resp.raise_for_status()
            search_data = search_resp.json()

            if search_data.get('results') and len(search_data['results']) > 0:
                match = search_data['results'][0]
                match_title = match.get('display_name', '').strip()
                match_doi = match.get('doi', 'no DOI')
                print(f"  → Found match: {match_title[:70]}... (DOI: {match_doi})")

                best_match = match.get('best_oa_location') or {}
                pdf_url = best_match.get('pdf_url')

                if pdf_url:
                    print(f"  → PDF found via DOI+title search: {pdf_url}")
                else:
                    landing_match = best_match.get('landing_page_url', '')
                    if landing_match and landing_match.lower().endswith('.pdf'):
                        pdf_url = landing_match

        # ── Final check ──
        if not pdf_url:
            return work_id, "no pdf url found (after ID lookup + DOI+title fallback)"

        # ── Download the PDF ──
        time.sleep(RATE_LIMIT_PAUSE)
        pdf_resp = session.get(pdf_url, timeout=REQUEST_TIMEOUT, stream=True)
        pdf_resp.raise_for_status()

        content_type = pdf_resp.headers.get('Content-Type', '').lower()
        if 'pdf' not in content_type and 'octet-stream' not in content_type:
            return work_id, f"not pdf (Content-Type: {content_type}) from {pdf_url[:80]}..."

        content = pdf_resp.content

        if not is_valid_pdf(content):
            return work_id, "invalid / corrupted PDF"

        # Save
        with open(target_path, 'wb') as f:
            f.write(content)

        return work_id, f"OK → {filename}"

    except requests.RequestException as e:
        # Catch most network / HTTP / connection problems in one place
        msg = f"{type(e).__name__}: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            msg += f" | HTTP {e.response.status_code} {e.response.reason}"
            if e.response.url:
                msg += f" from {e.response.url[:120]}"
        elif hasattr(e, 'request') and e.request is not None and e.request.url:
            msg += f" (request to {e.request.url[:120]})"
        return work_id, msg

    except Exception as e:
        # Final safety net for unexpected things (e.g. JSON decode error, pypdf crash, filesystem issues)
        return work_id, f"unexpected error: {type(e).__name__} – {str(e)[:120]}"


def main():
    print(f"Reading {CSV_FILE} …")
    df = pd.read_csv(CSV_FILE)

    print(f"Processing {len(df)} papers using {MAX_WORKERS} workers …\n")

    worker = partial(download_one, download_folder=DOWNLOAD_FOLDER)

    results = []
    with Pool(processes=MAX_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(worker, [row for _, row in df.iterrows()]), 1):
            wid, msg = result
            print(f"[{i:4d}/{len(df)}] {wid:12} | {msg}")
            results.append(result)

        print("\nDone.")
    print("Summary:")

    from collections import Counter
    msgs = [msg for _, msg in results]

    counter = Counter(msgs)

    # Sort by count descending
    sorted_items = counter.most_common()

    for message, count in sorted_items:           # ← FIXED: message first (string), count second (int)
        display_msg = message
        # Only try len() if it's actually a string (extra safety)
        if isinstance(display_msg, str) and len(display_msg) > 90:
            display_msg = display_msg[:87] + "..."

        print(f"   {count:4d} × {display_msg}")

    # Stats
    total = len(results)
    success = sum(1 for m in msgs if isinstance(m, str) and m.startswith("OK"))
    skipped = sum(1 for m in msgs if isinstance(m, str) and ("skipped" in m or "already exists" in m))
    print(f"\nTotal processed: {total}")
    print(f"Successful downloads: {success} ({success/total*100:.1f}%)" if total > 0 else "Successful downloads: 0 (0.0%)")
    print(f"Skipped (already exists or not OA): {skipped}")


if __name__ == '__main__':
    main()