import pandas as pd
import os
from difflib import SequenceMatcher
import shutil
import re


df=pd.read_csv('argumentation.csv')
noArgumentation=0
Argumentation=0
drop_rows=[]
for i in range(len(df)):
    keys =df.loc[i,'keywords']
    title=df.loc[i,'title']
    t=str(title)
    t=t.lower()
    k=str(keys)
    k=k.lower()
    if k.find("argumentation")!=-1 or t.find("argumentation")!=-1:
        Argumentation=Argumentation+1
    else:  
        noArgumentation=noArgumentation+1
        
        
print(drop_rows)
print(noArgumentation,"paper that are not for argumentation")
print(Argumentation,"paper that are for argumentation")



# df.drop(drop_rows, inplace=True)
# df.to_csv("argumentation2_filtered.csv",index=False)


# filter duplicates
# df.drop_duplicates(subset=['title'],inplace = True)
# df.to_csv("cleanArgumentation.csv",index=False)

# df = pd.read_csv('argumentation.csv')

# pdf_files = [f.replace('.pdf', '') for f in os.listdir('argumentation2') if f.endswith('.pdf')]

# def clean_text(text):
#     return str(text).lower().replace(':', '').replace('.', '').replace(',', '')

# pdf_clean = [clean_text(p) for p in pdf_files]
# c = 0


# # count the number of papers that are actually downloaded from the csv file eg'argumentation1.csv' and stored in the folder
# for title in df['title']:
#     title_clean = clean_text(title)
#     for pdf in pdf_clean:
#         if SequenceMatcher(None, title_clean, pdf).ratio() >= 0.8:
#             c += 1
#             break
# print(c)

# extract pdf that to be deleted in unmatched_pdfs.txt
# for pdf in pdf_clean:
#     for title in df['title']:
#          title_clean = clean_text(title)
#          if SequenceMatcher(None, title_clean, pdf).ratio() >= 0.8:
      
#             break
#     else:  # PDF didn't match any title
#         with open('unmatched_pdfs.txt', 'a',encoding='utf-8') as f:
#             f.write(f"{pdf}\n")
#             c += 1
# print(c,": dont match")

# def clean_text(text):
#     return str(text).lower().replace(':', '').replace('.', '').replace(',', '')

# with open('unmatched_pdfs.txt', 'r', encoding='utf-8') as f:
#     pdf_names = [line.strip() for line in f]

# deleted = 0
# for name in pdf_names:
#     for file in os.listdir('argumentation2'):
#         if file.endswith('.pdf'):
#             file_clean = clean_text(file.replace('.pdf', ''))
#             if file_clean == name or name in file_clean:
#                 os.remove(os.path.join('argumentation2', file))
#                 deleted += 1
#                 print(f"Deleted: {file}")
#                 break

# print(f"Deleted: {deleted}")