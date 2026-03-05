import pandas as pd

def get_pending_downloads(master_path, damaged_path, clean_path, output_path):
    # 1. Load the CSV files
    master_df = pd.read_csv(master_path)
    damaged_df = pd.read_csv(damaged_path)
    clean_df = pd.read_csv(clean_path)

    # 2. Combine clean and damaged into one 'already_attempted' set
    # We focus on 'doi' as the unique key to avoid title mismatch issues
    attempted_dois = pd.concat([damaged_df['doi'], clean_df['doi']]).unique()

    # 3. Filter master_df for rows where the DOI is NOT in the attempted list
    # The '~' symbol means 'NOT'
    to_download_df = master_df[~master_df['doi'].isin(attempted_dois)]

    # 4. Save the result
    to_download_df.to_csv(output_path, index=False)
    
    print(f"Process complete!")
    print(f"Total papers: {len(master_df)}")
    print(f"Clean: {len(clean_df)} | Damaged: {len(damaged_df)}")
    print(f"Remaining to download: {len(to_download_df)}")

# Usage
get_pending_downloads(
    'tutoring.csv', 
    'tutoring_damaged.csv', 
    'tutoring_clean.csv', 
    'tutoring_remaining.csv'
)