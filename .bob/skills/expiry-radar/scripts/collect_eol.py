import json
import sys
import tomllib
from pathlib import Path

def get_dependencies(target_dir):
    """
    Reads pyproject.toml and requirements.txt to extract dependencies.
    Useful for checking IBM specific packages like 'qiskit', 'qiskit-aer', etc.
    """
    target_path = Path(target_dir)
    deps = {}
    
    # 1. Check pyproject.toml
    pyproject = target_path / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
                # Extract standard dependencies
                project_deps = data.get("project", {}).get("dependencies", [])
                for dep in project_deps:
                    deps[dep] = "pyproject.toml"
        except Exception as e:
            print(f"Error parsing pyproject.toml: {e}")
            
    # 2. Check requirements.txt
    req_txt = target_path / "requirements.txt"
    if req_txt.exists():
        try:
            with open(req_txt, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Ignore empty lines and comments
                    if line and not line.startswith("#"):
                        deps[line] = "requirements.txt"
        except Exception as e:
            print(f"Error parsing requirements.txt: {e}")
            
    # Format the extracted dependencies into a list of dictionaries
    return [{"dependency": k, "source_file": v} for k, v in deps.items()]

def main():
    # Use the first argument as target directory, or default to current directory
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
        
    print(f"Collecting dependencies for EOL check in {target_dir}...")
    deps = get_dependencies(target_dir)
    
    # Write the dependencies to a JSON file for the Bob agent to process
    with open("eol_candidates.json", "w") as f:
        json.dump(deps, f, indent=2)
    print(f"Found {len(deps)} dependencies.")

if __name__ == "__main__":
    main()
