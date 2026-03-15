#!/usr/bin/env python3
"""
Review Issues Verification Script
Tests the validity of the code review findings
"""

import sys
import os
import json
import re

# Change to project directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

print("=" * 70)
print("PROJECT REVIEW VERIFICATION TESTS")
print("=" * 70)

# =============================================================================
# Test 1: Circular Import Risk (Issue #1)
# =============================================================================
print("\n[TEST 1] Circular Import Risk")
print("-" * 50)
try:
    # This should work if circular import is properly handled
    from src.edinet_client import extract_yuho_data
    from src.data_fetcher import call_gemini
    from src.analyzers import generate_scorecard
    from src.sec_client import extract_sec_data
    print("✅ PASS: All modules import without circular import errors")
    print("   Note: Circular import is avoided via function-level imports")
except ImportError as e:
    print(f"❌ FAIL: Circular import detected: {e}")

# =============================================================================
# Test 2: API Key Management Inconsistency (Issue #2)
# =============================================================================
print("\n[TEST 2] API Key Management Inconsistency")
print("-" * 50)

# Check .env.example
with open('.env.example', 'r') as f:
    env_example = f.read()

# Check config.json
with open('config.json', 'r') as f:
    config = json.load(f)

issues = []

# Check for GOOGLE_SHEETS_KEY_PATH in .env.example but not in config
if 'GOOGLE_SHEETS_KEY_PATH' in env_example:
    if 'google_sheets_key_path' not in str(config).lower():
        issues.append("GOOGLE_SHEETS_KEY_PATH in .env.example but not in config.json")

# Check for SPREADSHEET_ID inconsistency
if 'spreadsheet_id' in env_example.lower():
    if 'spreadsheet_id' not in config:
        issues.append("SPREADSHEET_ID in .env but config uses 'spreadsheet_id' key")

# Check for GOOGLE_SERVICE_ACCOUNT_JSON
if 'GOOGLE_SERVICE_ACCOUNT_JSON' in env_example:
    # Check if config expects JSON string or file path
    if 'google_service_account' in str(config).lower():
        issues.append(" GOOGLE_SERVICE_ACCOUNT_JSON format unclear (JSON vs file path)")

if issues:
    print("⚠️  PARTIAL: API key management inconsistencies found:")
    for issue in issues:
        print(f"   - {issue}")
else:
    print("✅ PASS: No obvious API key management inconsistencies")

# =============================================================================
# Test 3: Error Handling Inconsistency (Issue #3)
# =============================================================================
print("\n[TEST 3] Error Handling Inconsistency")
print("-" * 50)

# Check for silent failures vs exception propagation
files_to_check = [
    'src/data_fetcher.py',
    'src/edinet_client.py',
    'src/sec_client.py',
    'src/dcf_model.py',
    'main.py'
]

silent_fail_count = 0
exception_propagate_count = 0

for filepath in files_to_check:
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Count bare except clauses that return default values
    silent_fails = re.findall(r'except\s+(?:Exception|ImportError)?:\s*\n\s*return\s+({}|\[\]|None|""|0)', content)
    silent_fail_count += len(silent_fails)
    
    # Count except clauses that re-raise
    re_raises = re.findall(r'except.*:\n\s*.*raise', content)
    exception_propagate_count += len(re_raises)

print(f"   Silent failures (return default): {silent_fail_count}")
print(f"   Exception propagation (raise): {exception_propagate_count}")

if silent_fail_count > 5:
    print("⚠️  PARTIAL: High number of silent failures detected")
else:
    print("✅ PASS: Error handling is reasonable")

# =============================================================================
# Test 4: Config.json Bloat (Issue #4)
# =============================================================================
print("\n[TEST 4] Config.json Bloat")
print("-" * 50)

with open('config.json', 'r') as f:
    config_content = f.read()
    config = json.loads(config_content)

line_count = len(config_content.split('\n'))
key_count = len(str(config).replace(',', '\n').split('\n'))

print(f"   Lines: {line_count}")
print(f"   Config keys (approx): {key_count}")

# Check nesting depth
def get_depth(obj, current=0):
    if isinstance(obj, dict):
        return max((get_depth(v, current + 1) for v in obj.values()), default=current)
    elif isinstance(obj, list):
        return max((get_depth(v, current + 1) for v in obj), default=current)
    return current

max_depth = get_depth(config)
print(f"   Max nesting depth: {max_depth}")

if line_count > 300:
    print("⚠️  PARTIAL: Config file is large (>300 lines)")
if max_depth > 5:
    print("⚠️  PARTIAL: Deep nesting detected (>5 levels)")
if line_count <= 300 and max_depth <= 5:
    print("✅ PASS: Config size is reasonable")

# =============================================================================
# Test 5: Main.py Responsibility (Issue #5)
# =============================================================================
print("\n[TEST 5] Main.py Responsibility Separation")
print("-" * 50)

with open('main.py', 'r') as f:
    main_content = f.read()

line_count = len(main_content.split('\n'))
function_count = len(re.findall(r'^def\s+\w+', main_content, re.MULTILINE))
class_count = len(re.findall(r'^class\s+\w+', main_content, re.MULTILINE))

print(f"   Lines: {line_count}")
print(f"   Functions: {function_count}")
print(f"   Classes: {class_count}")

# Check for multiple responsibilities
responsibilities = []
if 'def analyze_all' in main_content:
    responsibilities.append("Analysis logic")
if 'def save_to_dashboard_json' in main_content:
    responsibilities.append("Data persistence")
if 'def run(' in main_content:
    responsibilities.append("Orchestration")
if 'import yfinance' in main_content:
    responsibilities.append("Data fetching")

print(f"   Responsibilities: {', '.join(responsibilities)}")

if line_count > 500:
    print("⚠️  PARTIAL: main.py is large (>500 lines)")
if len(responsibilities) > 3:
    print("⚠️  PARTIAL: Multiple responsibilities detected")
if line_count <= 500 and len(responsibilities) <= 2:
    print("✅ PASS: Responsibility separation is reasonable")

# =============================================================================
# Test 6: Test Coverage Gaps (Issue #6)
# =============================================================================
print("\n[TEST 6] Test Coverage Gaps")
print("-" * 50)

import glob
test_files = glob.glob('test*.py') + glob.glob('**/test*.py', recursive=True)
print(f"   Test files found: {len(test_files)}")
for tf in test_files:
    print(f"      - {tf}")

# Check for unit tests vs integration tests
unit_test_keywords = ['unittest', 'pytest', 'mock', 'patch', 'TestCase']
integration_test_keywords = ['main.py', 'fetch', 'API', 'call_']

unit_count = 0
integration_count = 0

for tf in test_files:
    with open(tf, 'r') as f:
        content = f.read().lower()
    
    if any(kw.lower() in content for kw in unit_test_keywords):
        unit_count += 1
    if any(kw.lower() in content for kw in integration_test_keywords):
        integration_count += 1

print(f"   Unit tests (approx): {unit_count}")
print(f"   Integration tests (approx): {integration_count}")

# Check core logic files for tests
core_files = ['src/analyzers.py', 'src/strategies.py', 'src/dcf_model.py']
for cf in core_files:
    test_name = f"test_{os.path.basename(cf).replace('.py', '')}.py"
    if not os.path.exists(test_name):
        print(f"   ⚠️  No dedicated test for {cf}")

if unit_count == 0:
    print("⚠️  PARTIAL: No unit tests detected")
else:
    print("✅ PASS: Some unit tests exist")

# =============================================================================
# Test 7: Magic Numbers (Issue #7)
# =============================================================================
print("\n[TEST 7] Magic Numbers in Source Code")
print("-" * 50)

# Check for hardcoded thresholds
magic_number_patterns = [
    (r'RSI.*[<>=]\s*\d+', 'RSI thresholds'),
    (r'if.*score.*[<>=]\s*\d+\.?\d*', 'Score thresholds'),
    (r'ATR.*\*\s*\d+\.?\d*', 'ATR multipliers'),
]

files_with_magic = []
for filepath in ['src/strategies.py', 'src/analyzers.py', 'src/dcf_model.py']:
    if not os.path.exists(filepath):
        continue
    with open(filepath, 'r') as f:
        content = f.read()
    
    for pattern, desc in magic_number_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            files_with_magic.append(f"{filepath}: {desc} ({len(matches)} occurrences)")

if files_with_magic:
    print("⚠️  PARTIAL: Magic numbers found:")
    for item in files_with_magic[:5]:  # Show first 5
        print(f"   - {item}")
else:
    print("✅ PASS: No obvious magic numbers (or they're in config)")

# =============================================================================
# Test 8: Type Hint Inconsistency (Issue #8)
# =============================================================================
print("\n[TEST 8] Type Hint Inconsistency")
print("-" * 50)

# Check for type hints in key files
files_to_check = ['src/data_fetcher.py', 'src/analyzers.py', 'main.py']

hinted_count = 0
unhinted_count = 0

for filepath in files_to_check:
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Count functions with type hints
    hinted = re.findall(r'def\s+\w+\([^)]*:\s*[^)]*\)\s*->', content)
    hinted_count += len(hinted)
    
    # Count functions without type hints
    all_funcs = re.findall(r'def\s+\w+\s*\(', content)
    unhinted_count += len(all_funcs) - len(hinted)

print(f"   Functions with type hints: {hinted_count}")
print(f"   Functions without type hints: {unhinted_count}")

if unhinted_count > hinted_count:
    print("⚠️  PARTIAL: More functions lack type hints")
else:
    print("✅ PASS: Type hint coverage is reasonable")

# =============================================================================
# Test 9: Input Validation (Issue #9)
# =============================================================================
print("\n[TEST 9] Input Validation on main.py")
print("-" * 50)

# Check if main.py validates ticker input
with open('main.py', 'r') as f:
    main_content = f.read()

# Check for validation patterns
validation_patterns = [
    (r're\.match|re\.search', 'Regex validation'),
    (r'ticker.*valid|valid.*ticker', 'Ticker validation'),
    (r'if.*ticker.*:', 'Ticker checks'),
]

has_validation = False
for pattern, desc in validation_patterns:
    if re.search(pattern, main_content, re.IGNORECASE):
        has_validation = True
        print(f"   ✅ Found: {desc}")
        break

# Check app.py for comparison
with open('app.py', 'r') as f:
    app_content = f.read()

app_has_validation = bool(re.search(r're\.match.*ticker', app_content))

if has_validation:
    print("✅ PASS: Input validation exists in main.py")
elif app_has_validation:
    print("⚠️  PARTIAL: Input validation only in app.py, not in main.py")
else:
    print("❌ FAIL: No input validation detected")

# =============================================================================
# Test 10: SEC User-Agent Default (Issue #10)
# =============================================================================
print("\n[TEST 10] SEC User-Agent Default Value")
print("-" * 50)

with open('src/sec_client.py', 'r') as f:
    sec_content = f.read()

# Check for default User-Agent
user_agent_match = re.search(r'SEC_USER_AGENT.*=.*["\']([^"\']+)["\']', sec_content)

if user_agent_match:
    default_ua = user_agent_match.group(1)
    print(f"   Default User-Agent: {default_ua}")
    
    if 'example.com' in default_ua or 'cio-prototype' in default_ua.lower():
        print("⚠️  PARTIAL: Default User-Agent uses placeholder email")
        print("   SEC requires valid contact email in User-Agent")
    else:
        print("✅ PASS: User-Agent appears to be properly configured")
else:
    print("❌ FAIL: Could not find User-Agent configuration")

# =============================================================================
# Summary
# =============================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
Legend:
  ✅ PASS   - Issue not present or properly handled
  ⚠️  PARTIAL - Issue exists but is minor or partially addressed
  ❌ FAIL   - Issue confirmed as a problem

Note: This automated test checks for the presence of issues.
Some issues (like code organization, documentation quality) require
human judgment for full assessment.
""")
