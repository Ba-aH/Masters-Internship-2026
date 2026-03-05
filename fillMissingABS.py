import pandas as pd
import requests
import time
import re
import urllib.parse
import xml.etree.ElementTree as ET
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
EMAIL = "behantous@gmail.com"  # Required for OpenAlex, CrossRef, Unpaywall
CORE_API_KEY = "5qo9HW0V2xUMXSNtY7fpKQJGvuzj1kCR"  # Your CORE key (Bearer token)

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]*>', '', text)  # Strip HTML/XML tags
    return " ".join(text.split())

def clean_doi(doi_str):
    if pd.isna(doi_str) or not str(doi_str).strip():
        return None
    return str(doi_str).replace("https://doi.org/", "").strip().lower()

# ────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────
def reconstruct_openalex_abstract(inverted_index):
    if not inverted_index:
        return None
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for pos, word in word_positions)

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
# Europe PMC Fetcher (NEW)
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

        return {
            'abstract': clean_text(abstract) if abstract else None,
            'keywords': list(set(k.strip() for k in keywords if k and k.strip())),
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None
        }
    except Exception as e:
        print(f"Europe PMC error: {str(e)[:120]}")
        return {}

# ────────────────────────────────────────────────
# Other fetchers (Unpaywall, OpenAlex, Semantic Scholar, CORE, PubMed)
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
        pdf_url = None
        best = data.get('best_oa_location') or {}
        if best.get('url_for_pdf', '').lower().endswith('.pdf'):
            pdf_url = best['url_for_pdf']

        extracted_abstract = None
        if pdf_url and PDF_EXTRACTION_AVAILABLE:
            try:
                resp = requests.get(pdf_url, timeout=20, stream=True)
                if resp.status_code == 200:
                    reader = PdfReader(resp.raw)
                    text = ""
                    for page in reader.pages[:6]:
                        text += (page.extract_text() or "")
                    m = re.search(r'(?:Abstract|ABSTRACT|Summary)\s*[:\n]*(.+?)(?=\n\s*(?:Introduction|Keywords|1\.|Methods)|\Z)',
                                  text, re.DOTALL | re.IGNORECASE)
                    if m:
                        extracted_abstract = clean_text(m.group(1).strip())
                        if len(extracted_abstract) > 120:
                            print(f"PDF abstract extracted ({len(extracted_abstract)} chars)")
            except:
                pass

        return {
            'abstract': extracted_abstract or clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None
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

        return {
            'abstract': clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [w for w in data.get('referenced_works', []) if w],
            'related_works': data.get('related_works', []),
            'cited_by_count': data.get('cited_by_count'),
            'citations': len(data.get('referenced_works', []))
        }
    except Exception as e:
        print(f"OpenAlex error: {str(e)[:120]}")
        return {}

def fetch_semantic_scholar_all(doi, title=None):
    try:
        data = None
        if doi:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields=abstract,fieldsOfStudy,s2FieldsOfStudy,references,citations"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
        else:
            params = {'query': title, 'limit': 1, 'fields': 'abstract,fieldsOfStudy,s2FieldsOfStudy,references,citations'}
            r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, timeout=10)
            if r.status_code == 200:
                json_data = r.json()
                if json_data.get('data'):
                    data = json_data['data'][0]

        if data is None:
            return {}

        fields = data.get('s2FieldsOfStudy', []) + data.get('fieldsOfStudy', [])
        keywords = [f['category'] if isinstance(f, dict) else f for f in fields if f]

        return {
            'abstract': clean_text(data.get('abstract')),
            'keywords': list(set(keywords)),
            'referenced_works': [ref.get('paperId') for ref in data.get('references', [])],
            'related_works': [],
            'cited_by_count': len(data.get('citations', [])),
            'citations': len(data.get('references', []))
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

        return {
            'abstract': clean_text(abstract),
            'keywords': list(set(keywords)),
            'referenced_works': [ref.get('doi') or ref.get('coreId') for ref in data.get('references', [])],
            'related_works': [],
            'cited_by_count': data.get('citedByCount'),
            'citations': len(data.get('references', []))
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
            'citations': None
        }
    except Exception as e:
        print(f"PubMed fetch error: {str(e)[:120]}")
        return {}

# ────────────────────────────────────────────────
# MAIN PROCESS
# ────────────────────────────────────────────────
def main_process(input_csv, output_csv):
    df = pd.read_csv(input_csv)

    for col in ['abstract', 'keywords', 'referenced_works', 'related_works', 'cited_by_count', 'citations', 'doi']:
        if col not in df.columns:
            df[col] = ""

    abs_recovered = 0
    kw_recovered = 0
    doi_recovered = 0
    ref_recovered = 0
    rel_recovered = 0
    cit_recovered = 0
    citedby_recovered = 0

    print(f"Starting recovery on {len(df)} papers...")

    for i, row in tqdm(df.iterrows(), total=len(df)):
        title = str(row.get('title', '')).strip()
        doi = clean_doi(row.get('doi'))

        if not doi:
            new_doi = fetch_doi_by_title(title)
            if new_doi:
                df.at[i, 'doi'] = new_doi
                doi = new_doi
                doi_recovered += 1

        current_abs = str(row.get('abstract', '')).strip()
        current_kw = str(row.get('keywords', '')).strip()
        current_ref = str(row.get('referenced_works', '')).strip()
        current_rel = str(row.get('related_works', '')).strip()
        current_cit = str(row.get('citations', '')).strip()
        current_citedby = str(row.get('cited_by_count', '')).strip()

        needs_update = (
            (not current_abs or len(current_abs) < 60) or
            not current_kw or current_kw.lower() in ['nan', ''] or
            not current_ref or
            not current_cit or current_cit in ['nan', '0.0'] or
            not current_citedby or current_citedby in ['nan', '0.0']
        )

        best_data = {
            'abstract': None,
            'keywords': [],
            'referenced_works': [],
            'related_works': [],
            'cited_by_count': None,
            'citations': None
        }
        best_abstract_len = 0

        if needs_update:
            sources = [
                (fetch_unpaywall, [doi, title]),
                (fetch_core_all, [doi, title]),
                (fetch_europe_pmc_all, [doi, title]),       # ← Europe PMC added here
                (fetch_pubmed_all, [doi, title]),
                (fetch_openalex_all, [doi, title]),
                (fetch_semantic_scholar_all, [doi, title]),
            ]

            for fetch_func, args in sources:
                try:
                    res = fetch_func(*args)
                    abs_text = res.get('abstract', '')
                    if abs_text and len(abs_text) > best_abstract_len:
                        best_data = res
                        best_abstract_len = len(abs_text)
                    elif abs_text or res.get('keywords'):
                        if not best_data.get('abstract'):
                            best_data = res
                except Exception as e:
                    print(f"Error in {fetch_func.__name__} for '{title[:60]}...': {str(e)[:100]}")

                time.sleep(1.5)

        # Apply best data
        if best_data.get('abstract') and (not current_abs or len(current_abs) < 60):
            df.at[i, 'abstract'] = best_data['abstract']
            abs_recovered += 1

        if best_data.get('keywords') and (not current_kw or current_kw.lower() in ['nan', '']):
            df.at[i, 'keywords'] = "; ".join(best_data['keywords'][:15])
            kw_recovered += 1

        if best_data.get('referenced_works') and not current_ref:
            df.at[i, 'referenced_works'] = "; ".join(str(x) for x in best_data['referenced_works'][:30])
            ref_recovered += 1

        if best_data.get('related_works') and not current_rel:
            df.at[i, 'related_works'] = "; ".join(str(x) for x in best_data['related_works'][:20])
            rel_recovered += 1

        if best_data.get('citations') is not None and (not current_cit or current_cit in ['nan', '0.0']):
            df.at[i, 'citations'] = best_data['citations']
            cit_recovered += 1

        if best_data.get('cited_by_count') is not None and (not current_citedby or current_citedby in ['nan', '0.0']):
            df.at[i, 'cited_by_count'] = best_data['cited_by_count']
            citedby_recovered += 1

        time.sleep(1.6)

    df.to_csv(output_csv, index=False)
    print("\n" + "═"*60)
    print("Recovery summary:")
    print(f"Abstracts recovered  : {abs_recovered:4d}")
    print(f"Keywords recovered   : {kw_recovered:4d}")
    print(f"DOIs recovered       : {doi_recovered:4d}")
    print(f"Referenced works     : {ref_recovered:4d}")
    print(f"Related works        : {rel_recovered:4d}")
    print(f"Citations filled     : {cit_recovered:4d}")
    print(f"Cited-by count       : {citedby_recovered:4d}")
    print("═"*60)
    print(f"Saved → {output_csv}")

if __name__ == "__main__":
    main_process('dataset_with_keywords.csv', 'final_dataset_with_europe_pmc.csv')