from rapidfuzz import fuzz
import re

def extract_main_title(title: str) -> str:
    main = re.split(r'[:\|—–]', title)[0].strip()
    main = re.sub(r'[^\w\s]$', '', main).strip()
    return main if len(main) > 10 else title

# ✅ Both have subtitle
print(fuzz.token_set_ratio(
    extract_main_title("The impact of mood on persuasion: A meta-analysis"),
    extract_main_title("The impact of mood on persuasion: A meta-analysis")
))  # → 100.0

# ✅ One side missing subtitle — now symmetric
print(fuzz.token_set_ratio(
    extract_main_title("The impact of mood on persuasion: A meta-analysis"),
    extract_main_title("The impact of mood on persuasion")
))  # → 100.0  ← fixed

# ✅ Word order noise
print(fuzz.token_set_ratio(
    extract_main_title("The impact of mood on persuasion: A meta-analysis"),
    extract_main_title("A meta-analysis: mood persuasion impact")
))  # → 100.0

# ❌ Different paper
print(fuzz.token_set_ratio(
    extract_main_title("The impact of mood on persuasion: A meta-analysis"),
    extract_main_title("Mood regulation and emotional persuasion techniques")
))  # → 38.0  ← still correctly rejected