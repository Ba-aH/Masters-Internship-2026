import os
import sys
import json
import time
import signal
from pathlib import Path
from paddleocr import PPStructureV3

# --- Configuration ---
SOURCE_DIR = "./papers"
OUTPUT_BASE_DIR = "./extracted"
SCRIPT_DIR = Path(__file__).parent
LOG_FILE = str(SCRIPT_DIR / "processing_log.txt")
REGISTRY_FILE = str(SCRIPT_DIR / "processed_registry.json")

# Initialize Engine (Your specific settings)
engine = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_chart_recognition=False,
    use_formula_recognition=False,
    use_table_recognition=False,
)

# ---------------------------------------------------------------------------
# Registry helpers  (tracks which PDFs have been successfully processed)
# ---------------------------------------------------------------------------

def load_registry() -> dict:
    """Load the processed-files registry from disk, or return a fresh one."""
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r") as f:
            return json.load(f)
    return {"processed": []}


def save_registry(registry: dict) -> None:
    """Persist the registry to disk."""
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def format_duration(seconds: float) -> str:
    """Convert seconds to a human-readable 'Xh Ym Zs' string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def write_log(total_files: int, processed_count: int, elapsed: float,
              session_count: int, session_elapsed: float) -> None:
    """Write/overwrite the progress log with cumulative + session stats."""
    from datetime import datetime
    with open(LOG_FILE, "w") as f:
        f.write("Batch Processing Report\n")
        f.write("-----------------------\n")
        f.write(f"Last updated             : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("\n--- This Session ---\n")
        f.write(f"Session duration         : {format_duration(session_elapsed)}\n")
        f.write(f"Processed this session   : {session_count}\n")
        f.write("\n--- Cumulative ---\n")
        f.write(f"Total time spent         : {format_duration(elapsed)}\n")
        f.write(f"Total processed so far   : {processed_count}\n")
        f.write(f"Total PDFs in source dir : {total_files}\n")
        f.write(f"Remaining                : {total_files - processed_count}\n")


# ---------------------------------------------------------------------------
# Main batch processor
# ---------------------------------------------------------------------------

def batch_process():
    os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

    # Load registry (cumulative state across sessions)
    registry = load_registry()
    processed_set = set(registry["processed"])
    cumulative_seconds = registry.get("total_seconds", 0.0)
    total_processed_ever = len(processed_set)

    # Discover all PDFs
    pdf_files = sorted(f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(".pdf"))
    if not pdf_files:
        print(f"No PDF files found in {SOURCE_DIR}")
        return

    # Separate into pending vs already done
    pending = [f for f in pdf_files if f not in processed_set]
    skipped = len(pdf_files) - len(pending)

    print(f"Found {len(pdf_files)} PDF(s) — "
          f"{skipped} already processed (skipping), "
          f"{len(pending)} to process.")

    if not pending:
        print("Nothing to do. All papers have been processed.")
        return

    # --- Session tracking ---
    session_start = time.time()
    session_count = 0

    # --- Graceful shutdown on Ctrl+C or SIGTERM ---
    def shutdown(signum=None, frame=None):
        session_elapsed = time.time() - session_start
        new_cumulative = cumulative_seconds + session_elapsed

        # Persist registry & log before exiting
        registry["processed"] = sorted(processed_set)
        registry["total_seconds"] = new_cumulative
        save_registry(registry)
        write_log(
            total_files=len(pdf_files),
            processed_count=len(processed_set),
            elapsed=new_cumulative,
            session_count=session_count,
            session_elapsed=session_elapsed,
        )

        print(f"\nShutdown requested — progress saved.")
        print(f"  Session : {session_count} file(s) in {format_duration(session_elapsed)}")
        print(f"  Total   : {len(processed_set)}/{len(pdf_files)} file(s) "
              f"in {format_duration(new_cumulative)}")
        print(f"  Log     : {LOG_FILE}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)   # Ctrl+C
    signal.signal(signal.SIGTERM, shutdown)  # kill / system shutdown

    # --- Process pending files ---
    for pdf_name in pending:
        file_start = time.time()
        pdf_path = os.path.join(SOURCE_DIR, pdf_name)

        folder_name = Path(pdf_name).stem
        save_folder = os.path.join(OUTPUT_BASE_DIR, folder_name)
        os.makedirs(save_folder, exist_ok=True)

        print(f"Processing: {pdf_name}...")

        try:
            output = engine.predict(input=pdf_path)
            for res in output:
                res.save_to_markdown(save_path=save_folder)

            # Mark as done only after a successful run
            processed_set.add(pdf_name)
            session_count += 1
            total_processed_ever += 1

            elapsed_file = time.time() - file_start
            print(f"  ✓ Done in {format_duration(elapsed_file)}")

        except Exception as e:
            print(f"  ✗ Error processing {pdf_name}: {e}")
            # Don't add to registry — it will be retried next run

    # --- All done naturally ---
    shutdown()


if __name__ == "__main__":
    batch_process()