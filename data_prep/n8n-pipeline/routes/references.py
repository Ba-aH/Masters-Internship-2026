import json
import os
from datetime import datetime
import requests
from flask import Blueprint, jsonify, request
from pathlib import Path
from cache import load_cache, save_cache
from config import EXTRACTED_DIR, REF_FILENAME
from services.groq import call_groq, split_into_chunks
from services.openalex import validate_batch_with_openalex   # ← batch, not single
from utils import make_author_id, make_paper_id

bp = Blueprint("references", __name__)


def _get_ref_path(folder: str) -> str:
    return os.path.join(EXTRACTED_DIR, folder, REF_FILENAME)


# ── GET /references/<folder> ──────────────────────────────────────────────────
@bp.route("/references/<folder>", methods=["GET"])
def read_references(folder):
    ref_path = _get_ref_path(folder)
    if not os.path.isfile(ref_path):
        return jsonify({"folder": folder, "content": "", "exists": False, "path": ref_path}), 404
    try:
        with open(ref_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"folder": folder, "content": content, "exists": True, "path": ref_path}), 200
    except Exception as e:
        return jsonify({"error": str(e), "folder": folder}), 500


# ── POST /references/<folder> ─────────────────────────────────────────────────
@bp.route("/references/<folder>", methods=["POST"])
def write_references(folder):
    data = request.get_json(silent=True)
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' in request body"}), 400

    folder_path = os.path.join(EXTRACTED_DIR, folder)
    if not os.path.isdir(folder_path):
        return jsonify({"error": f"Folder not found: {folder}"}), 404

    try:
        ref_path = _get_ref_path(folder)
        with open(ref_path, "w", encoding="utf-8") as f:
            f.write(data["content"])
        return jsonify({
            "folder":        folder,
            "success":       True,
            "bytes_written": len(data["content"].encode("utf-8")),
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "folder": folder}), 500


# ── POST /process_references/<folder> ─────────────────────────────────────────
@bp.route("/process_references/<folder>", methods=["POST"])
def process_references(folder):
    ref_path         = _get_ref_path(folder)
    skipped_log_path = Path("skipped_folders.json")

    def log_skipped(reason: str, partial_references=None):
        entry = {
            "folder":        folder,
            "timestamp":     datetime.now().isoformat(),
            "reason":        reason,
            "partial_count": len(partial_references) if partial_references else 0,
        }
        if skipped_log_path.exists():
            try:
                with open(skipped_log_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {"skipped": []}
        else:
            data = {"skipped": []}

        data["skipped"].append(entry)
        try:
            with open(skipped_log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: Could not write to skipped log: {e}")

        return jsonify({
            "folder":     folder,
            "skipped":    True,
            "reason":     reason,
            "references": partial_references or [],
            "count":      len(partial_references) if partial_references else 0,
        }), 200

    if not os.path.isfile(ref_path):
        return log_skipped("referenced_work.md not found")

    try:
        with open(ref_path, "r", encoding="utf-8") as f:
            raw_content = f.read().strip()
    except Exception as e:
        return log_skipped(f"Could not read file: {e}")

    if not raw_content:
        return log_skipped("referenced_work.md is empty")

    chunks         = split_into_chunks(raw_content)
    all_references = []

    for idx, chunk in enumerate(chunks):
        try:
            all_references.extend(call_groq(chunk))
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            body   = e.response.text        if e.response is not None else str(e)
            return log_skipped(
                f"Groq HTTP {status} on chunk {idx+1}/{len(chunks)}: {body[:300]}",
                all_references,
            )
        except Exception as e:
            return log_skipped(
                f"Groq call failed on chunk {idx+1}/{len(chunks)}: {e}",
                all_references,
            )

    return jsonify({
        "folder":     folder,
        "skipped":    False,
        "references": all_references,
        "count":      len(all_references),
    }), 200


# ── POST /cleaned_references/<folder> ─────────────────────────────────────────
@bp.route("/cleaned_references/<folder>", methods=["POST"])
def write_cleaned_references(folder):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    actual_folder = data.get("folder") or folder
    if actual_folder == "unknown":
        return jsonify({"error": "Folder is 'unknown' - check upstream nodes"}), 400

    folder_path = os.path.join(EXTRACTED_DIR, folder)
    if not os.path.isdir(folder_path):
        return jsonify({"error": f"Folder not found: {folder}"}), 404

    cleaned_path = os.path.join(folder_path, "cleaned_references.md")

    try:
        title   = data.get("title", "Untitled Reference")
        authors = data.get("authors", ["Unknown Author"])
        year    = data.get("year")
        doi     = data.get("doi")
        journal = data.get("journal")

        if isinstance(authors, str):
            authors = [authors]
        elif not isinstance(authors, list):
            authors = ["Unknown Author"]

        lines = [f"### {title}", f"Authors: {', '.join(authors)}"]
        if year:
            lines.append(f"Year: {year}")
        if journal:
            lines.append(f"Journal: {journal}")
        if doi:
            lines.append(f"DOI: {doi}")

        validation = data.get("validation", {})
        if validation.get("fixedByOpenAlex"):
            lines.append(f"**Validated by OpenAlex:** Yes (ID: {validation.get('openalexId', 'N/A')})")
        else:
            lines.append("**Validated by OpenAlex:** No (used Groq output directly)")

        lines  += ["", "---", ""]
        content = "\n".join(lines)

        with open(cleaned_path, "w", encoding="utf-8") as f:
            f.write(content)

        return jsonify({
            "folder":        folder,
            "success":       True,
            "path":          cleaned_path,
            "title":         title,
            "bytes_written": len(content.encode("utf-8")),
            "authors_count": len(authors),
        }), 200

    except Exception as e:
        return jsonify({"error": str(e), "folder": folder}), 500


# ── POST /save_all_references/<folder> ────────────────────────────────────────
@bp.route("/save_all_references/<folder>", methods=["POST"])
def save_all_references(folder):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    folder_path = os.path.join(EXTRACTED_DIR, folder)
    if not os.path.isdir(folder_path):
        return jsonify({"error": f"Folder not found: {folder}"}), 404

    references = data.get("references", [])
    if not references:
        return jsonify({"folder": folder, "skipped": True,
                        "reason": "No references in payload"}), 200

    # ── Validate paper + all references in ONE batch ──────────────────────────
    # Old approach: ThreadPoolExecutor → N parallel requests (still N total calls)
    # New approach: batch → ceil((N+1) / 25) total calls
    cache               = load_cache()
    all_refs_to_validate = [{"title": folder}] + list(references)

    validate_batch_with_openalex(all_refs_to_validate, cache=cache)

    save_cache(cache)   # single write after everything is done

    paper_meta = all_refs_to_validate[0]
    references = all_refs_to_validate[1:]

    # ── Build paper entry ─────────────────────────────────────────────────────
    paper_entry = {
        "title":          paper_meta.get("title", folder),
        "authors":        paper_meta.get("authors", []),
        "year":           paper_meta.get("year"),
        "venue":          paper_meta.get("venue"),
        "doi":            paper_meta.get("doi"),
        "openalex_id":    paper_meta.get("openalex_id"),
        "openalex_found": paper_meta.get("openalex_found", False),
        "openalex_score": paper_meta.get("openalex_score", 0.0),
        "citation_count": paper_meta.get("citation_count"),   # ← from OpenAlex
    }
    paper_entry["paper_id"] = make_paper_id(paper_entry["title"])

    raw_authors = paper_entry.get("authors", [])
    if raw_authors and isinstance(raw_authors[0], str):
        paper_entry["authors"] = [
            {"name": a, "author_id": make_author_id(a)} for a in raw_authors if a
        ]

    # ── 1. cleaned_references.md ──────────────────────────────────────────────
    md_lines = [
        f"#  {paper_entry['title']}",
        f"> *Source paper — OpenAlex score: {paper_entry['openalex_score']}%*",
        "", "---", "", "## References", "",
    ]

    for i, ref in enumerate(references, start=1):
        title    = str(ref.get("title")  or "Untitled").strip()
        year     = ref.get("year")
        venue    = str(ref.get("venue")  or ref.get("journal") or "").strip()
        doi      = ref.get("doi")
        authors  = ref.get("authors", [])
        oa_found = ref.get("openalex_found", False)
        oa_score = ref.get("openalex_score", 0.0)

        if isinstance(authors, str):
            authors = [authors]
        elif not isinstance(authors, list):
            authors = []

        author_str = ", ".join(a for a in authors if a) or "Unknown Author"

        md_lines.append(f"### {i}. {title}")
        md_lines.append(f"Authors: {author_str}")
        if year:
            md_lines.append(f"Year: {year}")
        if venue:
            md_lines.append(f"Venue: {venue}")
        if doi:
            md_lines.append(f"DOI: {doi}")
        md_lines.append(f"OpenAlex verified: {'Yes' if oa_found else 'No'} (score: {oa_score}%)")
        md_lines.append("")

    md_path = os.path.join(folder_path, "cleaned_references.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    # ── 2. references.json ────────────────────────────────────────────────────
    json_refs = []
    for ref in references:
        authors = ref.get("authors", [])
        if isinstance(authors, str):
            authors = [authors]
        elif not isinstance(authors, list):
            authors = []

        json_refs.append({
            "title":          str(ref.get("title") or "Untitled").strip(),
            "authors":        [{"name": a, "author_id": make_author_id(a)} for a in authors if a],
            "year":           ref.get("year"),
            "venue":          str(ref.get("venue") or ref.get("journal") or "").strip() or None,
            "doi":            ref.get("doi"),
            "openalex_id":    ref.get("openalex_id"),
            "openalex_found": ref.get("openalex_found", False),
            "openalex_score": ref.get("openalex_score", 0.0),
            "citation_count": ref.get("citation_count"),           # ← from OpenAlex
            "paper_id":       make_paper_id(str(ref.get("title") or "Untitled").strip()),
            "main_paper_id":  paper_entry["paper_id"],
        })

    # ── Build author_links ────────────────────────────────────────────────────
    author_links = [
        {"paper_id": paper_entry["paper_id"], "author_id": a["author_id"], "author_name": a["name"]}
        for a in paper_entry["authors"]
    ] + [
        {"paper_id": ref["paper_id"], "author_id": a["author_id"], "author_name": a["name"]}
        for ref in json_refs
        for a in ref["authors"]
    ]

    output = {
        "paper":        paper_entry,
        "references":   json_refs,
        "author_links": author_links,
        "total":        len(json_refs),
        "verified":     sum(1 for r in json_refs if r["openalex_found"]),
    }

    json_path = os.path.join(folder_path, "references.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return jsonify({
        "folder":           folder,
        "success":          True,
        "references_count": len(json_refs),
        "verified_count":   output["verified"],
        "md_path":          md_path,
        "json_path":        json_path,
    }), 200