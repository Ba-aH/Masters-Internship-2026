#!/usr/bin/env python3
import json
import sys

def discretize_strength(density):
    """Convert density to discrete relationship level"""
    if density >= 0.15:
        return "Very Strong"
    elif density >= 0.08:
        return "Strong"
    elif density >= 0.04:
        return "Moderate"
    elif density >= 0.02:
        return "Weak"
    else:
        return "Very Weak"

def build_paper_relationships(json_file='graph_data.json', output_file='paper_relationships.json'):
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    nodes = data['nodes']
    links = data['links']
    
    # Map coordinates to nodes
    coord_to_node = {}
    for node in nodes:
        coord_key = (round(node['cx'], 2), round(node['cy'], 2))
        coord_to_node[coord_key] = node
    
    # Build relationships with density
    relationships = {}
    
    for link in links:
        source_key = (round(link['x1'], 2), round(link['y1'], 2))
        target_key = (round(link['x2'], 2), round(link['y2'], 2))
        
        source_node = coord_to_node.get(source_key)
        target_node = coord_to_node.get(target_key)
        
        if source_node and target_node:
            source_title = source_node.get('title', 'Unknown')
            target_title = target_node.get('title', 'Unknown')
            density = link.get('density', 0)
            
            # Initialize if needed
            if source_title not in relationships:
                relationships[source_title] = {"related_papers": [], "degree": 0}
            if target_title not in relationships:
                relationships[target_title] = {"related_papers": [], "degree": 0}
            
            # Avoid duplicates
            existing_titles_source = [r['title'] for r in relationships[source_title]["related_papers"]]
            existing_titles_target = [r['title'] for r in relationships[target_title]["related_papers"]]
            
            if target_title not in existing_titles_source:
                relationships[source_title]["related_papers"].append({
                    "title": target_title,
                    "relationship_strength": discretize_strength(density),
                    "density_value": round(density, 4)
                })
                relationships[source_title]["degree"] += 1
            
            if source_title not in existing_titles_target:
                relationships[target_title]["related_papers"].append({
                    "title": source_title,
                    "relationship_strength": discretize_strength(density),
                    "density_value": round(density, 4)
                })
                relationships[target_title]["degree"] += 1
    
    # Sort related papers by density value
    for paper in relationships:
        relationships[paper]["related_papers"].sort(
            key=lambda x: x['density_value'], 
            reverse=True
        )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(relationships, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Saved to: {output_file}")
    print(f"   Total papers: {len(relationships)}")
    
    # Show sample
    sample = list(relationships.items())[0]
    print(f"\n📄 Sample:")
    print(f'"{sample[0]}": {{')
    print(f'  "degree": {sample[1]["degree"]},')
    print(f'  "related_papers": [')
    for rel in sample[1]["related_papers"][:3]:
        print(f'    {json.dumps(rel, ensure_ascii=False)},')
    print(f'    ...')
    print(f'  ]\n}}')
    
    # Show strength distribution
    print("\n📊 Relationship Strength Distribution:")
    strength_counts = {"Very Strong": 0, "Strong": 0, "Moderate": 0, "Weak": 0, "Very Weak": 0}
    for paper in relationships.values():
        for rel in paper["related_papers"]:
            strength_counts[rel["relationship_strength"]] += 1
    for strength, count in strength_counts.items():
        print(f"   {strength}: {count}")

if __name__ == '__main__':
    build_paper_relationships()