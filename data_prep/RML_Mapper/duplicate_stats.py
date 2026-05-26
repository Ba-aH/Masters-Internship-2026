"""
duplicate_stats.py
------------------
Scans all references.json files under an `extracted/` root folder and
produces a duplicate statistics report based on exact title matches.
Optionally fixes duplicates by querying OpenAlex and replacing each
duplicate group with a single clean entry built purely from OpenAlex data.

Folder structure expected:
    extracted/
        paper_folder_1/
            references.json
        paper_folder_2/
            references.json
        ...

Usage:
    python duplicate_stats.py --root extracted
    python duplicate_stats.py --root extracted --save report.md
    python duplicate_stats.py --root extracted --fix --fixdir extracted_deduped
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# OpenAlex credentials  (rotated round-robin to stay in polite pool)
# ---------------------------------------------------------------------------

OPENALEX_CREDENTIALS = [
    {"key": "h2VQLBHlgD4wBNOuroywew", "email": "behantous@gmail.com"},
    {"key": "ZmYuOfeVVSYxVLZRyL0SwZ", "email": "bahahantous@gmail.com"},
    {"key": "zruTIcT4eZmLhFzIUZ69hZ", "email": "brensm3allem@gmail.com"},
    {"key": "i8l5VxjlMHHE5FYLUuV5PN", "email": "pinkyboan@gmail.com"},
    {"key": "vbL8IZElFROAwaRgJ7bUO2", "email": "tousa.shop.contact@gmail.com"},
]

_cred_index = 0


def _next_cred():
    global _cred_index
    cred = OPENALEX_CREDENTIALS[_cred_index % len(OPENALEX_CREDENTIALS)]
    _cred_index += 1
    return cred


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text):
    text = re.sub(r"[^\w\s]", "", text or "").strip().lower()
    return re.sub(r"\s+", "_", text)[:120]


# ---------------------------------------------------------------------------
# Per-file duplicate detection (title only)
# ---------------------------------------------------------------------------

def detect_in_file(references):
    title_groups = defaultdict(list)

    for i, ref in enumerate(references):
        t = slugify(ref.get("title", ""))
        if t:
            title_groups[t].append(i)

    return {k: v for k, v in title_groups.items() if len(v) > 1}


# ---------------------------------------------------------------------------
# Scan all files
# ---------------------------------------------------------------------------

def scan(root):
    files = sorted(root.rglob("references.json"))
    if not files:
        print(f"No references.json files found under: {root}")
        return []

    results = []

    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            results.append({"path": str(path), "error": str(e)})
            continue

        refs       = data.get("references", [])
        paper      = data.get("paper", {})
        title_dups = detect_in_file(refs)

        # Number of removable entries (each group of N has N-1 extras)
        removable = sum(len(v) - 1 for v in title_dups.values())

        results.append({
            "path":             str(path),
            "paper_id":         paper.get("paper_id", "unknown"),
            "paper_title":      paper.get("title", ""),
            "total_refs":       len(refs),
            "dup_groups":       len(title_dups),
            "exact_duplicates": removable,
            "dup_titles": {
                slug: [refs[i].get("title", slug) for i in indices]
                for slug, indices in title_dups.items()
            },
            # kept private; used by fix_files
            "_refs":      refs,
            "_data":      data,
            "_title_dups": title_dups,
        })

    return results


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def build_report_md(results):
    errors = [r for r in results if "error" in r]
    ok     = [r for r in results if "error" not in r]

    total_files     = len(ok)
    total_refs      = sum(r["total_refs"] for r in ok)
    total_dups      = sum(r["exact_duplicates"] for r in ok)
    files_with_dups = sum(1 for r in ok if r["dup_groups"] > 0)
    files_clean     = total_files - files_with_dups
    dup_pct = f"{total_dups / total_refs * 100:.1f}%" if total_refs else "0%"

    L = []
    L.append("# Duplicate Statistics Report\n")

    L.append("## Summary\n")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Files scanned | {total_files} |")
    if errors:
        L.append(f"| Files with errors | {len(errors)} |")
    L.append(f"| Total references | {total_refs} |")
    L.append(f"| Exact title duplicates | {total_dups} ({dup_pct}) |")
    L.append(f"| Files with duplicates | {files_with_dups} / {total_files} |")
    L.append(f"| Clean files | {files_clean} |")
    L.append("")

    # Top 10 worst files
    worst = sorted(ok, key=lambda r: r["exact_duplicates"], reverse=True)[:10]
    if worst and worst[0]["exact_duplicates"] > 0:
        L.append("## Top 10 Files by Duplicate Count\n")
        L.append("| Exact Duplicates | Total Refs | Paper title |")
        L.append("|---|---|---|")
        for r in worst:
            if r["exact_duplicates"] == 0:
                break
            title = (r["paper_title"] or r["path"])[:60]
            L.append(f"| {r['exact_duplicates']} | {r['total_refs']} | {title} |")
        L.append("")

    # Per-file detail
    dup_files = [r for r in ok if r["dup_groups"] > 0]
    if dup_files:
        L.append(f"## Per-File Detail ({len(dup_files)} files with duplicates)\n")
        for r in dup_files:
            L.append(f"### {r['paper_title'][:70] or r['paper_id']}")
            L.append(f"- **paper\\_id**: `{r['paper_id']}`")
            L.append(f"- **File**: `{r['path']}`")
            L.append(f"- **Total refs**: {r['total_refs']} &nbsp;|&nbsp; "
                     f"**Duplicate groups**: {r['dup_groups']} &nbsp;|&nbsp; "
                     f"**Exact duplicates**: {r['exact_duplicates']}")
            L.append("")
            L.append("| Occurrences | Title |")
            L.append("|---|---|")
            for slug, titles in r["dup_titles"].items():
                display_title = titles[0][:80]
                L.append(f"| {len(titles)} | {display_title} |")
            L.append("")

    if errors:
        L.append("## Files With Load Errors\n")
        for e in errors:
            L.append(f"- `{e['path']}`: {e['error']}")
        L.append("")

    return L


# ---------------------------------------------------------------------------
# OpenAlex lookup + field mapping
# ---------------------------------------------------------------------------

def fetch_openalex_by_title(title, retries=2):
    """
    Search OpenAlex for a work by title.
    Returns the top matching work dict, or None if not found / on error.
    Rotates credentials and respects the polite-pool rate limit (~8 req/s).
    """
    cred   = _next_cred()
    params = urllib.parse.urlencode({
        "search":   title,
        "mailto":   cred["email"],
        "api_key":  cred["key"],
        "per_page": 1,
    })
    url = f"https://api.openalex.org/works?{params}"

    for attempt in range(retries + 1):
        try:
            time.sleep(0.12)          # stay safely under 10 req/sec
            with urllib.request.urlopen(url, timeout=10) as resp:
                data    = json.loads(resp.read().decode())
                results = data.get("results", [])
                return results[0] if results else None
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            if attempt == retries:
                print(f"    [warn] OpenAlex fetch failed for "
                      f"'{title[:55]}': {exc}")
                return None
            time.sleep(1.0 * (attempt + 1))   # brief back-off before retry

    return None


def openalex_work_to_ref(work, original_paper_id=None):
    """
    Convert an OpenAlex work object into a clean reference dict.
    Only fields sourced from OpenAlex are included; nothing is carried
    over from the original entry except the internal paper_id.
    """
    # DOI — strip the https://doi.org/ prefix when present
    doi = work.get("doi") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    # OpenAlex ID — strip the URL prefix, keep just the W-number
    oa_id = work.get("id") or ""
    if oa_id.startswith("https://openalex.org/"):
        oa_id = oa_id[len("https://openalex.org/"):]

    # Venue — primary location source name
    venue  = None
    source = ((work.get("primary_location") or {}).get("source") or {})
    venue  = source.get("display_name")

    # Authors — ordered list of display names
    authors = [
        a["author"]["display_name"]
        for a in (work.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    ]

    return {
        "paper_id":                 original_paper_id or oa_id or None,
        "openalex_id":              oa_id or None,
        "title":                    work.get("display_name"),
        "year":                     work.get("publication_year"),
        "doi":                      doi or None,
        "venue":                    venue,
        "authors":                  authors,
        "citation_count":           work.get("cited_by_count"),
        "openalex_title_validated": True,
    }


# ---------------------------------------------------------------------------
# Fix — deduplicate + enrich duplicate groups via OpenAlex
# ---------------------------------------------------------------------------

def fix_files(results, fix_dir, root, inplace=False):
    """
    For every file with title duplicates:
      1. Keep the first occurrence of each duplicate group; drop the rest.
      2. Query OpenAlex for that title and replace the kept entry with
         a clean record built entirely from OpenAlex data.
      3. If OpenAlex returns nothing, keep the original entry unchanged.
      4. Non-duplicate references are written out as-is.

    When inplace=True the original files are overwritten directly and
    fix_dir / --fixdir is ignored entirely.
    """
    if not inplace:
        fix_dir.mkdir(parents=True, exist_ok=True)

    total_removed   = 0
    total_enriched  = 0
    total_not_found = 0

    files_to_fix = [r for r in results if "error" not in r
                    and r["dup_groups"] > 0]

    mode_label = "in-place (overwriting originals)" if inplace else str(fix_dir)
    print(f"\nFixing {len(files_to_fix)} file(s) → {mode_label} …")

    for r in files_to_fix:
        src_path  = Path(r["path"])
        if inplace:
            dest_path = src_path
        else:
            rel_path  = src_path.relative_to(root)
            dest_path = fix_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

        refs       = r["_refs"]
        title_dups = r["_title_dups"]

        # For each dup group: keep first index, drop the rest, enrich via OA
        replace_map  = {}    # first_index -> enriched ref from OpenAlex
        drop_indices = set()

        for slug, indices in title_dups.items():
            keep_idx = indices[0]
            for drop_idx in indices[1:]:
                drop_indices.add(drop_idx)
            total_removed += len(indices) - 1

            original_title = refs[keep_idx].get("title", "")
            original_pid   = refs[keep_idx].get("paper_id")

            print(f"  [{src_path.parent.name}] querying: {original_title[:65]}")
            work = fetch_openalex_by_title(original_title)

            if work:
                replace_map[keep_idx] = openalex_work_to_ref(work, original_pid)
                total_enriched += 1
            else:
                # OpenAlex had no result — keep original entry untouched
                replace_map[keep_idx] = refs[keep_idx]
                total_not_found += 1

        # Rebuild the reference list
        new_refs = []
        for i, ref in enumerate(refs):
            if i in drop_indices:
                continue
            new_refs.append(replace_map.get(i, ref))

        out_data               = r["_data"].copy()
        out_data["references"] = new_refs

        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)

    # Copy clean files to fixdir (skipped when --inplace since source == dest)
    if not inplace:
        for r in results:
            if "error" in r or r["dup_groups"] > 0:
                continue
            src_path  = Path(r["path"])
            rel_path  = src_path.relative_to(root)
            dest_path = fix_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(src_path, encoding="utf-8") as f_in, \
                 open(dest_path, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())

    dest_label = "originals (in-place)" if inplace else str(fix_dir)
    print(f"\nFixed files written to       : {dest_label}")
    print(f"Duplicate entries removed    : {total_removed}")
    print(f"Entries enriched via OpenAlex: {total_enriched}")
    print(f"Entries not found on OpenAlex: {total_not_found}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root",   default="extracted",
                   help="Root folder containing one subfolder per paper")
    p.add_argument("--save",   default=None,
                   help="Save the report to a markdown file (e.g. report.md)")
    p.add_argument("--fix",    action="store_true",
                   help="Deduplicate files and enrich via OpenAlex")
    p.add_argument("--fixdir", default="extracted_deduped",
                   help="Output root for fixed files (default: extracted_deduped)")
    p.add_argument("--inplace", action="store_true",
                   help="Overwrite original files directly instead of writing to --fixdir")
    args = p.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Folder not found: {root}")
        return

    print(f"Scanning {root} …")
    results = scan(root)

    if not results:
        return

    # Console summary
    ok         = [r for r in results if "error" not in r]
    total_dups = sum(r["exact_duplicates"] for r in ok)
    total_refs = sum(r["total_refs"] for r in ok)
    print(f"Files scanned        : {len(ok)}")
    print(f"Total references     : {total_refs}")
    print(f"Exact duplicates     : {total_dups}")

    if args.save:
        save_path = Path(args.save)
        lines     = build_report_md(results)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"Report saved to      : {save_path}")

    if args.fix:
        fix_files(results, Path(args.fixdir), root, inplace=args.inplace)


if __name__ == "__main__":
    main()