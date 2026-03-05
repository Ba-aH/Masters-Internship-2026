import pandas as pd
import requests
import time
import re
import urllib.parse
import os
from pathlib import Path
from tqdm import tqdm

try:
    from PyPDF2 import PdfReader
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False
    print("Warning: PyPDF2 not installed → PDF abstract extraction disabled. Install with: pip install PyPDF2")

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────
EMAIL = "behantous@gmail.com"
CORE_API_KEY = "5qo9HW0V2xUMXSNtY7fpKQJGvuzj1kCR"

INPUT_FILE     = "argumentation_papers_with_citations.csv"
FINAL_OUTPUT   = "final_dataset_with_europe_pmc.csv"
CHECKPOINT_DIR = "recovery_checkpoints"
CHECKPOINT_EVERY = 2000         # ← tune: 1000–3000 recommended

os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# ────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]*>', '', text)  # Strip HTML/XML tags
    return " ".join(text.split())

def clean_doi(doi_str):
    if pd.isna(doi_str) or not str(doi_str).strip():
        return None
    return str(doi_str).replace("https://doi.org/", "").strip().lower()

def reconstruct_openalex_abstract(inverted_index):
    if not inverted_index:
        return None
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for pos, word in word_positions)

def extract_abstract_from_pdf(pdf_url):
    if not pdf_url or not pdf_url.lower().endswith('.pdf'):
        return None
    try:
        resp = requests.get(pdf_url, timeout=20, stream=True)
        if resp.status_code != 200:
            return None
        reader = PdfReader(resp.raw)
        text = ""
        for page in reader.pages[:6]:
            text += (page.extract_text() or "") + "\n"
        m = re.search(r'(?is)(?:Abstract|ABSTRACT|Summary)\s*[:\n]*(.+?)(?=\n\s*(?:Introduction|Keywords|1\.|Methods|MATERIALS)|\Z)', text)
        if m:
            extracted = clean_text(m.group(1).strip())
            if len(extracted) > 120:
                print(f"PDF abstract extracted ({len(extracted)} chars) from {pdf_url}")
                return extracted
    except Exception as e:
        print(f"PDF extraction failed for {pdf_url}: {str(e)[:70]}")
    return None

# ────────────────────────────────────────────────
# DOI lookup if missing (fallback)
# ────────────────────────────────────────────────
def fetch_doi_by_title(title):
    for source, func in [
        ("CrossRef", lambda: fetch_crossref_doi(title)),
        ("OpenAlex", lambda: fetch_openalex_doi(title)),
        ("Semantic", lambda: fetch_semanticscholar_doi(title)),
    ]:
        try:
            doi = func()
            if doi:
                print(f"Found DOI via {source}: {doi}")
                return doi
        except:
            pass
    return None

def fetch_crossref_doi(title):
    params = {'query.title': title, 'rows': 1, 'mailto': EMAIL}
    r = requests.get("https://api.crossref.org/works", params=params, timeout=10)
    if r.status_code == 200:
        items = r.json().get('message', {}).get('items', [])
        if items:
            return items[0].get('DOI')
    return None

def fetch_openalex_doi(title):
    params = {'filter': f'title.search:{urllib.parse.quote(title)}', 'mailto': EMAIL, 'per_page': 1}
    r = requests.get("https://api.openalex.org/works", params=params, timeout=10)
    if r.status_code == 200:
        data = r.json()
        if data.get('results'):
            return clean_doi(data['results'][0].get('doi'))
    return None

def fetch_semanticscholar_doi(title):
    params = {'query': title, 'limit': 1, 'fields': 'doi'}
    r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, timeout=10)
    if r.status_code == 200:
        data = r.json()
        if data.get('data'):
            return data['data'][0].get('doi')
    return None

# ────────────────────────────────────────────────
# Europe PMC Fetcher
# ────────────────────────────────────────────────
def fetch_europe_pmc_all(doi=None, title=None):
    try:
        if doi:
            query = f"doi:\"{doi}\""
        elif title:
            query = f'title:"{urllib.parse.quote(title)}"'
        else:
            return {}

        url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query={query}&resultType=core&format=json&pageSize=1"
        )
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return {}

        data = r.json()
        results = data.get('resultList', {}).get('result', [])
        if not results:
            return {}

        item = results[0]
        abstract = item.get('abstractText')
        keywords_list = item.get('keywordList', {}).get('keyword', [])
        keywords = keywords_list if isinstance(keywords_list, list) else [keywords_list]

        # PDF URL
        pdf_url = None
        full_text_urls = item.get('fullTextUrlList', {}).get('fullTextUrl', [])
        for link in full_text_urls:
            if 'pdf' in link.get('documentStyle', '').lower() and link.get('availability') == 'Free':
                pdf_url = link['url']
                break

        return {
            'abstract': clean_text(abstract) if abstract else None,
            'keywords': list(set(k.strip() for k in keywords if k and k.strip())),
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None,
            'pdf_url': pdf_url
        }
    except Exception as e:
        print(f"Europe PMC error: {str(e)[:120]}")
        return {}

# ────────────────────────────────────────────────
# Other fetchers
# ────────────────────────────────────────────────
def fetch_unpaywall(doi, title=None):
    if not doi:
        return {}
    try:
        url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={EMAIL}"
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return {}
        data = r.json()
        abstract = data.get('abstract') or data.get('crossref', {}).get('abstract', None)
        keywords = data.get('crossref', {}).get('subject', [])
        best = data.get('best_oa_location') or {}
        pdf_url = best.get('url_for_pdf') if best.get('url_for_pdf', '').lower().endswith('.pdf') else None

        return {
            'abstract': clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None,
            'pdf_url': pdf_url
        }
    except:
        return {}

def fetch_openalex_all(doi, title=None):
    try:
        data = None
        if doi:
            url = f"https://api.openalex.org/works/https://doi.org/{doi}?mailto={EMAIL}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
        else:
            params = {'filter': f'title.search:{urllib.parse.quote(title)}', 'mailto': EMAIL, 'per_page': 1, 'sort': 'relevance_score:desc'}
            r = requests.get("https://api.openalex.org/works", params=params, timeout=10)
            if r.status_code == 200:
                json_data = r.json()
                if json_data.get('results'):
                    data = json_data['results'][0]

        if data is None:
            return {}

        abstract = reconstruct_openalex_abstract(data.get('abstract_inverted_index'))
        keywords = [k['display_name'] for k in data.get('keywords', [])]
        if not keywords:
            keywords = [c['display_name'] for c in data.get('concepts', []) if c.get('level', 10) <= 1]

        # PDF URL
        oa = data.get('open_access', {})
        pdf_url = oa.get('oa_url') if oa.get('is_oa') and oa.get('oa_url', '').lower().endswith('.pdf') else None

        return {
            'abstract': clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [w for w in data.get('referenced_works', []) if w],
            'related_works': data.get('related_works', []),
            'cited_by_count': data.get('cited_by_count'),
            'citations': len(data.get('referenced_works', [])),
            'pdf_url': pdf_url
        }
    except Exception as e:
        print(f"OpenAlex error: {str(e)[:120]}")
        return {}

def fetch_semantic_scholar_all(doi, title=None):
    try:
        data = None
        fields = 'abstract,fieldsOfStudy,s2FieldsOfStudy,references,citations,openAccessPdf'
        if doi:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields={fields}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
        else:
            params = {'query': title, 'limit': 1, 'fields': fields}
            r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, timeout=10)
            if r.status_code == 200:
                json_data = r.json()
                if json_data.get('data'):
                    data = json_data['data'][0]

        if data is None:
            return {}

        fields = (data.get('s2FieldsOfStudy') or []) + (data.get('fieldsOfStudy') or [])
        keywords = [f['category'] if isinstance(f, dict) else f for f in fields if f]

        # PDF URL
        open_access_pdf = data.get('openAccessPdf', {})
        pdf_url = open_access_pdf.get('url') if open_access_pdf and open_access_pdf.get('url', '').lower().endswith('.pdf') else None

        return {
            'abstract': clean_text(data.get('abstract')),
            'keywords': list(set(keywords)),
            'referenced_works': [ref.get('paperId') for ref in data.get('references', [])],
            'related_works': [],
            'cited_by_count': len(data.get('citations', [])),
            'citations': len(data.get('references', [])),
            'pdf_url': pdf_url
        }
    except Exception as e:
        print(f"Semantic Scholar error: {str(e)[:120]}")
        return {}

def fetch_core_all(doi, title=None):
    if not (doi or title):
        return {}
    try:
        headers = {}
        if CORE_API_KEY:
            headers["Authorization"] = f"Bearer {CORE_API_KEY}"

        if doi:
            url = f"https://api.core.ac.uk/v3/works/{urllib.parse.quote(doi)}"
            r = requests.get(url, headers=headers, timeout=12)
        else:
            params = {'q': f'title:"{urllib.parse.quote(title)}"', 'pageSize': 1}
            url = "https://api.core.ac.uk/v3/search/works"
            r = requests.get(url, params=params, headers=headers, timeout=12)

        if r.status_code != 200:
            return {}

        if doi:
            data = r.json()
        else:
            res = r.json().get('results', [])
            if not res:
                return {}
            data = res[0]

        abstract = data.get('abstract') or data.get('description')
        keywords = data.get('topics', []) or data.get('subjects', []) or data.get('keywords', [])

        # PDF URL
        pdf_url = data.get('downloadUrl') if data.get('downloadUrl', '').lower().endswith('.pdf') else None

        return {
            'abstract': clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [ref.get('doi') or ref.get('coreId') for ref in data.get('references', [])],
            'related_works': [],
            'cited_by_count': data.get('citedByCount'),
            'citations': len(data.get('references', [])),
            'pdf_url': pdf_url
        }
    except Exception as e:
        print(f"CORE error: {str(e)[:120]}")
        return {}

def fetch_pubmed_all(doi=None, title=None):
    try:
        if doi:
            term = f"{doi}[doi]"
        elif title:
            term = f'"{title}"[Title]'
        else:
            return {}

        esearch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&term={urllib.parse.quote(term)}&retmax=1&retmode=json"
        )
        r_search = requests.get(esearch_url, timeout=10)
        if r_search.status_code != 200:
            return {}

        search_data = r_search.json()
        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return {}

        pmid = id_list[0]

        efetch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
        )
        r_fetch = requests.get(efetch_url, timeout=12)
        if r_fetch.status_code != 200:
            return {}

        text = r_fetch.text.strip()

        abstract_match = re.search(r'(?s)Abstract\s*(.*?)(?=\n[A-Z][a-zA-Z ]+?:|\Z)', text)
        abstract = abstract_match.group(1).strip() if abstract_match else None

        keywords = []
        mesh_section = re.search(r'(?s)MeSH Headings\s*(.*?)(?=\n\n|\Z)', text)
        if mesh_section:
            mesh_text = mesh_section.group(1)
            keywords = re.findall(r'([^*]+?)\*?;?', mesh_text)
            keywords = [k.strip() for k in keywords if k.strip()]

        return {
            'abstract': clean_text(abstract) if abstract else None,
            'keywords': list(set(keywords)),
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None,
            'pdf_url': None  # PubMed typically doesn't provide direct PDF
        }
    except Exception as e:
        print(f"PubMed fetch error: {str(e)[:120]}")
        return {}

# ────────────────────────────────────────────────
# CHECKPOINT HELPERS
# ────────────────────────────────────────────────
def get_checkpoint_path(start_idx: int, end_idx: int) -> Path:
    return Path(CHECKPOINT_DIR) / f"recovered_{start_idx:06d}_{end_idx:06d}.csv"

def find_latest_checkpoint() -> tuple[int, pd.DataFrame | None]:
    files = sorted(Path(CHECKPOINT_DIR).glob("recovered_*.csv"))
    if not files:
        return 0, None

    last_file = files[-1]
    try:
        start_str = last_file.stem.split('_')[2]   # recovered_000000_003000 → 003000
        start_idx = int(start_str)
        df = pd.read_csv(last_file)
        print(f"→ Resuming from checkpoint: {last_file.name}  ({len(df)} rows already done)")
        return start_idx, df
    except:
        print("Last checkpoint appears corrupted → starting from beginning")
        return 0, None

# ────────────────────────────────────────────────
# MAIN PROCESS
# ────────────────────────────────────────────────
def main_process():
    if not Path(INPUT_FILE).is_file():
        print(f"Input file not found: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE)
    total = len(df)
    print(f"Total rows: {total:,}\n")

    # Resume logic
    start_idx, checkpoint_df = find_latest_checkpoint()

    if checkpoint_df is not None:
        n = len(checkpoint_df)
        for col in checkpoint_df.columns:
            if col not in df.columns:
                df[col] = pd.NA
        df.iloc[start_idx : start_idx + n] = checkpoint_df.values
        print(f"Loaded {n:,} previously processed rows.\n")
    else:
        for col in ['abstract', 'keywords', 'referenced_works', 'related_works',
                    'cited_by_count', 'citations', 'doi']:
            if col not in df.columns:
                df[col] = ""

    current_batch = []
    batch_start = start_idx

    stats = {
        'doi': 0, 'abstract': 0, 'keywords': 0,
        'referenced': 0, 'related': 0, 'citations': 0, 'cited_by': 0
    }

    try:
        for i in tqdm(range(start_idx, total), initial=start_idx, total=total,
                      desc="Enriching", unit="paper"):

            row = df.iloc[i]
            title = str(row.get('title', '')).strip()
            doi   = clean_doi(row.get('doi'))

            if not doi:
                new_doi = fetch_doi_by_title(title)
                if new_doi:
                    df.at[i, 'doi'] = new_doi
                    doi = new_doi
                    stats['doi'] += 1

            # Check if needs enrichment
            needs_enrich = False

            old_abs = str(row.get('abstract', '')).strip()
            if not old_abs or len(old_abs) < 100:
                needs_enrich = True

            old_kw = str(row.get('keywords', '')).strip()
            kw_list = [k.strip() for k in old_kw.split(';') if k.strip()]
            num_kw = len(kw_list)
            if num_kw < 3:
                needs_enrich = True

            for field in ['referenced_works', 'related_works', 'citations', 'cited_by_count']:
                v = str(row.get(field, '')).strip()
                if not v or v.lower() in ['nan', '0', '0.0', '']:
                    needs_enrich = True
                    break

            if not needs_enrich:
                current_batch.append(df.iloc[i].to_dict())
                continue

            # Try sources → keep best abstract (longest)
            best = {
                'abstract': None, 'keywords': [], 'referenced_works': [],
                'related_works': [], 'cited_by_count': None, 'citations': None
            }
            best_abs_len = 0
            pdf_candidates = []

            sources = [
                (fetch_unpaywall,           [doi, title]),
                (fetch_core_all,            [doi, title]),
                (fetch_europe_pmc_all,      [doi, title]),
                (fetch_pubmed_all,          [doi, title]),
                (fetch_openalex_all,        [doi, title]),
                (fetch_semantic_scholar_all,[doi, title]),
            ]

            for func, args in sources:
                try:
                    res = func(*args)
                    abst = res.get('abstract') or ""
                    if abst and len(abst) > best_abs_len:
                        best = res.copy()
                        best_abs_len = len(abst)
                    elif abst or res.get('keywords'):
                        if best['abstract'] is None:
                            best = res.copy()
                    if res.get('pdf_url'):
                        pdf_candidates.append(res['pdf_url'])
                except Exception as e:
                    print(f"  {func.__name__:<22} failed → {str(e)[:70]}")
                time.sleep(1.3)

            # Fallback to PDF extraction if abstract is still short/missing
            if best_abs_len < 100 and PDF_EXTRACTION_AVAILABLE and pdf_candidates:
                for pdf_url in pdf_candidates:
                    extracted = extract_abstract_from_pdf(pdf_url)
                    if extracted and len(extracted) > best_abs_len:
                        best['abstract'] = extracted
                        best_abs_len = len(extracted)
                        break

            # Apply best data if better
            if best['abstract'] and best_abs_len > len(old_abs):
                df.at[i, 'abstract'] = best['abstract']
                stats['abstract'] += 1

            if best['keywords'] and len(best['keywords']) > num_kw:
                df.at[i, 'keywords'] = "; ".join(best['keywords'][:15])
                stats['keywords'] += 1

            for field, key, lim, stat_key in [
                ('referenced_works', 'referenced_works', 30, 'referenced'),
                ('related_works',    'related_works',    20, 'related'),
            ]:
                old_v = str(row.get(field, '')).strip()
                old_num = len([x.strip() for x in old_v.split(';') if x.strip()]) if old_v else 0
                if best.get(key) and len(best[key]) > old_num:
                    df.at[i, field] = "; ".join(str(x) for x in best[key][:lim])
                    stats[stat_key] += 1

            for field, key in [
                ('citations',      'citations'),
                ('cited_by_count', 'cited_by_count'),
            ]:
                old_v = str(row.get(field, '')).strip()
                old_num = int(float(old_v)) if old_v and old_v.lower() not in ['nan', ''] else 0
                if best.get(key) is not None and best[key] > old_num:
                    df.at[i, field] = best[key]
                    k = 'citations' if field == 'citations' else 'cited_by'
                    stats[k] += 1

            current_batch.append(df.iloc[i].to_dict())

            # Checkpoint & incremental save
            if len(current_batch) >= CHECKPOINT_EVERY or i == total - 1:
                end_idx = i + 1
                chunk = pd.DataFrame(current_batch)
                path = get_checkpoint_path(batch_start, end_idx)
                chunk.to_csv(path, index=False)
                print(f"  Saved → {path.name} ({len(chunk):,} rows)")

                # Append to final file
                header = not Path(FINAL_OUTPUT).exists()
                chunk.to_csv(FINAL_OUTPUT, mode='a', header=header, index=False)

                current_batch = []
                batch_start = end_idx

            time.sleep(1.5)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        if current_batch:
            end_idx = i + 1
            chunk = pd.DataFrame(current_batch)
            path = get_checkpoint_path(batch_start, end_idx)
            chunk.to_csv(path, index=False)
            print(f"Saved partial batch → {path.name} ({len(current_batch)} rows)")
            print("Resume: re-run the script (auto-detects last checkpoint)")
        raise

    except Exception as e:
        print(f"\nCrash: {type(e).__name__} - {e}")
        if current_batch:
            path = get_checkpoint_path(batch_start, i + 1)
            pd.DataFrame(current_batch).to_csv(path, index=False)
            print(f"Emergency save → {path.name}")
        raise

    # Final report
    print("\n" + "═"*70)
    print("Recovery summary:")
    print(f"DOIs recovered       : {stats['doi']:5d}")
    print(f"Abstracts improved   : {stats['abstract']:5d}")
    print(f"Keywords filled      : {stats['keywords']:5d}")
    print(f"Referenced works     : {stats['referenced']:5d}")
    print(f"Related works        : {stats['related']:5d}")
    print(f"Citations filled     : {stats['citations']:5d}")
    print(f"Cited-by counts      : {stats['cited_by']:5d}")
    print("═"*70)
    print(f"Final file → {FINAL_OUTPUT}")
    print("Done.")

if __name__ == "__main__":
    main_process()