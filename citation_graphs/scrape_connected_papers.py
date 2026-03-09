#!/usr/bin/env python3
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import sys

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    return webdriver.Chrome(options=chrome_options)

def scrape_connected_papers(url, output_file='graph_data.json', density_threshold=0.05):
    driver = setup_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'g.nodes')))
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Extract nodes
        nodes = []
        nodes_group = soup.find('g', class_='nodes')
        if nodes_group:
            for group in nodes_group.find_all('g', recursive=False):
                circle = group.find('circle')
                if circle:
                    nodes.append({
                        'id': circle.get('id', ''),
                        'cx': float(circle.get('cx', 0)),
                        'cy': float(circle.get('cy', 0)),
                        'r': float(circle.get('r', 0)),
                        'title': circle.find('title').text if circle.find('title') else '',
                        'selected': 'selected' in circle.get('filter', '')
                    })
        
        # Extract author/year labels
        for label_class in ['year-labels', 'labels']:
            label_group = soup.find('g', class_=label_class)
            if label_group:
                for text in label_group.find_all('text'):
                    x, y = float(text.get('x', 0)), float(text.get('y', 0))
                    label = text.text.strip()
                    for node in nodes:
                        if ((node['cx'] - x)**2 + (node['cy'] - y)**2)**0.5 < 10:
                            node['author'] = label
                            break
        
        # Extract links with density
        all_links = []
        edges_group = soup.find('g', class_='edges')
        if edges_group:
            for line in edges_group.find_all('line'):
                opacity = float(line.get('stroke-opacity', 0))
                width = float(line.get('stroke-width', 0))
                density = opacity * width
                
                all_links.append({
                    'x1': float(line.get('x1', 0)),
                    'y1': float(line.get('y1', 0)),
                    'x2': float(line.get('x2', 0)),
                    'y2': float(line.get('y2', 0)),
                    'opacity': opacity,
                    'width': width,
                    'density': density
                })
        
        # Filter: keep only HIGH density links (above threshold)
        high_density_links = [link for link in all_links if link['density'] >= density_threshold]
        
        # Sort by density
        high_density_links.sort(key=lambda x: x['density'], reverse=True)
        
        graph_data = {
            'nodes': nodes,
            'links': high_density_links,
            'metadata': {
                'total_nodes': len(nodes),
                'total_links_original': len(all_links),
                'total_links_filtered': len(high_density_links),
                'density_threshold': density_threshold,
                'removed_links': len(all_links) - len(high_density_links),
                'source_url': url
            }
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2)
        
        print(f"Scraped {len(nodes)} nodes")
        print(f"Original links: {len(all_links)}")
        print(f"High-density links (density ≥ {density_threshold}): {len(high_density_links)}")
        print(f"Removed {len(all_links) - len(high_density_links)} low-density links")
        return graph_data
    finally:
        driver.quit()

if __name__ == '__main__':
    # Argumentation papers scrapping
    # url = sys.argv[1] if len(sys.argv) > 1 else "https://www.connectedpapers.com/main/ea54b9405885d72156b1415dc81387c1f68f7825/Argumentation-and-explainable-artificial-intelligence%3A-a-survey/graph"
    # url = sys.argv[1] if len(sys.argv) > 1 else "https://www.connectedpapers.com/main/25535d54d130acec7c665fa6fd35cf4b1215d4cb/Argumentation-Schemes/graph"

    # Social science papers scrapping
    # education papers
    # url = sys.argv[1] if len(sys.argv) > 1 else "https://www.connectedpapers.com/main/f0e641f4d67c5aaeb6d8f5050758a9d3b3266812/Educational-Research%3A-Planning%2C-Conducting%2C-and-Evaluating-Quantitative-and-Qualitative-Research/graph"
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.connectedpapers.com/main/cbad715ec2e0cca4ff74d0751f3f0424535a7cca/PHILOSOPHY-OF-EDUCATION/graph"
    
    # Life science papers scrapping
    # genomics papers
    # url = sys.argv[1] if len(sys.argv) > 1 else "https://www.connectedpapers.com/main/239b7e2422dcff08c87e606dc1b6d10667ddf475/Genomic-sequencing./graph"
    
    
    # Adjust threshold: higher = fewer links (only strongest), lower = more links
    # Default 0.05 keeps ~top 30-40% of links
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
    
    scrape_connected_papers(url, density_threshold=threshold)