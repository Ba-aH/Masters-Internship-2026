import pandas as pd
import re
import sys

def contains_substring(text, substring="argumentation"):
    """Check if substring exists in text (case-insensitive)."""
    if pd.isna(text) or str(text).strip() == "":
        return False
    return substring.lower() in str(text).lower()

def contains_keywords(text, keywords=("argumentation", "formal argumentation")):
    """Check if any of the keywords exist in text (case-insensitive)."""
    if pd.isna(text) or str(text).strip() == "":
        return False
    text_lower = str(text).lower()
    return any(kw.lower() in text_lower for kw in keywords)

def filter_argumentation_papers(input_path: str, output_path: str = None):
    df = pd.read_csv(input_path)
    df.columns = df.columns.str.strip()

    def is_argumentation_paper(row):
        # 1. Check title — substring match
        if contains_substring(row.get("title", "")):
            return True
        # 2. Check abstract — substring match
        if contains_substring(row.get("abstract", "")):
            return True
        # 3. Check keywords — must match "argumentation" or "formal argumentation"
        if contains_substring(row.get("keywords", "")):
            return True
        return False

    df["argumentation"] = df.apply(is_argumentation_paper, axis=1).map({True: "yes", False: "no"})
    
    # Summary stats
    total = len(df)
    matched = (df["argumentation"] == "yes").sum()
    print(f"Total papers     : {total}")
    print(f"Argumentation    : {matched}  ({matched/total*100:.1f}%)")
    print(f"Non-argumentation: {total - matched}  ({(total - matched)/total*100:.1f}%)")

    # Save output
    if output_path is None:
        output_path = input_path.replace(".csv", "_filtered.csv")

    df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")
    return df

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python filter_argumentation.py <input.csv> [output.csv]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    filter_argumentation_papers(input_file, output_file)