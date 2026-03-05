#!/usr/bin/env python3
"""
Paper Downloader v2
Search order per source: DOI first → title fallback if DOI fails
Sources: OpenAlex, Semantic Scholar, Unpaywall, ArXiv, CORE,
         Google Scholar, Publisher Direct, Sci-Hub
Output: downloaded_papers/
Resume: python download_papers.py papers.csv 150  ← start from row 150
"""

import csv
import os
import re
import time
import sys
import requests
from urllib.parse import quote_plus, quote, urljoin

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OUTPUT_FOLDER = "downloaded_papers"
YOUR_EMAIL    = "behantous@gmail.com"
TIMEOUT       = 30
DELAY         = 2        # seconds between papers
MIN_PDF_SIZE  = 5_000   # bytes — reject anything smaller (HTML error pages etc.)
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'mailto': YOUR_EMAIL,
}


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sanitize_filename(title):
    title = re.sub(r'[<>:"/\\|?*]', '', title).strip('. ')
    return title[:200] + '.pdf'

def clean_doi(doi):
    if not doi:
        return None
    return (doi
            .replace('https://doi.org/', '')
            .replace('http://doi.org/', '')
            .strip())

def is_valid_pdf(content: bytes) -> bool:
    """True only if content looks like a real PDF, not an HTML error page."""
    return len(content) >= MIN_PDF_SIZE and content[:4] == b'%PDF'

def fetch_pdf(url: str) -> bytes | None:
    """Download a URL; return bytes if it's a valid PDF, else None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True)
        if r.status_code == 200 and is_valid_pdf(r.content):
            return r.content
    except Exception:
        pass
    return None

def save_pdf(content: bytes, path: str) -> bool:
    try:
        with open(path, 'wb') as f:
            f.write(content)
        return True
    except Exception:
        return False

def already_downloaded(title: str) -> bool:
    path = os.path.join(OUTPUT_FOLDER, sanitize_filename(title))
    return os.path.exists(path) and os.path.getsize(path) >= MIN_PDF_SIZE

def word_overlap(a: str, b: str) -> float:
    """Fraction of words in `a` that also appear in `b`."""
    stopwords = {'a','an','the','for','on','in','with','to','of','and','or','at','by','from','is','are'}
    wa = set(a.lower().split()) - stopwords
    wb = set(b.lower().split()) - stopwords
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 1 — OPENALEX
# ══════════════════════════════════════════════════════════════════════════════

def openalex_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'https://api.openalex.org/works/https://doi.org/{doi_clean}',
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        best = data.get('best_oa_location') or {}
        if best.get('pdf_url'):
            return best['pdf_url']
        if data.get('open_access', {}).get('oa_url'):
            return data['open_access']['oa_url']
        for loc in data.get('locations', []):
            if loc.get('is_oa') and loc.get('pdf_url'):
                return loc['pdf_url']
    except Exception:
        pass
    return None

def openalex_title(title: str) -> str | None:
    try:
        r = requests.get(
            'https://api.openalex.org/works',
            params={'filter': f'title.search:{title}', 'per_page': 5},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for paper in r.json().get('results', []):
            if word_overlap(title, paper.get('title') or '') < 0.5:
                continue
            best = paper.get('best_oa_location') or {}
            if best.get('pdf_url'):
                return best['pdf_url']
            for loc in paper.get('locations', []):
                if loc.get('is_oa') and loc.get('pdf_url'):
                    return loc['pdf_url']
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 2 — SEMANTIC SCHOLAR
# ══════════════════════════════════════════════════════════════════════════════

def semantic_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_clean}',
            params={'fields': 'openAccessPdf,isOpenAccess'},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('isOpenAccess') and data.get('openAccessPdf'):
                return data['openAccessPdf'].get('url')
    except Exception:
        pass
    return None

def semantic_title(title: str) -> str | None:
    try:
        r = requests.get(
            'https://api.semanticscholar.org/graph/v1/paper/search',
            params={'query': title,
                    'fields': 'openAccessPdf,isOpenAccess,title',
                    'limit': 5},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for paper in r.json().get('data', []):
            if word_overlap(title, paper.get('title') or '') < 0.5:
                continue
            if paper.get('isOpenAccess') and paper.get('openAccessPdf'):
                return paper['openAccessPdf'].get('url')
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 3 — UNPAYWALL  (DOI only)
# ══════════════════════════════════════════════════════════════════════════════

def unpaywall_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'https://api.unpaywall.org/v2/{doi_clean}?email={YOUR_EMAIL}',
            timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get('is_oa') and data.get('best_oa_location'):
                return data['best_oa_location'].get('url_for_pdf')
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 4 — ARXIV  ★ NEW ★
# ══════════════════════════════════════════════════════════════════════════════

def _arxiv_id_from_xml(xml: str) -> str | None:
    m = re.search(r'<id>http://arxiv\.org/abs/([\d.]+v?\d*)</id>', xml)
    return m.group(1) if m else None

def arxiv_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'http://export.arxiv.org/api/query'
            f'?search_query=doi:{quote(doi_clean)}&max_results=1',
            timeout=TIMEOUT)
        if r.status_code == 200 and '<entry>' in r.text:
            arxiv_id = _arxiv_id_from_xml(r.text)
            if arxiv_id:
                return f'https://arxiv.org/pdf/{arxiv_id}.pdf'
    except Exception:
        pass
    return None

def arxiv_title(title: str) -> str | None:
    try:
        r = requests.get(
            f'http://export.arxiv.org/api/query'
            f'?search_query=ti:{quote(title)}&max_results=3',
            timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        entries = re.findall(r'<entry>(.*?)</entry>', r.text, re.DOTALL)
        for entry in entries:
            m = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
            if m and word_overlap(title, m.group(1)) >= 0.6:
                arxiv_id = _arxiv_id_from_xml(entry)
                if arxiv_id:
                    return f'https://arxiv.org/pdf/{arxiv_id}.pdf'
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 5 — CORE.AC.UK  ★ NEW ★
# ══════════════════════════════════════════════════════════════════════════════

def core_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'https://core.ac.uk/api-v2/articles/search/doi:{quote(doi_clean)}',
            params={'page': 1, 'pageSize': 3},
            timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('data', []):
                if item.get('downloadUrl'):
                    return item['downloadUrl']
    except Exception:
        pass
    return None

def core_title(title: str) -> str | None:
    try:
        r = requests.get(
            f'https://core.ac.uk/api-v2/articles/search/{quote(title)}',
            params={'page': 1, 'pageSize': 3},
            timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('data', []):
                if word_overlap(title, item.get('title') or '') >= 0.5:
                    if item.get('downloadUrl'):
                        return item['downloadUrl']
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 6 — GOOGLE SCHOLAR  (scraping, blocks easily)
# ══════════════════════════════════════════════════════════════════════════════

def google_scholar(query: str) -> str | None:
    try:
        h = HEADERS.copy()
        h['Accept'] = 'text/html,application/xhtml+xml'
        r = requests.get(
            f'https://scholar.google.com/scholar?q={quote_plus(query)}',
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
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 7 — PUBLISHER DIRECT  (DOI only)
# ══════════════════════════════════════════════════════════════════════════════

def publisher_direct(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            f'https://doi.org/{doi_clean}',
            headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
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
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 8 — SCI-HUB  (DOI only)
# ══════════════════════════════════════════════════════════════════════════════

def scihub_doi(doi_clean: str) -> str | None:
    for base in ['https://sci-hub.se', 'https://sci-hub.st', 'https://sci-hub.ru']:
        try:
            r = requests.get(
                f'{base}/{doi_clean}',
                headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
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
                        url = ('https:' + url) if url.startswith('//') else base + url
                    return url
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCES TABLE  — ordered by reliability
#  (label, doi_function, title_function)   None = not supported
# ══════════════════════════════════════════════════════════════════════════════

SOURCES = [
    ('OpenAlex',         openalex_doi,    openalex_title),
    ('Semantic Scholar', semantic_doi,    semantic_title),
    ('Unpaywall',        unpaywall_doi,   None),
    ('ArXiv',            arxiv_doi,       arxiv_title),
    ('CORE',             core_doi,        core_title),
    ('Google Scholar',   google_scholar,  google_scholar),   # same fn, different query
    ('Publisher Direct', publisher_direct,None),
    ('Sci-Hub',          scihub_doi,      None),
]


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DOWNLOAD LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def process_paper(doi: str, title: str, idx: int, total: int) -> bool:
    print(f"\n{'='*80}")
    print(f"[{idx}/{total}] {title[:72]}")
    print(f"DOI: {doi or '[none — title search only]'}")
    print(f"{'='*80}")

    if already_downloaded(title):
        print('  ✅ Already downloaded — skipping')
        return True

    doi_clean = clean_doi(doi)
    out_path  = os.path.join(OUTPUT_FOLDER, sanitize_filename(title))

    for label, doi_fn, title_fn in SOURCES:
        print(f'\n  🔎 {label}')
        pdf_url = None

        # ── Step 1: Try by DOI ─────────────────────────────────────────────
        if doi_clean and doi_fn:
            print(f'     → DOI ... ', end='', flush=True)
            try:
                pdf_url = doi_fn(doi_clean)
            except Exception:
                pdf_url = None
            print('found ✓' if pdf_url else 'not found')

        # ── Step 2: Fallback to title ──────────────────────────────────────
        if not pdf_url and title_fn:
            print(f'     → title ... ', end='', flush=True)
            try:
                # Google Scholar: use title as query; others use title arg
                pdf_url = title_fn(title)
            except Exception:
                pdf_url = None
            print('found ✓' if pdf_url else 'not found')

        # ── Step 3: Download & validate ────────────────────────────────────
        if pdf_url:
            print(f'     ⬇  {pdf_url[:72]}')
            content = fetch_pdf(pdf_url)
            if content and save_pdf(content, out_path):
                print(f'  ✅ SUCCESS via {label}')
                return True
            else:
                print(f'     ✗  Download failed or not a valid PDF')

        time.sleep(1)

    print(f'\n  ❌ FAILED — not available from any source')
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print('Usage: python download_papers.py <csv_file> [start_from]')
        print()
        print('CSV columns required: title   (doi is optional but helps)')
        print('Output folder:        downloaded_papers/')
        print()
        print('Examples:')
        print('  python download_papers.py argumentation.csv')
        print('  python download_papers.py damaged_papers.csv 150   ← resume from row 150')
        sys.exit(1)

    csv_file   = sys.argv[1]
    start_from = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if not os.path.exists(csv_file):
        print(f'❌ File not found: {csv_file}')
        sys.exit(1)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f'📁 Output folder: {os.path.abspath(OUTPUT_FOLDER)}')

    with open(csv_file, 'r', encoding='utf-8') as f:
        papers = list(csv.DictReader(f))

    total = len(papers)
    print(f'📚 {total} papers in CSV')
    if start_from > 1:
        print(f'📌 Resuming from #{start_from}')

    print(f'\n🔍 Sources (DOI first → title fallback):')
    for label, doi_fn, title_fn in SOURCES:
        has_title = '+ title fallback' if title_fn else 'DOI only'
        print(f'   • {label:<20} {has_title}')

    ok = failed = skipped = 0

    for i, row in enumerate(papers, 1):
        if i < start_from:
            continue

        title = (row.get('title') or '').strip()
        doi   = (row.get('doi')   or '').strip()

        if not title:
            print(f'\n[{i}/{total}] ⚠️  Skipping — no title')
            skipped += 1
            continue

        if process_paper(doi, title, i, total):
            ok += 1
        else:
            failed += 1

        if i < total:
            time.sleep(DELAY)

    print(f"\n{'='*80}")
    print('DOWNLOAD SUMMARY')
    print(f"{'='*80}")
    print(f'Total:      {total}')
    print(f'✅ Success: {ok}  ({ok/total*100:.1f}%)')
    print(f'❌ Failed:  {failed}')
    print(f'⏭  Skipped: {skipped}')
    print(f'\n📁 PDFs saved to: {os.path.abspath(OUTPUT_FOLDER)}')


if __name__ == '__main__':
    main()