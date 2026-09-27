import json
import re
import sys
from pathlib import Path

def scan_for_dates(target_dir):
    """
    Scans files in the target directory for hardcoded dates and TODOs.
    Specifically useful for finding deprecated IBM/Qiskit API calls that have a future removal date.
    """
    # Regex to find standard date formats (e.g., 2025-01-01)
    date_pattern = re.compile(r'\b(20\d{2}[-/]\d{2}[-/]\d{2})\b')
    # Regex to find TODOs that contain a year
    todo_pattern = re.compile(r'(?i)TODO.*?(20\d{2})')
    
    candidates = []
    target_path = Path(target_dir)
    
    # Iterate through all files in the directory
    for filepath in target_path.rglob('*'):
        # Only check code and text files to avoid binary files
        if filepath.suffix not in ['.py', '.md', '.txt', '.json', '.yaml']:
            continue
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    # If we find a date or a TODO, save it as a candidate
                    if date_pattern.search(line) or todo_pattern.search(line):
                        candidates.append({
                            "file": str(filepath),
                            "line": line_no,
                            "content": line.strip(),
                            "type": "date_or_todo"
                        })
        except Exception:
            # Skip files that cannot be read
            pass
            
    return candidates

def main():
    # Use the first argument as target directory, or default to current directory
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
        
    print(f"Collecting hardcoded dates and TODOs in {target_dir}...")
    candidates = scan_for_dates(target_dir)
    
    # Write the candidates to a JSON file for the Bob agent to process
    with open("candidates.json", "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"Found {len(candidates)} date/TODO candidates.")

if __name__ == "__main__":
    main()
