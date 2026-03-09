import pandas as pd



files = ['argumentation1.csv', 'argumentation2.csv', 'argumentation3.csv']
df_list = []
for file in files:
    df = pd.read_csv(file)
    df_list.append(df)

merged_df = pd.concat(df_list, ignore_index=True)
merged_df.to_csv('argumentation1.csv', index=False)

