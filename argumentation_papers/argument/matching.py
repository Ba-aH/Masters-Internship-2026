import pandas as pd
import os
import re

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
CSV_INPUT = "argumentation.csv"      # Your large metadata file
DOWNLOAD_FOLDER = "downloaded_papers"  # Where your 1500 PDFs are
CSV_OUTPUT = "scrapped_argumentation.csv"

# This must match the sanitize_filename logic used in your downloader script
def sanitize_title_for_match(title):
    if not isinstance(title, str):
        return ""
    # Remove characters that aren't allowed in filenames
    clean = re.sub(r'[<>:"/\\|?*]', '', title).strip('. ')
    # Your downloader likely truncated to 150 or 200 chars
    return clean[:150]

# 1. Load the big metadata file
print(f"📂 Loading {CSV_INPUT}...")
df = pd.read_csv(CSV_INPUT)

# 2. Get the list of files you actually have
print(f"📂 Scanning {DOWNLOAD_FOLDER}...")
downloaded_files = set(os.listdir(DOWNLOAD_FOLDER))
print(f"   Found {len(downloaded_files)} files in folder.")

# 3. Create a matching column in the dataframe
# We create a temporary column that looks exactly like a PDF filename
print("🔍 Matching titles to filenames...")
df['expected_filename'] = df['title'].apply(lambda x: sanitize_title_for_match(x) + ".pdf")

# 4. Filter: Keep only rows where the expected filename exists in the folder
final_df = df[df['expected_filename'].isin(downloaded_files)].copy()

# 5. Cleanup and Save
# Remove the temporary matching column
final_df = final_df.drop(columns=['expected_filename'])

print(f"✅ Match complete!")
print(f"   Original rows: {len(df)}")
print(f"   Matches found: {len(final_df)}")

final_df.to_csv(CSV_OUTPUT, index=False)
print(f"💾 Saved metadata for downloaded papers to: {CSV_OUTPUT}")