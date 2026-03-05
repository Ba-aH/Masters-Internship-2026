#!/usr/bin/env python3
"""
PDF Health Checker
- Checks all PDFs in a folder for corruption
- Returns list of damaged files
- Saves results to CSV and TXT
"""

import os
import sys
import csv
from pathlib import Path

def check_pdf(filepath):
    """
    Check if a PDF is valid by:
    1. Checking file size (> 1KB)
    2. Checking PDF header (%PDF)
    3. Checking PDF footer (%%EOF)
    4. Trying to parse with PyPDF2 if available
    """
    errors = []
    
    try:
        size = os.path.getsize(filepath)
        
        # Check 1: File size
        if size < 1000:
            errors.append(f"Too small ({size} bytes)")
            return False, errors
        
        # Check 2: PDF header
        with open(filepath, 'rb') as f:
            header = f.read(8)
            if not header.startswith(b'%PDF'):
                errors.append(f"Invalid header: {header[:8]}")
                return False, errors
        
        # Check 3: PDF footer (%%EOF somewhere near end)
        with open(filepath, 'rb') as f:
            f.seek(max(0, size - 2048))  # Read last 2KB
            tail = f.read()
            if b'%%EOF' not in tail and b'%%EO' not in tail:
                errors.append("Missing %%EOF marker")
                # Don't return False yet, some valid PDFs miss this
        
        # Check 4: Try PyPDF2 for deep validation
        try:
            import pypdf
            with open(filepath, 'rb') as f:
                reader = pypdf.PdfReader(f, strict=False)
                num_pages = len(reader.pages)
                if num_pages == 0:
                    errors.append("Zero pages")
                    return False, errors
                # Try reading first page
                _ = reader.pages[0]
            
            if errors:
                return False, errors  # Has issues (like missing EOF) but readable
            return True, []
            
        except ImportError:
            # pypdf not installed, use basic checks only
            if errors:
                return False, errors
            return True, []
            
        except Exception as e:
            errors.append(f"Parse error: {str(e)[:80]}")
            return False, errors
    
    except Exception as e:
        errors.append(f"Cannot read: {str(e)[:80]}")
        return False, errors


def check_folder(pdf_folder, output_folder=None):
    """Check all PDFs in folder and report damaged ones"""
    
    if not os.path.exists(pdf_folder):
        print(f"❌ Folder not found: {pdf_folder}")
        sys.exit(1)
    
    # Get all PDFs
    pdf_files = sorted([f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')])
    total = len(pdf_files)
    
    if total == 0:
        print(f"❌ No PDF files found in: {pdf_folder}")
        sys.exit(1)
    
    print(f"\n📂 Folder: {pdf_folder}")
    print(f"📚 Found {total} PDF files to check")
    
    # Check if pypdf is available
    try:
        import pypdf
        print(f"✓ Using PyPDF for deep validation")
    except ImportError:
        print(f"⚠️  PyPDF not installed - using basic checks only")
        print(f"   Install with: pip install pypdf")
    
    print()
    
    # Results
    damaged = []
    ok = []
    
    for idx, pdf_file in enumerate(pdf_files, 1):
        filepath = os.path.join(pdf_folder, pdf_file)
        
        # Progress
        print(f"\r  Checking [{idx}/{total}] {pdf_file[:60]:<60}", end='', flush=True)
        
        is_valid, errors = check_pdf(filepath)
        
        if is_valid:
            ok.append(pdf_file)
        else:
            damaged.append({
                'filename': pdf_file,
                'filepath': filepath,
                'errors': '; '.join(errors),
                'size_bytes': os.path.getsize(filepath) if os.path.exists(filepath) else 0
            })
    
    print()  # Newline after progress
    
    # Output folder
    if output_folder is None:
        output_folder = pdf_folder
    os.makedirs(output_folder, exist_ok=True)
    
    # Save damaged list as TXT
    txt_output = os.path.join(output_folder, 'damaged_pdfs.txt')
    with open(txt_output, 'w', encoding='utf-8') as f:
        f.write(f"DAMAGED PDF FILES REPORT\n")
        f.write(f"{'='*60}\n")
        f.write(f"Total checked:  {total}\n")
        f.write(f"OK:             {len(ok)}\n")
        f.write(f"Damaged:        {len(damaged)}\n")
        f.write(f"{'='*60}\n\n")
        
        if damaged:
            f.write("DAMAGED FILES:\n")
            f.write("-"*60 + "\n")
            for i, item in enumerate(damaged, 1):
                f.write(f"{i}. {item['filename']}\n")
                f.write(f"   Error: {item['errors']}\n")
                f.write(f"   Size:  {item['size_bytes']:,} bytes\n\n")
        else:
            f.write("✅ No damaged files found!\n")
    
    # Save damaged list as CSV (for easy re-downloading)
    csv_output = os.path.join(output_folder, 'damaged_pdfs.csv')
    with open(csv_output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['filename', 'filepath', 'errors', 'size_bytes'])
        writer.writeheader()
        writer.writerows(damaged)
    
    # Save just filenames as a simple list (easy to use with download script)
    names_output = os.path.join(output_folder, 'damaged_names_only.txt')
    with open(names_output, 'w', encoding='utf-8') as f:
        for item in damaged:
            # Write the paper title (filename without .pdf)
            title = item['filename'].replace('.pdf', '').replace('_', ' ')
            f.write(title + '\n')
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Total checked:  {total}")
    print(f"✅ OK:          {len(ok)} ({len(ok)/total*100:.1f}%)")
    print(f"❌ Damaged:     {len(damaged)} ({len(damaged)/total*100:.1f}%)")
    print(f"{'='*60}")
    
    if damaged:
        print(f"\n❌ DAMAGED FILES:")
        for i, item in enumerate(damaged, 1):
            size_kb = item['size_bytes'] / 1024
            print(f"  {i:3d}. {item['filename'][:65]}")
            print(f"       Error: {item['errors'][:70]}")
            print(f"       Size:  {size_kb:.1f} KB")
        
        print(f"\n📄 Reports saved:")
        print(f"  Full report:  {txt_output}")
        print(f"  CSV list:     {csv_output}")
        print(f"  Titles only:  {names_output}")
        print(f"\n💡 To re-download damaged files:")
        print(f"   Use damaged_names_only.txt as input to your download script")
    else:
        print(f"\n✅ All PDFs are healthy!")
    
    return damaged


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python check_pdfs.py <pdf_folder> [output_folder]")
        print("\nExamples:")
        print("  python check_pdfs.py downloaded_papers/")
        print("  python check_pdfs.py downloaded_papers/ reports/")
        print("\nOutputs:")
        print("  damaged_pdfs.txt       - Full report with errors")
        print("  damaged_pdfs.csv       - CSV for processing")
        print("  damaged_names_only.txt - Paper titles for re-downloading")
        print("\nInstall deep validation:")
        print("  pip install pypdf")
        sys.exit(1)
    
    pdf_folder = sys.argv[1]
    output_folder = sys.argv[2] if len(sys.argv) > 2 else None
    
    check_folder(pdf_folder, output_folder)
