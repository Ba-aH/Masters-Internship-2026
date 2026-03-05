import pandas as pd
import requests
import time

df = pd.read_csv("scrapped_argumentation.csv")
MAILTO = "behantous@gmail.com"

def query_openalex(doi=None, title=None):
    # Standard Polite Pool Header
    headers = {"User-Agent": f"MyScraper/1.0 (mailto:{MAILTO})"}
    
    # 1. Try DOI Search
    if pd.notna(doi) and str(doi).strip():
        # Ensure we only have the DOI string, not the full URL
        clean_doi = str(doi).strip().split("doi.org/")[-1]
        url = f"https://api.openalex.org/works/https://doi.org/{clean_doi}"
        
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass # Fall back to title search if DOI fails
    
    # 2. Try Title Search (Fuzzy/Search)
    if pd.notna(title) and str(title).strip():
        clean_title = str(title).strip()
        # filter=title.search is better for slightly messy titles
        url = f"https://api.openalex.org/works?filter=title.search:{requests.utils.quote(clean_title)}&per_page=1"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    return results[0]
        except Exception:
            return None
    
    return None

def extract_fields(work):
    if not work:
        return {}

    # -- Authors --
    authorships = work.get("authorships", [])
    authors = "; ".join([a["author"]["display_name"] for a in authorships if a.get("author")])

    # -- Topics (New OpenAlex Schema) --
    topics_raw = work.get("topics", [])
    
    # Safely get primary topic info to avoid IndexError
    primary = topics_raw[0] if len(topics_raw) > 0 else {}
    
    return {
        "authors": authors,
        "primary_topic":    primary.get("display_name", ""),
        "primary_subfield": primary.get("subfield", {}).get("display_name", ""),
        "primary_field":    primary.get("field",     {}).get("display_name", ""),
        "primary_domain":   primary.get("domain",    {}).get("display_name", ""),
        "referenced_works": "; ".join(work.get("referenced_works", [])),
        "related_works":    "; ".join(work.get("related_works", [])),
        "cited_by_count":   work.get("cited_by_count", 0) # Bonus: Updated citation count
    }

# -- Execution --
enriched_rows = []
for i, row in df.iterrows():
    title_short = str(row.get('title', 'No Title'))[:50]
    print(f"[{i+1}/{len(df)}] Fetching: {title_short}...")

    work = query_openalex(doi=row.get("doi"), title=row.get("title"))
    extra = extract_fields(work)

    # Merge original row with new data
    enriched_rows.append({**row.to_dict(), **extra})
    time.sleep(0.1) # OpenAlex allows up to 10 requests/sec in polite pool

# Save
pd.DataFrame(enriched_rows).to_csv("papers_enriched.csv", index=False)
print("\nSuccess! Data saved to papers_enriched.csv")