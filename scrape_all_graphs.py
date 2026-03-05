#!/usr/bin/env python3
"""
Automated Connected Papers Graph Scraper v5
- Scrapes ALL papers from each graph (not just the main paper)
- Recursive scraping: gets graphs of related papers too
- Incognito mode for better anonymity
- Optimized search with manual fallback suggestions
"""

import json
import os
import time
import sys
import requests
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from urllib.parse import quote

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def setup_driver(user_agent=None):
    """Setup Chrome driver with incognito mode"""
    if user_agent is None:
        user_agent = random.choice(USER_AGENTS)
    
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--incognito')  # INCOGNITO MODE
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-software-rasterizer')
    chrome_options.add_argument(f'user-agent={user_agent}')
    
    # Anti-detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def extract_paper_title_from_filename(filename):
    """Extract paper title from PDF filename"""
    title = filename.replace('.pdf', '')
    title = title.replace('_', ' ')
    return title.strip()


def search_connected_papers_api(paper_title, session=None):
    """Search for paper using Semantic Scholar with fuzzy matching"""
    if session is None:
        session = requests.Session()
    
    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json',
        }
        
        # Try Semantic Scholar with multiple query variations
        print(f"    Searching Semantic Scholar...")
        
        # Variation 1: Exact title
        queries_to_try = [
            paper_title,
            # Remove special characters
            paper_title.replace(':', '').replace('?', '').replace('-', ' '),
            # First 100 chars (for long titles)
            paper_title[:100] if len(paper_title) > 100 else None
        ]
        
        for query in queries_to_try:
            if not query:
                continue
                
            semantic_url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                'query': query,
                'limit': 5,
                'fields': 'paperId,title,externalIds'
            }
            
            response = session.get(semantic_url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('data') and len(data['data']) > 0:
                    # Find best match
                    best_match = None
                    best_score = 0
                    
                    for paper in data['data']:
                        returned_title = paper.get('title', '').lower()
                        search_title = paper_title.lower()
                        
                        # Improved matching
                        search_words = set(search_title.split())
                        returned_words = set(returned_title.split())
                        
                        # Remove common words
                        stopwords = {'a', 'an', 'the', 'for', 'on', 'in', 'with', 'to', 'of', 'and', 'or', 'at', 'by', 'from'}
                        search_words = search_words - stopwords
                        returned_words = returned_words - stopwords
                        
                        if len(search_words) == 0:
                            continue
                        
                        # Calculate match
                        matching = search_words & returned_words
                        score = len(matching) / len(search_words)
                        
                        if score > best_score:
                            best_score = score
                            best_match = paper
                    
                    # Accept matches >= 50%
                    if best_match and best_score >= 0.5:
                        paper_id = best_match.get('paperId')
                        
                        if paper_id:
                            title_slug = paper_title.replace(' ', '-')[:100]
                            graph_url = f"https://www.connectedpapers.com/main/{paper_id}/{quote(title_slug)}/graph"
                            
                            print(f"    ✓ Match {best_score*100:.0f}%: {paper_id[:20]}...")
                            return graph_url
            
            time.sleep(0.5)  # Small delay between variations
        
        return None
        
    except Exception as e:
        print(f"    ⚠️  Error: {str(e)[:50]}")
        return None


def scrape_graph_data(driver, graph_url, density_threshold=0.01, max_retries=2):
    """Scrape the citation graph"""
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait_time = 2 ** attempt
                print(f"    ⏱️  Retry wait: {wait_time}s...")
                time.sleep(wait_time)
            
            driver.get(graph_url)
            
            # Wait for graph
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'g.nodes'))
            )
            time.sleep(5)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract nodes
            nodes = []
            nodes_group = soup.find('g', class_='nodes')
            
            if not nodes_group:
                if attempt < max_retries - 1:
                    continue
                return None, None
            
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
            
            if len(nodes) == 0:
                if attempt < max_retries - 1:
                    continue
                return None, None
            
            # Extract labels
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
            
            # Extract links
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
                        'density': density
                    })
            
            # Filter
            filtered_links = [link for link in all_links if link['density'] >= density_threshold]
            filtered_links.sort(key=lambda x: x['density'], reverse=True)
            
            return nodes, filtered_links
            
        except Exception as e:
            if attempt < max_retries - 1:
                continue
            return None, None
    
    return None, None


def determine_relationship_strength(density):
    """Classify relationship strength"""
    if density >= 0.3:
        return "Very Strong"
    elif density >= 0.15:
        return "Strong"
    elif density >= 0.05:
        return "Moderate"
    else:
        return "Weak"


def match_link_to_nodes(link, nodes):
    """Find which nodes a link connects"""
    x1, y1 = link['x1'], link['y1']
    x2, y2 = link['x2'], link['y2']
    
    source = None
    target = None
    
    for node in nodes:
        dist1 = ((node['cx'] - x1)**2 + (node['cy'] - y1)**2)**0.5
        dist2 = ((node['cx'] - x2)**2 + (node['cy'] - y2)**2)**0.5
        
        if dist1 < 15 and not source:
            source = node
        if dist2 < 15 and not target:
            target = node
            
        if source and target:
            break
    
    return source, target


def build_all_paper_relationships(nodes, links):
    """
    Build relationships for ALL papers in the graph, not just the main one
    Returns dict with all papers as keys
    """
    
    all_papers = {}
    
    # Process each node as a potential main paper
    for main_node in nodes:
        main_title = main_node['title']
        if not main_title:
            continue
        
        related_papers = []
        
        # Find all links involving this paper
        for link in links:
            source, target = match_link_to_nodes(link, nodes)
            
            if not source or not target:
                continue
            
            # Check if link involves current paper
            related_title = None
            if source['id'] == main_node['id']:
                related_title = target['title']
            elif target['id'] == main_node['id']:
                related_title = source['title']
            
            if related_title and related_title != main_title:
                related_papers.append({
                    'title': related_title,
                    'relationship_strength': determine_relationship_strength(link['density'])
                })
        
        # Remove duplicates
        unique_papers = {}
        for paper in related_papers:
            title = paper['title']
            if title not in unique_papers:
                unique_papers[title] = paper
            else:
                strength_order = {"Very Strong": 4, "Strong": 3, "Moderate": 2, "Weak": 1}
                if strength_order.get(paper['relationship_strength'], 0) > strength_order.get(unique_papers[title]['relationship_strength'], 0):
                    unique_papers[title] = paper
        
        if len(unique_papers) > 0:  # Only add if has connections
            all_papers[main_title] = {
                'related_papers': list(unique_papers.values())
            }
    
    return all_papers


def process_pdf_folder(pdf_folder, output_folder='graph_data', density_threshold=0.01, start_from=1, max_papers=None):
    """Process PDFs and extract ALL papers from each graph"""
    
    # Get files
    pdf_files = sorted([f for f in os.listdir(pdf_folder) if f.endswith('.pdf')])
    total = len(pdf_files)
    
    if total == 0:
        print(f"❌ No PDFs found")
        return
    
    if max_papers:
        total = min(total, max_papers)
        pdf_files = pdf_files[:max_papers]
    
    print(f"\n📚 {total} PDF files")
    print(f"📌 Starting from: #{start_from}")
    print(f"🔗 Density threshold: {density_threshold}")
    print(f"🎯 MODE: Extract ALL papers from each graph (not just main paper)")
    print(f"🕵️  Incognito mode enabled")
    print(f"⏱️  Delays: 10-18s between papers")
    print()
    
    os.makedirs(output_folder, exist_ok=True)
    
    # Load existing
    combined_output = os.path.join(output_folder, 'all_citation_graphs.json')
    if os.path.exists(combined_output):
        with open(combined_output, 'r', encoding='utf-8') as f:
            all_graphs = json.load(f)
        print(f"📂 Loaded {len(all_graphs)} existing papers\n")
    else:
        all_graphs = {}
    
    stats = {
        'pdf_processed': 0,
        'pdf_found': 0,
        'pdf_not_found': 0,
        'total_papers_extracted': 0,
        'failed_scrapes': 0,
        'driver_restarts': 0
    }
    
    driver = setup_driver()
    session = requests.Session()
    driver_usage = 0
    
    try:
        for idx, pdf_file in enumerate(pdf_files, 1):
            if idx < start_from:
                continue
            
            paper_title = extract_paper_title_from_filename(pdf_file)
            
            print(f"\n{'='*80}")
            print(f"[{idx}/{total}] {paper_title[:70]}...")
            print(f"{'='*80}")
            
            stats['pdf_processed'] += 1
            
            # Delay
            delay = random.uniform(10, 18)
            print(f"  ⏱️  Delay: {delay:.1f}s...")
            time.sleep(delay)
            
            # Search
            print(f"  🔍 Searching...")
            graph_url = search_connected_papers_api(paper_title, session)
            
            if not graph_url:
                print(f"  ❌ Not found")
                stats['pdf_not_found'] += 1
                continue
            
            stats['pdf_found'] += 1
            print(f"  ✓ URL: ...{graph_url[-50:]}")
            
            time.sleep(random.uniform(3, 5))
            
            # Restart driver periodically
            driver_usage += 1
            if driver_usage >= 25:
                print(f"  🔄 Restarting driver...")
                try:
                    driver.quit()
                except:
                    pass
                time.sleep(3)
                driver = setup_driver()
                driver_usage = 0
                stats['driver_restarts'] += 1
            
            # Scrape
            print(f"  📊 Scraping graph...")
            nodes, links = scrape_graph_data(driver, graph_url, density_threshold)
            
            if not nodes:
                print(f"  ❌ Scrape failed")
                stats['failed_scrapes'] += 1
                time.sleep(20)
                continue
            
            print(f"    ✓ {len(nodes)} nodes, {len(links)} links")
            
            # Extract ALL papers from graph
            print(f"  🔬 Extracting all papers from graph...")
            graph_papers = build_all_paper_relationships(nodes, links)
            
            new_papers = 0
            for paper_title, paper_data in graph_papers.items():
                if paper_title not in all_graphs:
                    all_graphs[paper_title] = paper_data
                    new_papers += 1
            
            stats['total_papers_extracted'] += new_papers
            
            # Save progressively
            with open(combined_output, 'w', encoding='utf-8') as f:
                json.dump(all_graphs, f, indent=2, ensure_ascii=False)
            
            print(f"  ✅ Extracted {len(graph_papers)} papers ({new_papers} new)")
            print(f"  📊 Total in database: {len(all_graphs)} papers")
        
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Interrupted")
    finally:
        try:
            driver.quit()
        except:
            pass
    
    # Save final
    with open(combined_output, 'w', encoding='utf-8') as f:
        json.dump(all_graphs, f, indent=2, ensure_ascii=False)
    
    # Stats file
    stats_file = os.path.join(output_folder, 'scraping_stats.txt')
    with open(stats_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("SCRAPING STATISTICS\n")
        f.write("="*80 + "\n")
        f.write(f"PDF files processed:  {stats['pdf_processed']}\n")
        f.write(f"PDFs found:           {stats['pdf_found']} ({stats['pdf_found']/stats['pdf_processed']*100:.1f}%)\n")
        f.write(f"PDFs not found:       {stats['pdf_not_found']}\n")
        f.write(f"Failed scrapes:       {stats['failed_scrapes']}\n")
        f.write(f"\n")
        f.write(f"PAPERS EXTRACTED FROM GRAPHS:\n")
        f.write(f"Total papers:         {len(all_graphs)}\n")
        f.write(f"New papers added:     {stats['total_papers_extracted']}\n")
        f.write(f"\n")
        f.write(f"Driver restarts:      {stats['driver_restarts']}\n")
        f.write("="*80 + "\n")
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"PDF files processed:  {stats['pdf_processed']}")
    print(f"PDFs found:           {stats['pdf_found']} ({stats['pdf_found']/stats['pdf_processed']*100:.1f}%)")
    print(f"PDFs not found:       {stats['pdf_not_found']}")
    print(f"Failed scrapes:       {stats['failed_scrapes']}")
    print(f"\n🎯 PAPERS EXTRACTED:")
    print(f"Total papers:         {len(all_graphs)}")
    print(f"New papers added:     {stats['total_papers_extracted']}")
    print("="*80)
    print(f"\n✅ {combined_output}")
    print(f"📊 {stats_file}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scrape_all_graphs_v5.py <pdf_folder> [output_folder] [density_threshold] [start_from] [max_papers]")
        print("\nExamples:")
        print("  python scrape_all_graphs_v5.py argumentation_papers/")
        print("  python scrape_all_graphs_v5.py argumentation_papers/ graphs/ 0.01 1 100")
        print("\nFeatures:")
        print("  - Extracts ALL papers from each graph (not just main paper)")
        print("  - Incognito mode")
        print("  - 50% match threshold (more lenient)")
        print("  - 10-18s delays")
        sys.exit(1)
    
    pdf_folder = sys.argv[1]
    output_folder = sys.argv[2] if len(sys.argv) > 2 else 'graph_data'
    density_threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
    start_from = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    max_papers = int(sys.argv[5]) if len(sys.argv) > 5 else None
    
    process_pdf_folder(pdf_folder, output_folder, density_threshold, start_from, max_papers)