import pandas as pd
import requests
import time

# Config
INPUT_CSV = "papers_enriched.csv"
OUTPUT_CSV = "papers_with_keywords.csv"
MAILTO = "behantous@gmail.com"

def query_openalex(doi=None, title=None):
    headers = {"User-Agent": f"MyScraper/1.0 (mailto:{MAILTO})"}
    
    if pd.notna(doi) and str(doi).strip():
        clean_doi = str(doi).strip().split("doi.org/")[-1]
        url = f"https://api.openalex.org/works/https://doi.org/{clean_doi}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()
        except:
            pass
    
    if pd.notna(title) and str(title).strip():
        clean_title = str(title).strip()
        url = f"https://api.openalex.org/works?filter=title.search:{requests.utils.quote(clean_title)}&per_page=1"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    return results[0]
        except:
            pass
    
    return None


def get_keywords(work):
    if not work:
        return ""
    
    keywords_raw = work.get("keywords", [])
    
    if not keywords_raw:
        return ""
    
    # Handle both cases: list of strings OR list of dicts
    if isinstance(keywords_raw[0], str):
        # old/simple format (rare now)
        return "; ".join(keywords_raw)
    else:
        # current format: list of dicts → extract display_name
        return "; ".join(
            kw.get("display_name", "").strip()
            for kw in keywords_raw
            if kw.get("display_name")
        )


# Main
df = pd.read_csv(INPUT_CSV)
print(f"Processing {len(df)} papers...\n")

enriched = []

for i, row in df.iterrows():
    title_short = str(row.get('title', 'No Title'))[:50]
    print(f"[{i+1}/{len(df)}] {title_short}...")
    
    work = query_openalex(doi=row.get("doi"), title=row.get("title"))
    
    keywords = get_keywords(work)
    
    new_row = row.to_dict()
    new_row["keywords"] = keywords
    
    enriched.append(new_row)
    
    time.sleep(0.5)  # polite

pd.DataFrame(enriched).to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
print(f"\nDone. Saved to: {OUTPUT_CSV}")
print(f"Rows with keywords: {sum(1 for r in enriched if r['keywords'])}")