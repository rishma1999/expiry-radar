import json
import re
import glob

def main():
    # Regex to find standard dates and TODOs with a year.
    # date_pattern: ISO-style dates in code (2024-01-15 or 2024/01/15)
    date_pattern = re.compile(r'20\d{2}[-/]\d{2}[-/]\d{2}')
    # todo_pattern: only match TODO/FIXME/HACK in actual code comments
    # (lines starting with #, //, or /* after optional whitespace) to
    # avoid false positives from prose, docstrings, and author surnames.
    todo_pattern = re.compile(r'(?:#|//|/\*)\s*(?:TODO|FIXME|HACK).*20\d{2}', re.IGNORECASE)
    
    candidates = []
    
    # Find all Python and Markdown files
    files = glob.glob("**/*.py", recursive=True) + glob.glob("**/*.md", recursive=True)
    
    for filepath in files:
        # ignore errors for problematic encodings
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_no, line in enumerate(f, 1):
                if date_pattern.search(line) or todo_pattern.search(line):
                    candidates.append({
                        "file": filepath, 
                        "line": line_no, 
                        "content": line.strip()
                    })
                    
    # Save for IBM Bob to analyze
    with open("candidates.json", "w") as f:
        json.dump(candidates, f, indent=2)
        
    print(f"Found {len(candidates)} expiring items.")

if __name__ == "__main__":
    main()
