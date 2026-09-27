import json

def main():
    deps = []
    
    # Just read requirements.txt directly to keep it simple
    try:
        with open("requirements.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append({
                        "dependency": line, 
                        "source": "requirements.txt"
                    })
    except FileNotFoundError:
        print("No requirements.txt found.")
        
    # Save for IBM Bob to analyze EOL
    with open("eol_candidates.json", "w") as f:
        json.dump(deps, f, indent=2)
        
    print(f"Found {len(deps)} dependencies to check.")

if __name__ == "__main__":
    main()
