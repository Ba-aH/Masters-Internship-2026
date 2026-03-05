import pandas as pd

df = pd.read_csv('not_found_papers.csv')
df = df.drop(['Unnamed: 2', 'Unnamed: 4', 'Unnamed: 3'], axis=1)
df.to_csv('output.csv', index=False)