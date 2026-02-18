import os

# 収集対象のファイルリスト (絶対パスまたは相対パス)
FILES_TO_COLLECT = [
    "docs/system_design.md",
    "docs/short_term_strategy_design.md",
    "src/analyzers.py",
    "src/backtester.py",
    "config.json",
    "batch_sim_report.md",
    # WalkthroughはBrainディレクトリにあるため、スクリプト実行時にパスを補正
]

# Walkthroughの場所 (現在のセッション用)
WALKTHROUGH_PATH = r"C:\Users\liver\.gemini\antigravity\brain\bad35626-1e58-4603-b46b-05ccf7bb5944\walkthrough.md"
OUTPUT_FILE = "REVIEW_PACKAGE.md"

def main():
    package_content = "# CIO Prototype External Review Package\n\n"
    package_content += "This package contains the current system design, core logic, and latest verification results for v1.4.1.\n\n"
    
    # Walkthroughを最初に追加
    if os.path.exists(WALKTHROUGH_PATH):
        with open(WALKTHROUGH_PATH, "r", encoding="utf-8") as f:
            package_content += f"## FILE: walkthrough.md (Implementation Record)\n```markdown\n{f.read()}\n```\n\n---\n\n"

    for file_path in FILES_TO_COLLECT:
        if os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1].replace(".", "")
            if ext == "py": lang = "python"
            elif ext == "json": lang = "json"
            else: lang = "markdown"

            with open(file_path, "r", encoding="utf-8") as f:
                package_content += f"## FILE: {file_path}\n```{lang}\n{f.read()}\n```\n\n---\n\n"
        else:
            print(f"Warning: File not found: {file_path}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(package_content)

    print(f"Successfully generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
