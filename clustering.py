"""
Topic Modeling Pipeline: SBERT → UMAP → HDBSCAN
================================================
Full pipeline with PCA (before) vs UMAP (after) visualization.
"""

import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.decomposition import PCA
from sentence_transformers import SentenceTransformer
import umap
import hdbscan

# ─────────────────────────────────────────────
# STEP 1: Load Data
# ─────────────────────────────────────────────
print("📂 Loading data...")
df = pd.read_csv('argumentation_papers.csv')
print(f"   Loaded {len(df):,} papers.")


# ─────────────────────────────────────────────
# STEP 2: Clean & Prepare Text
# ─────────────────────────────────────────────
def clean_text(text: str) -> str:
    """Remove XML/HTML tags, strip boilerplate headers, collapse whitespace."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)               # remove XML/HTML tags
    text = re.sub(r'(?i)^abstract[:\s]*', '', text)    # strip leading "Abstract:"
    text = re.sub(r'\s+', ' ', text).strip()
    return text

print("🧹 Cleaning and concatenating text fields...")
df['abstract_clean']  = df['abstract'].fillna('').apply(clean_text)
df['keywords_clean']  = df['keywords'].fillna('').apply(clean_text)
df['title_clean']     = df['title'].fillna('').apply(clean_text)

# Format: "Title: ... Keywords: ... Abstract: ..."
df['text_for_embedding'] = (
    "Title: "    + df['title_clean']    + ". "
    "Keywords: " + df['keywords_clean'] + ". "
    "Abstract: " + df['abstract_clean']
)


# ─────────────────────────────────────────────
# STEP 3: Generate Sentence-BERT Embeddings
# ─────────────────────────────────────────────
# all-mpnet-base-v2  → 768-dim, best quality
# all-MiniLM-L6-v2  → 384-dim, faster alternative
MODEL_NAME = 'all-mpnet-base-v2'

print(f"\n🌀 Generating embeddings with '{MODEL_NAME}'...")
print("   (Truncation at 512 tokens is handled automatically by the model.)")
model = SentenceTransformer(MODEL_NAME)
embeddings = model.encode(
    df['text_for_embedding'].tolist(),
    batch_size=64,
    show_progress_bar=True,
    normalize_embeddings=True  # cosine similarity friendly
)
print(f"   Embedding matrix shape: {embeddings.shape}")   # (N_papers, 768)


# ─────────────────────────────────────────────
# STEP 4: Reduce to 5D for Clustering (UMAP)
# ─────────────────────────────────────────────
print("\n📉 Reducing to 5D for clustering (UMAP)...")
umap_5d = umap.UMAP(
    n_neighbors=15,
    n_components=5,  # dimensionality reduction
    metric='cosine',
    random_state=42
).fit_transform(embeddings)


# ─────────────────────────────────────────────
# STEP 5: Cluster with HDBSCAN
# ─────────────────────────────────────────────
print("🧪 Clustering with HDBSCAN...")
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=15,
    metric='euclidean',
    cluster_selection_method='eom' # "Excess of Mass" picks the most persistent clusters; 
                                   # alternative is 'leaf' for more hierarchical/smaller clusters
)
cluster_labels = clusterer.fit_predict(umap_5d)
df['cluster'] = cluster_labels

n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
n_noise    = (cluster_labels == -1).sum()
print(f"   Found {n_clusters} clusters | Noise points: {n_noise:,} ({100*n_noise/len(df):.1f}%)")


# ─────────────────────────────────────────────
# STEP 6: Reduce to 2D for Visualization
# ─────────────────────────────────────────────
print("\n🖼️  Reducing to 2D for visualization...")

# --- "Before": PCA (linear, shows raw 768-D structure) ---
print("   Running PCA...")
pca_2d = PCA(n_components=2, random_state=42).fit_transform(embeddings)

# --- "After": UMAP (non-linear, shows learned cluster structure) ---
print("   Running UMAP 2D...")
umap_2d = umap.UMAP(
    n_neighbors=15,
    n_components=2,
    metric='cosine',
    random_state=42
).fit_transform(embeddings)

df['pca_x']  = pca_2d[:, 0];   df['pca_y']  = pca_2d[:, 1]
df['umap_x'] = umap_2d[:, 0];  df['umap_y'] = umap_2d[:, 1]


# ─────────────────────────────────────────────
# STEP 7: Visualize — Before (PCA) vs After (UMAP)
# ─────────────────────────────────────────────
print("🎨 Plotting...")

# Build a colour palette: noise → grey, clusters → Spectral
unique_labels = sorted(set(cluster_labels))
cmap = plt.cm.get_cmap('Spectral', max(n_clusters, 1))
color_map = {label: ('lightgrey' if label == -1 else cmap(i / max(n_clusters - 1, 1)))
             for i, label in enumerate(unique_labels)}
colors = [color_map[l] for l in cluster_labels]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(22, 9))
fig.suptitle('Research Paper Clusters — SBERT + UMAP + HDBSCAN', fontsize=16, fontweight='bold', y=1.01)

# ── Left: PCA (Before) ──
ax1.scatter(pca_2d[:, 0], pca_2d[:, 1], c=colors, s=4, alpha=0.55, linewidths=0)
ax1.set_title("BEFORE  —  Raw SBERT Space\n(PCA, linear)", fontsize=13, pad=10)
ax1.set_xlabel("PC 1");  ax1.set_ylabel("PC 2")
ax1.text(0.02, 0.97,
         "Each point = 1 paper\nColour = HDBSCAN cluster\nGrey = noise (no cluster)",
         transform=ax1.transAxes, va='top', fontsize=9,
         bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7))

# ── Right: UMAP (After) ──
sc = ax2.scatter(umap_2d[:, 0], umap_2d[:, 1], c=colors, s=4, alpha=0.55, linewidths=0)
ax2.set_title("AFTER  —  Clustered Structure\n(UMAP, non-linear)", fontsize=13, pad=10)
ax2.set_xlabel("UMAP 1");  ax2.set_ylabel("UMAP 2")

# Legend (first 20 clusters + noise)
legend_labels = unique_labels[:20]
handles = [mpatches.Patch(color=color_map[l],
                           label=('Noise (-1)' if l == -1 else f'Cluster {l}'))
           for l in legend_labels]
if len(unique_labels) > 20:
    handles.append(mpatches.Patch(color='white', label=f'… +{len(unique_labels)-20} more'))
ax2.legend(handles=handles, loc='upper right', fontsize=7,
           framealpha=0.8, markerscale=2, ncol=2)

# Stats box
stats_text = (f"Papers:    {len(df):,}\n"
              f"Clusters:  {n_clusters}\n"
              f"Noise:     {n_noise:,}  ({100*n_noise/len(df):.1f}%)")
ax2.text(0.02, 0.97, stats_text, transform=ax2.transAxes, va='top', fontsize=9,
         bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7))

plt.tight_layout()
plt.savefig('cluster_visualization.png', dpi=150, bbox_inches='tight')
plt.show()
print("   Saved → cluster_visualization.png")


# ─────────────────────────────────────────────
# STEP 8: Save Results
# ─────────────────────────────────────────────
df.to_csv('final_clustered_papers.csv', index=False)
print("\n✅ Done! Saved → final_clustered_papers.csv")
print(f"   Columns added: cluster, pca_x, pca_y, umap_x, umap_y, text_for_embedding")

# Quick cluster summary
summary = (df[df['cluster'] != -1]
           .groupby('cluster')
           .size()
           .reset_index(name='paper_count')
           .sort_values('paper_count', ascending=False))
print(f"\n📊 Top 10 clusters by size:\n{summary.head(10).to_string(index=False)}")