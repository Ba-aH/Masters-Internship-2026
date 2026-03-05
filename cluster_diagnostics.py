"""
Cluster Diagnostics & Insights
================================
Run this AFTER topic_modeling_pipeline.py has produced:
  - final_clustered_papers.csv
  - the `embeddings` numpy array (still in memory), OR re-embed below.

If you are running this as a standalone script, set RECOMPUTE_EMBEDDINGS = True.
If you are appending this to the end of the pipeline script, set it to False.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
import seaborn as sns
from sklearn.metrics import silhouette_score, silhouette_samples
from sklearn.metrics.pairwise import cosine_similarity
from collections import Counter
import textwrap, warnings
warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
RECOMPUTE_EMBEDDINGS = True   # Set False if embeddings already in memory
CSV_PATH             = 'final_clustered_papers.csv'
MODEL_NAME           = 'all-mpnet-base-v2'
TOP_KEYWORDS_PER_CLUSTER = 15
TOP_PAPERS_PER_CLUSTER   = 3
# ─────────────────────────────────────────────────────────────────────────────

print("📂 Loading clustered data...")
df = pd.read_csv(CSV_PATH)
cluster_labels = df['cluster'].values
n_total    = len(df)
n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
n_noise    = (cluster_labels == -1).sum()

if RECOMPUTE_EMBEDDINGS:
    print(f"🌀 Re-generating embeddings with '{MODEL_NAME}'...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        df['text_for_embedding'].tolist(),
        batch_size=64, show_progress_bar=True, normalize_embeddings=True
    )

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — GLOBAL HEALTH REPORT
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  CLUSTER HEALTH REPORT")
print("═"*60)

clustered_mask = cluster_labels != -1
pct_noise      = 100 * n_noise / n_total
pct_clustered  = 100 - pct_noise

print(f"\n  Total papers    : {n_total:>6,}")
print(f"  Clusters found  : {n_clusters:>6}")
print(f"  Clustered papers: {clustered_mask.sum():>6,}  ({pct_clustered:.1f}%)")
print(f"  Noise points    : {n_noise:>6,}  ({pct_noise:.1f}%)")

# Silhouette Score (only on clustered points)
if clustered_mask.sum() > 1 and n_clusters > 1:
    print("\n  ⏳ Computing Silhouette Score (this may take ~30s)...")
    sil_score = silhouette_score(
        embeddings[clustered_mask], cluster_labels[clustered_mask], metric='cosine'
    )
    sil_samples = silhouette_samples(
        embeddings[clustered_mask], cluster_labels[clustered_mask], metric='cosine'
    )
    print(f"\n  Silhouette Score: {sil_score:.4f}")
    if sil_score > 0.5:
        verdict = "🟢 STRONG — clusters are well-separated and cohesive"
    elif sil_score > 0.25:
        verdict = "🟡 MODERATE — reasonable separation, some overlap"
    else:
        verdict = "🔴 WEAK — clusters overlap significantly; consider tuning"
    print(f"  Verdict         : {verdict}")
else:
    sil_score = None; sil_samples = None

# Noise diagnosis
print(f"\n  Noise Diagnosis:")
if pct_noise > 50:
    print("  🔴 >50% noise — dataset is very heterogeneous OR min_cluster_size is too high.")
    print("     → Try: min_cluster_size=5 or min_cluster_size=10")
elif pct_noise > 30:
    print("  🟡 30-50% noise — many niche/unique papers. Common in specialized corpora.")
    print("     → Try: min_cluster_size=10, or min_samples=5 in HDBSCAN")
else:
    print("  🟢 <30% noise — healthy ratio for academic literature.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PER-CLUSTER STATISTICS TABLE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  PER-CLUSTER STATISTICS")
print("═"*60)

cluster_stats = []
for cid in sorted(set(cluster_labels)):
    mask = cluster_labels == cid
    count = mask.sum()
    label = "NOISE" if cid == -1 else str(cid)
    
    # Intra-cluster cosine similarity (cohesion)
    if count > 1 and cid != -1:
        emb_sub = embeddings[mask]
        sim_matrix = cosine_similarity(emb_sub)
        np.fill_diagonal(sim_matrix, np.nan)
        avg_sim = np.nanmean(sim_matrix)
    else:
        avg_sim = np.nan

    cluster_stats.append({
        'cluster': label,
        'papers': count,
        'pct_of_total': 100 * count / n_total,
        'avg_intra_similarity': avg_sim
    })

stats_df = pd.DataFrame(cluster_stats)
# Sort: noise last, clusters by size
noise_row    = stats_df[stats_df['cluster'] == 'NOISE']
cluster_rows = stats_df[stats_df['cluster'] != 'NOISE'].sort_values('papers', ascending=False)
stats_df     = pd.concat([cluster_rows, noise_row]).reset_index(drop=True)

print(f"\n  {'Cluster':<10} {'Papers':>8} {'% Total':>9} {'Avg Cosine Sim':>16}  {'Cohesion'}")
print("  " + "─"*58)
for _, row in stats_df.iterrows():
    sim_str = f"{row['avg_intra_similarity']:.3f}" if not np.isnan(row['avg_intra_similarity']) else "  —   "
    if not np.isnan(row['avg_intra_similarity']):
        cohesion = "🟢 High" if row['avg_intra_similarity'] > 0.5 else \
                   "🟡 Med"  if row['avg_intra_similarity'] > 0.3 else "🔴 Low"
    else:
        cohesion = ""
    print(f"  {row['cluster']:<10} {int(row['papers']):>8,} {row['pct_of_total']:>8.1f}%"
          f" {sim_str:>16}  {cohesion}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — KEYWORD FINGERPRINT PER CLUSTER
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*60)
print("  KEYWORD FINGERPRINT PER CLUSTER (Top Keywords)")
print("═"*60)

# Stopwords to filter from keywords
STOPWORDS = {
    'a','an','the','and','or','of','in','to','for','with','on','at','by','from',
    'is','are','was','were','be','been','being','have','has','had','do','does',
    'did','will','would','could','should','may','might','shall','can','this',
    'that','these','those','it','its','we','our','their','which','who','what',
    'how','when','where','also','using','based','via','study','paper','research',
    'proposed','method','approach','results','analysis','data','used','use',
    'new','two','three','different','various','both','high','low','large','small'
}

def extract_top_keywords(texts, n=TOP_KEYWORDS_PER_CLUSTER):
    """Count word frequencies, filter stopwords, return top-n."""
    words = []
    for t in texts:
        if isinstance(t, str):
            # Use the keywords field if it's a delimited list, else tokenize
            for w in t.lower().replace(',', ' ').replace(';', ' ').split():
                w = w.strip('.()"\'')
                if len(w) > 3 and w not in STOPWORDS and not w.isdigit():
                    words.append(w)
    return Counter(words).most_common(n)

print()
for cid in sorted(set(cluster_labels)):
    if cid == -1:
        continue
    mask  = cluster_labels == cid
    texts = df.loc[mask, 'keywords_clean'].fillna('') + ' ' + \
            df.loc[mask, 'abstract_clean'].fillna('')
    top_kw = extract_top_keywords(texts.tolist())
    kw_str = ', '.join([f"{w}({c})" for w, c in top_kw[:10]])
    print(f"  Cluster {cid:>2}  [{mask.sum():>3} papers]")
    print(f"    {kw_str}")
    
    # Show representative paper titles
    titles = df.loc[mask, 'title'].dropna().head(TOP_PAPERS_PER_CLUSTER).tolist()
    for t in titles:
        print(f"    📄 {textwrap.shorten(t, width=80, placeholder='...')}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — VISUALIZATIONS
# ══════════════════════════════════════════════════════════════════════════════
print("🎨 Generating diagnostic plots...")

fig = plt.figure(figsize=(24, 18))
fig.suptitle('Cluster Diagnostics Dashboard', fontsize=18, fontweight='bold', y=0.98)
gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.35)

# ── Plot 1: Cluster Size Bar Chart ──────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
plot_df = cluster_rows.copy()  # exclude noise
colors_bar = plt.cm.Spectral(np.linspace(0.1, 0.9, len(plot_df)))
bars = ax1.barh(plot_df['cluster'].astype(str), plot_df['papers'], color=colors_bar)
ax1.bar_label(bars, fmt='%d', padding=3, fontsize=9)
ax1.axvline(plot_df['papers'].mean(), color='red', linestyle='--', linewidth=1, label=f"Mean: {plot_df['papers'].mean():.0f}")
ax1.set_title('Papers per Cluster', fontweight='bold')
ax1.set_xlabel('Number of Papers')
ax1.set_ylabel('Cluster ID')
ax1.legend(fontsize=9)
ax1.invert_yaxis()

# ── Plot 2: Noise vs Clustered Pie ──────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
sizes  = [n_total - n_noise, n_noise]
labels = [f'Clustered\n{n_total-n_noise} ({pct_clustered:.1f}%)',
          f'Noise\n{n_noise} ({pct_noise:.1f}%)']
colors_pie = ['#4CAF50', '#FF7043']
wedges, texts, autotexts = ax2.pie(
    sizes, labels=labels, colors=colors_pie,
    autopct='%1.1f%%', startangle=90,
    wedgeprops=dict(edgecolor='white', linewidth=2)
)
ax2.set_title('Clustered vs Noise Papers', fontweight='bold')

# ── Plot 3: Intra-cluster Cohesion ──────────────────────────────────────────
ax3 = fig.add_subplot(gs[0, 2])
cohesion_df = cluster_rows.dropna(subset=['avg_intra_similarity'])
bar_colors  = ['#4CAF50' if v > 0.5 else '#FFC107' if v > 0.3 else '#F44336'
               for v in cohesion_df['avg_intra_similarity']]
ax3.bar(cohesion_df['cluster'].astype(str), cohesion_df['avg_intra_similarity'], color=bar_colors)
ax3.axhline(0.5, color='green',  linestyle='--', linewidth=1, label='High (0.5)')
ax3.axhline(0.3, color='orange', linestyle='--', linewidth=1, label='Med (0.3)')
ax3.set_title('Intra-Cluster Cohesion\n(Avg Cosine Similarity)', fontweight='bold')
ax3.set_xlabel('Cluster ID')
ax3.set_ylabel('Avg Cosine Similarity')
ax3.set_ylim(0, 1)
ax3.legend(fontsize=9)

# ── Plot 4: UMAP scatter coloured by cluster (larger, annotated) ─────────────
ax4 = fig.add_subplot(gs[1, :2])
cmap = plt.cm.get_cmap('Spectral', max(n_clusters, 1))

# Plot noise first (background)
noise_mask = cluster_labels == -1
ax4.scatter(df.loc[noise_mask, 'umap_x'], df.loc[noise_mask, 'umap_y'],
            c='lightgrey', s=6, alpha=0.3, label='Noise', zorder=1)

# Plot clusters, annotate centroid
for i, cid in enumerate(sorted(set(cluster_labels) - {-1})):
    mask = cluster_labels == cid
    color = cmap(i / max(n_clusters - 1, 1))
    ax4.scatter(df.loc[mask, 'umap_x'], df.loc[mask, 'umap_y'],
                c=[color], s=8, alpha=0.7, zorder=2)
    cx = df.loc[mask, 'umap_x'].mean()
    cy = df.loc[mask, 'umap_y'].mean()
    ax4.annotate(f'C{cid}\n({mask.sum()})', (cx, cy),
                 fontsize=8, ha='center', va='center', fontweight='bold',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.75, ec='grey'))

ax4.set_title('UMAP 2D — Cluster Map with Centroids & Sizes', fontweight='bold')
ax4.set_xlabel('UMAP 1');  ax4.set_ylabel('UMAP 2')

# ── Plot 5: Silhouette per cluster ──────────────────────────────────────────
ax5 = fig.add_subplot(gs[1, 2])
if sil_samples is not None:
    y_lower = 10
    clustered_labels_only = cluster_labels[clustered_mask]
    for i, cid in enumerate(sorted(set(clustered_labels_only))):
        c_sil = sil_samples[clustered_labels_only == cid]
        c_sil.sort()
        size_c = len(c_sil)
        y_upper = y_lower + size_c
        color = cmap(i / max(n_clusters - 1, 1))
        ax5.fill_betweenx(np.arange(y_lower, y_upper), 0, c_sil, color=color, alpha=0.8)
        ax5.text(-0.05, y_lower + size_c / 2, f'C{cid}', ha='right', va='center', fontsize=7)
        y_lower = y_upper + 5
    ax5.axvline(sil_score, color='red', linestyle='--', linewidth=1.5,
                label=f'Avg: {sil_score:.3f}')
    ax5.set_title('Silhouette Plot\n(wider = better cohesion)', fontweight='bold')
    ax5.set_xlabel('Silhouette Coefficient')
    ax5.set_ylabel('Papers (stacked by cluster)')
    ax5.legend(fontsize=9)
else:
    ax5.text(0.5, 0.5, 'Silhouette\nnot computed', ha='center', va='center',
             transform=ax5.transAxes, fontsize=14, color='grey')
    ax5.set_title('Silhouette Plot', fontweight='bold')

plt.savefig('cluster_diagnostics.png', dpi=150, bbox_inches='tight')
plt.show()
print("   Saved → cluster_diagnostics.png")



# Save stats table
stats_df.to_csv('cluster_statistics.csv', index=False)
print("  📊 Saved cluster_statistics.csv\n")
