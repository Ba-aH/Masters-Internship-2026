import os
import shutil
import subprocess

from flask import Blueprint, jsonify, request

from config import EXTRACTED_DIR, RML_MAPPING_PATH

bp = Blueprint("rml", __name__)


def _count_triples(ttl_path: str) -> int:
    """Quick line-count heuristic for Turtle files."""
    if not os.path.isfile(ttl_path):
        return 0
    count = 0
    with open(ttl_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.endswith(" .") or stripped == ".":
                count += 1
    return count


# ── POST /rml/convert ─────────────────────────────────────────────────────────
@bp.route("/rml/convert", methods=["POST"])
def rml_convert():
    body = request.get_json(silent=True) or {}
    json_path = body.get("json_path", "").strip()
    if not json_path:
        return jsonify({"success": False, "skipped": True,
                        "reason": "No json_path provided — folder skipped"}), 200

    if not os.path.isfile(json_path):
        return jsonify({"success": False, "skipped": True,
                        "reason": f"references.json not found: {json_path}"}), 200

    paper_folder = os.path.dirname(json_path)

    if not os.path.isfile(RML_MAPPING_PATH):
        return jsonify({"success": False,
                        "error": f"mapping.rml.ttl not found at: {RML_MAPPING_PATH}"}), 500

    # Copy mapping into the paper folder so Docker can reach it
    shutil.copy2(RML_MAPPING_PATH, os.path.join(paper_folder, "mapping.rml.ttl"))

    # Docker on Windows requires forward slashes in -v mounts
    docker_folder = paper_folder.replace("\\", "/")

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{docker_folder}:/data",
        "rmlio/rmlmapper-java",
        "-m", "/data/mapping.rml.ttl",
        "-o", "/data/paper.ttl",
        "-s", "turtle",
        "-b", "http://academickg.org/base/",
        "--duplicates",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "RMLMapper timed out after 120s"}), 500
    except FileNotFoundError:
        return jsonify({"success": False,
                        "error": "docker command not found — is Docker Desktop running?"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if result.returncode != 0:
        return jsonify({"success": False, "error": "RMLMapper exited with errors",
                        "stderr": result.stderr[-2000:]}), 500

    ttl_path = os.path.join(paper_folder, "paper.ttl")
    return jsonify({
        "success":  True,
        "folder":   os.path.basename(paper_folder),
        "ttl_path": ttl_path,
        "triples":  _count_triples(ttl_path),
    }), 200


# ── POST /rml/merge ───────────────────────────────────────────────────────────
@bp.route("/rml/merge", methods=["POST"])
def rml_merge():
    ttl_files = [
        os.path.join(root, fname)
        for root, _, files in os.walk(EXTRACTED_DIR)
        for fname in files
        if fname == "paper.ttl"
    ]

    if not ttl_files:
        return jsonify({"success": False, "error": "No paper.ttl files found"}), 404

    prefix_block = (
        "@prefix bibo:    <http://purl.org/ontology/bibo/> .\n"
        "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
        "@prefix foaf:    <http://xmlns.com/foaf/0.1/> .\n"
        "@prefix schema:  <https://schema.org/> .\n"
        "@prefix prov:    <http://www.w3.org/ns/prov#> .\n"
        "@prefix owl:     <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .\n"
        "@prefix ex:      <https://academickg.org/ontology/> .\n"
        "@prefix :        <https://academickg.org/resource/> .\n\n"
    )

    output_path = os.path.join(EXTRACTED_DIR, "graph.ttl")
    written     = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(prefix_block)
        for ttl_path in sorted(ttl_files):
            with open(ttl_path, "r", encoding="utf-8", errors="ignore") as src:
                for line in src:
                    if not line.startswith("@prefix"):
                        out.write(line)
            written += 1

    return jsonify({"success": True, "merged_files": written, "output_path": output_path}), 200
