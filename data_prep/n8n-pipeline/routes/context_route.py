import os

from flask import Blueprint, jsonify

from config import EXTRACTED_DIR
from services.context import extract_context_for_folder

bp = Blueprint("context", __name__)

CONTEXT_FILENAME = "context.json"


@bp.route("/extract_context/<path:folder>", methods=["GET"])
def check_context(folder):
    context_path = os.path.join(EXTRACTED_DIR, folder, CONTEXT_FILENAME)
    return jsonify({
        "folder": folder,
        "exists": os.path.isfile(context_path),
        "path":   context_path,
    }), 200


@bp.route("/extract_context/<path:folder>", methods=["POST"])
def extract_context(folder):
    try:
        result = extract_context_for_folder(folder)
    except Exception as e:
        return jsonify({"skipped": True, "reason": str(e), "folder": folder}), 200

    context_path = os.path.join(EXTRACTED_DIR, folder, CONTEXT_FILENAME)
    try:
        import json
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return jsonify({"skipped": True, "reason": f"Failed to write context.json: {e}", "folder": folder}), 200

    return jsonify({
        "folder":          folder,
        "context_path":    context_path,
        "paper_id":        result["paper_id"],
        "total_citations": result["total_citations"],
        "skipped":         False,
    }), 200
