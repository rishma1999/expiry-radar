# Expiry Radar Pipeline

This skill orchestrates the Expiry Radar pipeline:
1. Run collectors (Python scripts) to gather data without AI.
2. Spawn 4 parallel subagents to analyze the categories (deprecation, EOL, etc.).
3. Score findings based on urgency and impact.
4. Output results to a timeline dashboard and generate fix PRs.
