#!/usr/bin/env python3
"""
Paper Downloader v5 - Maximum Coverage with Zenodo & BASE
Search order: DOI first → title fallback
Sources: OpenAlex, Semantic Scholar, Unpaywall, ArXiv, CORE (with key),
         Europe PMC, BASE, Zenodo, Google Scholar, Publisher Direct, Sci-Hub
Output: downloaded_papers/
Resume: python download_papers.py argumentation.csv 150
"""

import csv
import os
import re
import time
import sys
import random
import logging
import requests
from urllib.parse import quote_plus, quote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential
from fake_useragent import UserAgent

try:
    from PyPDF2 import PdfReader
    from io import BytesIO
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False
    print("Warning: PyPDF2 not installed → weaker PDF validation.")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OUTPUT_FOLDER = "downloaded_papers"
YOUR_EMAIL    = "behantous@gmail.com"
CORE_API_KEY  = "5qo9HW0V2xUMXSNtY7fpKQJGvuzj1kCR"
TIMEOUT       = 30
BASE_DELAY    = 2.8
MAX_WORKERS   = 5
MIN_PDF_SIZE  = 5_000
LOG_FILE      = 'download_log.txt'
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

ua = UserAgent()
SESSION = requests.Session()

def get_headers():
    return {'User-Agent': ua.random, 'mailto': YOUR_EMAIL}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def sanitize_filename(title):
    title = re.sub(r'[<>:"/\\|?*]', '', title).strip('. ')
    return title[:200] + '.pdf'

def clean_doi(doi):
    if not doi:
        return None
    return doi.replace('https://doi.org/', '').replace('http://doi.org/', '').strip()

def is_valid_pdf(content: bytes) -> bool:
    if len(content) < MIN_PDF_SIZE or content[:4] != b'%PDF':
        return False
    if PDF_EXTRACTION_AVAILABLE:
        try:
            reader = PdfReader(BytesIO(content))
            _ = len(reader.pages)
            return True
        except Exception:
            return False
    return True

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_pdf(url: str) -> bytes | None:
    try:
        r = SESSION.get(url, headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200 and is_valid_pdf(r.content):
            return r.content
    except Exception as e:
        logging.error(f"Fetch failed: {url} - {e}")
    return None

def save_pdf(content: bytes, path: str) -> bool:
    try:
        with open(path, 'wb') as f:
            f.write(content)
        logging.info(f"Saved: {path}")
        return True
    except Exception as e:
        logging.error(f"Save failed: {path} - {e}")
        return False

def already_downloaded(title: str) -> bool:
    path = os.path.join(OUTPUT_FOLDER, sanitize_filename(title))
    return os.path.exists(path) and os.path.getsize(path) >= MIN_PDF_SIZE

def word_overlap(a: str, b: str) -> float:
    stopwords = {'a','an','the','for','on','in','with','to','of','and','or','at','by','from','is','are'}
    wa = set(a.lower().split()) - stopwords
    wb = set(b.lower().split()) - stopwords
    if not wa: return 0.0
    return len(wa & wb) / len(wa)

# ─── SOURCE FUNCTIONS (ALL DEFINED BEFORE SOURCES LIST) ───────────────────────

def openalex_doi(doi_clean: str) -> str | None:
    try:
        r = SESSION.get(f'https://api.openalex.org/works/https://doi.org/{doi_clean}',
                        headers=get_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            best = data.get('best_oa_location') or {}
            if best.get('pdf_url'):
                return best['pdf_url']
            for loc in data.get('locations', []):
                if loc.get('is_oa') and loc.get('pdf_url'):
                    return loc['pdf_url']
    except:
        pass
    return None

def openalex_title(title: str) -> str | None:
    try:
        r = SESSION.get('https://api.openalex.org/works',
                        params={'filter': f'title.search:{quote(title)}', 'per_page': 5},
                        headers=get_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            for paper in r.json().get('results', []):
                if word_overlap(title, paper.get('title') or '') < 0.5:
                    continue
                best = paper.get('best_oa_location') or {}
                if best.get('pdf_url'):
                    return best['pdf_url']
    except:
        pass
    return None

def semantic_doi(doi_clean: str) -> str | None:
    try:
        r = SESSION.get(f'https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_clean}',
                        params={'fields': 'openAccessPdf,isOpenAccess'},
                        headers=get_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('isOpenAccess') and data.get('openAccessPdf'):
                return data['openAccessPdf'].get('url')
    except:
        pass
    return None

def semantic_title(title: str) -> str | None:
    try:
        r = SESSION.get('https://api.semanticscholar.org/graph/v1/paper/search',
                        params={'query': title, 'fields': 'openAccessPdf,isOpenAccess,title', 'limit': 5},
                        headers=get_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            for paper in r.json().get('data', []):
                if word_overlap(title, paper.get('title') or '') < 0.5:
                    continue
                if paper.get('isOpenAccess') and paper.get('openAccessPdf'):
                    return paper['openAccessPdf'].get('url')
    except:
        pass
    return None

def unpaywall_doi(doi_clean: str) -> str | None:
    try:
        r = SESSION.get(f'https://api.unpaywall.org/v2/{doi_clean}?email={YOUR_EMAIL}',
                        timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('is_oa') and data.get('best_oa_location'):
                return data['best_oa_location'].get('url_for_pdf')
    except:
        pass
    return None

def arxiv_doi(doi_clean: str) -> str | None:
    try:
        r = SESSION.get(f'http://export.arxiv.org/api/query?search_query=doi:{quote(doi_clean)}&max_results=1',
                        timeout=TIMEOUT)
        if r.status_code == 200 and '<entry>' in r.text:
            m = re.search(r'<id>http://arxiv\.org/abs/([\d.]+v?\d*)</id>', r.text)
            if m:
                arxiv_id = m.group(1)
                return f'https://arxiv.org/pdf/{arxiv_id}.pdf'
    except:
        pass
    return None

def arxiv_title(title: str) -> str | None:
    try:
        r = SESSION.get(f'http://export.arxiv.org/api/query?search_query=ti:{quote(title)}&max_results=3',
                        timeout=TIMEOUT)
        if r.status_code == 200:
            entries = re.findall(r'<entry>(.*?)</entry>', r.text, re.DOTALL)
            for entry in entries:
                m = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
                if m and word_overlap(title, m.group(1)) >= 0.6:
                    m_id = re.search(r'<id>http://arxiv\.org/abs/([\d.]+v?\d*)</id>', entry)
                    if m_id:
                        return f'https://arxiv.org/pdf/{m_id.group(1)}.pdf'
    except:
        pass
    return None

def core_doi(doi_clean: str) -> str | None:
    try:
        headers = {'Authorization': f'Bearer {CORE_API_KEY}'}
        r = SESSION.get(f'https://api.core.ac.uk/v3/works/{quote(doi_clean)}',
                        headers=headers, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('downloadUrl'):
                return data['downloadUrl']
    except:
        pass
    return None

def core_title(title: str) -> str | None:
    try:
        headers = {'Authorization': f'Bearer {CORE_API_KEY}'}
        params = {'q': f'title:"{quote(title)}"', 'pageSize': 3}
        r = SESSION.get('https://api.core.ac.uk/v3/search/works',
                        params=params, headers=headers, timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('results', []):
                if word_overlap(title, item.get('title') or '') >= 0.5:
                    if item.get('downloadUrl'):
                        return item['downloadUrl']
    except:
        pass
    return None

def base_doi(doi_clean: str) -> str | None:
    try:
        query = f'dcdoi:"{doi_clean}"'
        params = {'func': 'search', 'format': 'json', 'hits': 1, 'query': query}
        r = SESSION.get("https://api.base-search.net/cgi-bin/BaseSearch/rsearch",
                        params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            docs = data.get('response', {}).get('docs', [])
            if docs:
                doc = docs[0]
                if 'dcformat' in doc and 'application/pdf' in doc['dcformat']:
                    return doc.get('dclink')
                if 'dclink' in doc:
                    links = doc['dclink'] if isinstance(doc['dclink'], list) else [doc['dclink']]
                    for link in links:
                        if 'pdf' in str(link).lower():
                            return link
    except:
        pass
    return None

def base_title(title: str) -> str | None:
    try:
        query = f'dctitle:"{quote(title)}"'
        params = {'func': 'search', 'format': 'json', 'hits': 3, 'query': query}
        r = SESSION.get("https://api.base-search.net/cgi-bin/BaseSearch/rsearch",
                        params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            docs = data.get('response', {}).get('docs', [])
            for doc in docs:
                if word_overlap(title, doc.get('dctitle', '') or '') >= 0.5:
                    if 'dcformat' in doc and 'application/pdf' in doc['dcformat']:
                        return doc.get('dclink')
                    if 'dclink' in doc:
                        links = doc['dclink'] if isinstance(doc['dclink'], list) else [doc['dclink']]
                        for link in links:
                            if 'pdf' in str(link).lower():
                                return link
    except:
        pass
    return None

def zenodo_doi(doi_clean: str) -> str | None:
    try:
        params = {'q': f'doi:"{doi_clean}"', 'size': 1}
        r = SESSION.get("https://zenodo.org/api/records", params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            hits = r.json().get('hits', {}).get('hits', [])
            if hits:
                record = hits[0]
                for file in record.get('files', []):
                    if file.get('type') == 'pdf' or '.pdf' in file.get('key', '').lower():
                        return file.get('links', {}).get('self')
    except:
        pass
    return None

def zenodo_title(title: str) -> str | None:
    try:
        params = {'q': f'title:"{quote(title)}"', 'size': 3}
        r = SESSION.get("https://zenodo.org/api/records", params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            hits = r.json().get('hits', {}).get('hits', [])
            for record in hits:
                rec_title = record.get('metadata', {}).get('title', '')
                if word_overlap(title, rec_title) >= 0.6:
                    for file in record.get('files', []):
                        if file.get('type') == 'pdf' or '.pdf' in file.get('key', '').lower():
                            return file.get('links', {}).get('self')
    except:
        pass
    return None

def google_scholar(query: str) -> str | None:
    try:
        h = get_headers()
        h['Accept'] = 'text/html'
        r = SESSION.get(f'https://scholar.google.com/scholar?q={quote_plus(query)}',
                        headers=h, timeout=TIMEOUT)
        if r.status_code == 200:
            for pat in [
                r'href="([^"]+\.pdf)"',
                r'data-clk-atid="[^"]*"[^>]+href="([^"]+)"[^>]*>\[PDF\]',
            ]:
                for url in re.findall(pat, r.text, re.IGNORECASE):
                    if 'pdf' in url.lower():
                        if url.startswith('//'):
                            url = 'https:' + url
                        if url.startswith('http'):
                            return url
    except:
        pass
    return None

def publisher_direct(doi_clean: str) -> str | None:
    try:
        r = SESSION.get(f'https://doi.org/{doi_clean}',
                        headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return None
        if 'application/pdf' in r.headers.get('Content-Type', ''):
            return f'https://doi.org/{doi_clean}'
        for pat in [r'href="([^"]*\.pdf[^"]*)"',
                    r'citation_pdf_url"\s+content="([^"]+)"']:
            m = re.search(pat, r.text, re.IGNORECASE)
            if m:
                url = m.group(1)
                return url if url.startswith('http') else urljoin(r.url, url)
    except:
        pass
    return None

def scihub_doi(doi_clean: str) -> str | None:
    mirrors = ['https://sci-hub.se', 'https://sci-hub.st', 'https://sci-hub.ru']
    for base in mirrors:
        try:
            r = SESSION.get(f'{base}/{doi_clean}',
                            headers=get_headers(), timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            if 'application/pdf' in r.headers.get('Content-Type', ''):
                return f'{base}/{doi_clean}'
            for pat in [
                r'<embed[^>]+src="([^"]+\.pdf[^"]*)"',
                r'<iframe[^>]+src="([^"]+\.pdf[^"]*)"',
                r"location\.href='([^']+\.pdf[^']*)'",
            ]:
                m = re.search(pat, r.text)
                if m:
                    url = m.group(1)
                    if not url.startswith('http'):
                        url = base + url if not url.startswith('//') else 'https:' + url
                    return url
        except:
            continue
    return None

# ─── SOURCES LIST (NOW SAFE) ──────────────────────────────────────────────────

SOURCES = [
    ('OpenAlex',         openalex_doi,    openalex_title),
    ('Semantic Scholar', semantic_doi,    semantic_title),
    ('Unpaywall',        unpaywall_doi,   None),
    ('ArXiv',            arxiv_doi,       arxiv_title),
    ('CORE',             core_doi,        core_title),
    ('BASE',             base_doi,        base_title),
    ('Zenodo',           zenodo_doi,      zenodo_title),
    ('Google Scholar',   google_scholar,  google_scholar),
    ('Publisher Direct', publisher_direct,None),
    ('Sci-Hub',          scihub_doi,      None),
]

# ─── PROCESS PAPER ────────────────────────────────────────────────────────────

def process_paper(row, idx, total):
    title = row.get('title', '').strip()
    doi = row.get('doi', '').strip()
    if not title:
        logging.info(f'[{idx}/{total}] Skipping — no title')
        return False, 'skipped'

    print(f"\n[{idx}/{total}] {title[:72]}")
    logging.info(f"Processing: {title} (DOI: {doi})")

    if already_downloaded(title):
        print(' ✅ Already downloaded')
        return True, 'success'

    doi_clean = clean_doi(doi)
    out_path = os.path.join(OUTPUT_FOLDER, sanitize_filename(title))

    for label, doi_fn, title_fn in SOURCES:
        print(f' 🔎 {label}')
        pdf_url = None

        if doi_clean and doi_fn:
            pdf_url = doi_fn(doi_clean)
        if not pdf_url and title_fn:
            pdf_url = title_fn(title)

        if pdf_url:
            print(f' ⬇ {pdf_url[:72]}')
            content = fetch_pdf(pdf_url)
            if content and save_pdf(content, out_path):
                print(f' ✅ SUCCESS via {label}')
                logging.info(f'Success: {title} via {label}')
                return True, 'success'
            else:
                print(' ✗ Failed')
        time.sleep(random.uniform(1.0, 2.0))

    print(' ❌ FAILED')
    logging.warning(f'Failed: {title}')
    return False, 'failed'

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('Usage: python download_papers.py <csv_file> [start_from]')
        sys.exit(1)

    csv_file = sys.argv[1]
    start_from = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if not os.path.exists(csv_file):
        print(f'❌ File not found: {csv_file}')
        sys.exit(1)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    with open(csv_file, 'r', encoding='utf-8') as f:
        papers = list(csv.DictReader(f))

    total = len(papers)
    print(f'📚 {total} papers')
    if start_from > 1:
        print(f'📌 Resuming from #{start_from}')

    print('\n🔍 Sources:')
    for label, _, title_fn in SOURCES:
        has_title = '+ fallback' if title_fn else 'DOI only'
        print(f' • {label:<20} {has_title}')

    success = failed = skipped = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i, row in enumerate(papers, 1):
            if i < start_from:
                continue
            futures.append(executor.submit(process_paper, row, i, total))
            time.sleep(random.uniform(BASE_DELAY, BASE_DELAY + 3))

        for future in as_completed(futures):
            ok, status = future.result()
            if status == 'success':
                success += 1
            elif status == 'failed':
                failed += 1
            else:
                skipped += 1

    print(f"\n{'='*80}")
    print(f'Total: {total}')
    print(f'✅ Success: {success} ({success/total*100:.1f}%)')
    print(f'❌ Failed: {failed}')
    print(f'⏭ Skipped: {skipped}')
    print(f'📁 PDFs: {os.path.abspath(OUTPUT_FOLDER)}')
    print(f'📝 Log: {LOG_FILE}')

if __name__ == '__main__':
    main()