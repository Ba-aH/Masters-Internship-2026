#!/usr/bin/env python3
import json
import sys

def extract_titles(input_file, output_file):
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    titles = set()
    
    for main_paper in data.keys():
        titles.add(main_paper)
        for related in data[main_paper].get('related_papers', []):
            titles.add(related['title'])
    
    result = {
        "total_papers": len(titles),
        "papers": sorted(list(titles))
    }
    
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python extract_titles.py paper_relationships.json output.json")
        sys.exit(1)
    
    extract_titles(sys.argv[1], sys.argv[2])