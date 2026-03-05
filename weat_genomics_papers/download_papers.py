#!/usr/bin/env python3
"""
Paper Downloader — Wheat Genomics / Plant Science Edition
CSV columns: paper, title, pmid, doi, abstractText, year, journal, volume, issue, pages, author

Sources (in priority order):
  1. PubMed Central (PMC)       — NCBI's free full-text archive, best for biomedical/plant science
  2. Europe PMC                  — European mirror of PMC, often has papers PMC misses
  3. Unpaywall                   — Legal OA resolver, great for journal articles with DOIs
  4. OpenAlex                    — Broad OA index, good journal coverage
  5. CORE                        — Aggregates institutional repositories worldwide
  6. Wiley Online Library        — Major publisher of plant/genomics journals (public PDFs only)
  7. Oxford Academic (OUP)       — Publishes many genetics/genomics journals
  8. Springer / BioMed Central   — Open-access plant science content
  9. USDA / ARS PubAg            — US gov agricultural research, often OA
 10. Google Scholar              — Broad fallback (scraping, may block)
 11. Publisher Direct            — Follow DOI redirect and scrape PDF link
 12. Sci-Hub                     — Last resort

Output: downloaded_papers/
Resume: python download_papers.py papers.csv 150
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
CORE_API_KEY  = "5qo9HW0V2xUMXSNtY7fpKQJGvuzj1kCR"   # ← paste your CORE API key here
TIMEOUT       = 30
DELAY         = 2
MIN_PDF_SIZE  = 5_000
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
    return len(content) >= MIN_PDF_SIZE and content[:4] == b'%PDF'

def fetch_pdf(url: str, extra_headers: dict = None) -> bytes | None:
    h = HEADERS.copy()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.get(url, headers=h, timeout=TIMEOUT, allow_redirects=True)
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
    stopwords = {'a','an','the','for','on','in','with','to','of','and','or',
                 'at','by','from','is','are','its','into','using','between'}
    wa = set(a.lower().split()) - stopwords
    wb = set(b.lower().split()) - stopwords
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 1 — PUBMED CENTRAL (NCBI)
#  Best primary source for plant biology / genetics papers with a PMID.
# ══════════════════════════════════════════════════════════════════════════════

def pmc_pmid(pmid: str) -> str | None:
    """PMID → PMCID → PDF URL via NCBI OA service."""
    try:
        # Convert PMID to PMCID
        r = requests.get(
            'https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/',
            params={'ids': pmid, 'format': 'json'},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        records = r.json().get('records', [])
        if not records or 'pmcid' not in records[0]:
            return None
        pmcid = records[0]['pmcid']   # e.g. "PMC1234567"

        # Check OA service for direct PDF link
        oa = requests.get(
            'https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi',
            params={'id': pmcid},
            headers=HEADERS, timeout=TIMEOUT)
        if oa.status_code == 200:
            m = re.search(r'href="(https://[^"]+\.pdf)"', oa.text)
            if m:
                return m.group(1)

        # Fallback: standard PMC PDF URL pattern
        return f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/'
    except Exception:
        pass
    return None

def pmc_doi(doi_clean: str) -> str | None:
    """DOI → PMCID via NCBI (for rows where PMID is absent)."""
    try:
        r = requests.get(
            'https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/',
            params={'ids': doi_clean, 'idtype': 'doi', 'format': 'json'},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        records = r.json().get('records', [])
        if not records or 'pmcid' not in records[0]:
            return None
        pmcid = records[0]['pmcid']
        return f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/'
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 2 — EUROPE PMC
#  European counterpart of PMC; indexes many plant science journals separately.
# ══════════════════════════════════════════════════════════════════════════════

def europepmc_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
            params={'query': f'DOI:{doi_clean}', 'resulttype': 'core',
                    'format': 'json', 'pageSize': 3},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for result in r.json().get('resultList', {}).get('result', []):
            if result.get('isOpenAccess') == 'Y' and result.get('pmcid'):
                pmcid = result['pmcid']
                return f'https://europepmc.org/articles/{pmcid}/pdf/render'
    except Exception:
        pass
    return None

def europepmc_title(title: str) -> str | None:
    try:
        r = requests.get(
            'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
            params={'query': title, 'resulttype': 'core',
                    'format': 'json', 'pageSize': 5},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        for result in r.json().get('resultList', {}).get('result', []):
            if word_overlap(title, result.get('title') or '') < 0.5:
                continue
            if result.get('isOpenAccess') == 'Y' and result.get('pmcid'):
                pmcid = result['pmcid']
                return f'https://europepmc.org/articles/{pmcid}/pdf/render'
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 3 — UNPAYWALL
#  Legal OA resolver; very reliable for papers with DOIs from major publishers.
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
#  SOURCE 4 — OPENALEX
#  Broad open-access index with good coverage of plant/ag science journals.
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
#  SOURCE 5 — CORE.AC.UK
#  Aggregates institutional repositories; good for older/grey literature.
# ══════════════════════════════════════════════════════════════════════════════

def _core_headers() -> dict:
    """Auth header for CORE API v3."""
    h = HEADERS.copy()
    h['Authorization'] = f'Bearer {CORE_API_KEY}'
    return h

def core_doi(doi_clean: str) -> str | None:
    """CORE API v3 — search by DOI (authenticated, higher rate limits)."""
    try:
        r = requests.post(
            'https://api.core.ac.uk/v3/search/works',
            json={'q': f'doi:"{doi_clean}"', 'limit': 3},
            headers=_core_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('results', []):
                if item.get('downloadUrl'):
                    return item['downloadUrl']
                # v3 also exposes links array
                for link in item.get('links', []):
                    if link.get('type') == 'download' and link.get('url'):
                        return link['url']
    except Exception:
        pass
    return None

def core_title(title: str) -> str | None:
    """CORE API v3 — search by title (authenticated)."""
    try:
        r = requests.post(
            'https://api.core.ac.uk/v3/search/works',
            json={'q': title, 'limit': 5},
            headers=_core_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('results', []):
                if word_overlap(title, item.get('title') or '') < 0.5:
                    continue
                if item.get('downloadUrl'):
                    return item['downloadUrl']
                for link in item.get('links', []):
                    if link.get('type') == 'download' and link.get('url'):
                        return link['url']
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 6 — WILEY ONLINE LIBRARY
#  Publishes TAG (Theoretical and Applied Genetics), Plant Journal,
#  Molecular Plant Pathology, Plant Breeding, Plant Cell & Environment, etc.
# ══════════════════════════════════════════════════════════════════════════════

def wiley_doi(doi_clean: str) -> str | None:
    try:
        pdf_url = f'https://onlinelibrary.wiley.com/doi/pdfdirect/{doi_clean}'
        r = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True)
        if r.status_code == 200 and is_valid_pdf(r.content):
            return pdf_url
        # Fallback: scrape article page for PDF link
        page_url = f'https://onlinelibrary.wiley.com/doi/{doi_clean}'
        r2 = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT,
                          allow_redirects=True)
        if r2.status_code == 200:
            m = re.search(r'href="(/doi/pdfdirect/[^"]+)"', r2.text)
            if m:
                return 'https://onlinelibrary.wiley.com' + m.group(1)
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 7 — OXFORD ACADEMIC (OUP)
#  Publishes Journal of Experimental Botany, Genetics, G3, Bioinformatics, etc.
# ══════════════════════════════════════════════════════════════════════════════

def oxford_doi(doi_clean: str) -> str | None:
    try:
        page_url = f'https://academic.oup.com/doi/{doi_clean}'
        r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True)
        if r.status_code == 200:
            m = re.search(r'href="(/[^"]+\.pdf[^"]*)"', r.text, re.IGNORECASE)
            if m:
                return 'https://academic.oup.com' + m.group(1)
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 8 — SPRINGER / BIOMEDCENTRAL
#  SpringerOpen & BMC Plant Biology host many OA plant genomics papers.
# ══════════════════════════════════════════════════════════════════════════════

def springer_doi(doi_clean: str) -> str | None:
    try:
        pdf_url = f'https://link.springer.com/content/pdf/{quote(doi_clean)}.pdf'
        r = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True)
        if r.status_code == 200 and is_valid_pdf(r.content):
            return pdf_url
        # BioMedCentral Plant Biology pattern
        bmc_url = f'https://bmcplantbiol.biomedcentral.com/articles/{doi_clean}/pdf'
        r2 = requests.get(bmc_url, headers=HEADERS, timeout=TIMEOUT,
                          allow_redirects=True)
        if r2.status_code == 200 and is_valid_pdf(r2.content):
            return bmc_url
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 9 — USDA PubAg
#  USDA's open-access repository — excellent for wheat/agricultural research.
# ══════════════════════════════════════════════════════════════════════════════

def pubag_doi(doi_clean: str) -> str | None:
    try:
        r = requests.get(
            'https://pubag.nal.usda.gov/catalog.json',
            params={'q': doi_clean, 'per_page': 3},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('results', []):
                if item.get('download_url'):
                    return item['download_url']
    except Exception:
        pass
    return None

def pubag_title(title: str) -> str | None:
    try:
        r = requests.get(
            'https://pubag.nal.usda.gov/catalog.json',
            params={'q': title, 'per_page': 5},
            headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get('results', []):
                if word_overlap(title, item.get('title') or '') >= 0.5:
                    if item.get('download_url'):
                        return item['download_url']
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 10 — GOOGLE SCHOLAR  (broad fallback, scraping — may get blocked)
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
#  SOURCE 11 — PUBLISHER DIRECT  (DOI redirect + scrape)
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
#  SOURCE 12 — SCI-HUB  (last resort)
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
#  SOURCES TABLE
#  Sentinel 'PMC' = uses PMID lookup, handled separately in process_paper()
# ══════════════════════════════════════════════════════════════════════════════

SOURCES = [
    # label                  doi_fn              title_fn
    ('PubMed Central',       'PMC',              None),
    ('Europe PMC',           europepmc_doi,      europepmc_title),
    ('Unpaywall',            unpaywall_doi,      None),
    ('OpenAlex',             openalex_doi,       openalex_title),
    ('CORE',                 core_doi,           core_title),
    ('Wiley Online',         wiley_doi,          None),
    ('Oxford Academic',      oxford_doi,         None),
    ('Springer/BMC',         springer_doi,       None),
    ('USDA PubAg',           pubag_doi,          pubag_title),
    ('Google Scholar',       google_scholar,     google_scholar),
    ('Publisher Direct',     publisher_direct,   None),
    ('Sci-Hub',              scihub_doi,         None),
]


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DOWNLOAD LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def process_paper(doi: str, title: str, pmid: str, idx: int, total: int) -> bool:
    print(f"\n{'='*80}")
    print(f"[{idx}/{total}] {title[:72]}")
    print(f"DOI:  {doi or '[none]'}  |  PMID: {pmid or '[none]'}")
    print(f"{'='*80}")

    if already_downloaded(title):
        print('  ✅ Already downloaded — skipping')
        return True

    doi_clean = clean_doi(doi)
    out_path  = os.path.join(OUTPUT_FOLDER, sanitize_filename(title))

    for label, doi_fn, title_fn in SOURCES:
        print(f'\n  🔎 {label}')
        pdf_url = None

        # ── PubMed Central: PMID first, DOI fallback ──────────────────────
        if doi_fn == 'PMC':
            if pmid:
                print(f'     → PMID ... ', end='', flush=True)
                try:
                    pdf_url = pmc_pmid(pmid)
                except Exception:
                    pdf_url = None
                print('found ✓' if pdf_url else 'not found')
            if not pdf_url and doi_clean:
                print(f'     → DOI  ... ', end='', flush=True)
                try:
                    pdf_url = pmc_doi(doi_clean)
                except Exception:
                    pdf_url = None
                print('found ✓' if pdf_url else 'not found')

        else:
            # ── Step 1: Try by DOI ─────────────────────────────────────────
            if doi_clean and doi_fn:
                print(f'     → DOI ... ', end='', flush=True)
                try:
                    pdf_url = doi_fn(doi_clean)
                except Exception:
                    pdf_url = None
                print('found ✓' if pdf_url else 'not found')

            # ── Step 2: Fallback to title ──────────────────────────────────
            if not pdf_url and title_fn:
                print(f'     → title ... ', end='', flush=True)
                try:
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

        time.sleep(0.5)

    print(f'\n  ❌ FAILED — not available from any source')
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  CSV READER
# ══════════════════════════════════════════════════════════════════════════════

def read_csv(csv_file: str) -> list[dict]:
    papers = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items()}
            papers.append({
                'title':   norm.get('title',   ''),
                'doi':     norm.get('doi',     ''),
                'pmid':    norm.get('pmid',    ''),
                'year':    norm.get('year',    ''),
                'journal': norm.get('journal', ''),
                'author':  norm.get('author',  ''),
            })
    return papers


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print('Usage: python download_papers.py <csv_file> [start_from]')
        print()
        print('CSV columns: paper, title, pmid, doi, abstractText,')
        print('             year, journal, volume, issue, pages, author')
        print()
        print('Examples:')
        print('  python download_papers.py wheat_papers.csv')
        print('  python download_papers.py wheat_papers.csv 150   ← resume from row 150')
        sys.exit(1)

    csv_file   = sys.argv[1]
    start_from = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if not os.path.exists(csv_file):
        print(f'❌ File not found: {csv_file}')
        sys.exit(1)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    print(f'📁 Output folder: {os.path.abspath(OUTPUT_FOLDER)}')

    papers = read_csv(csv_file)
    total  = len(papers)
    print(f'📚 {total} papers in CSV')
    if start_from > 1:
        print(f'📌 Resuming from #{start_from}')

    print(f'\n🌾 Sources optimised for wheat genomics / plant science:')
    for label, doi_fn, title_fn in SOURCES:
        if doi_fn == 'PMC':
            tag = 'PMID + DOI lookup'
        elif title_fn:
            tag = 'DOI + title fallback'
        else:
            tag = 'DOI only'
        print(f'   • {label:<22} {tag}')

    ok = failed = skipped = 0

    for i, row in enumerate(papers, 1):
        if i < start_from:
            continue

        title = row['title']
        doi   = row['doi']
        pmid  = row['pmid']

        if not title:
            print(f'\n[{i}/{total}] ⚠️  Skipping — no title')
            skipped += 1
            continue

        if process_paper(doi, title, pmid, i, total):
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