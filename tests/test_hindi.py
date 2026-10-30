"""Every fixed message the server sends has a Hindi translation in the site's language file."""
import json
import re
from pathlib import Path

import messages
from main import CHECK_EMAIL  # noqa: F401  (loads the app, so its settings model is real)
import main

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


ROOT = Path(__file__).parent.parent
HI = json.loads((ROOT / "web/src/hi.json").read_text(encoding="utf-8"))

for script in messages.SCRIPTS:
    for text in (script.title, script.verdict, script.explanation):
        ok(f"{script.id}: {text[:50]}", text in HI)

clear = messages.check_message("Hello, see you at lunch tomorrow.")
ok("clear verdict", clear["verdict"] in HI and clear["summary"] in HI)

# Single-line messages in errors the page shows.
sources = {"main.py": r'HTTPException\(\d+, "([^"]+)"\)', "scanner.py": r'ScanError\("([^"{]+)"\)'}
for name, pattern in sources.items():
    for text in re.findall(pattern, (ROOT / name).read_text(encoding="utf-8")):
        ok(f"{name}: {text[:60]}", text in HI)

# Fixed verdicts and labels written into reports.
for name, pattern in {"payments.py": r'"(?:danger|caution|clear)": "([^"]+)"', "impersonation.py": r'level, verdict = "\w+", "([^"{]+)"',
                      "scanner.py": r'Category\("\w+", "([^"]+)"\)'}.items():
    found = re.findall(pattern, (ROOT / name).read_text(encoding="utf-8"))
    ok(f"{name}: found the strings to check", len(found) >= 3)
    for text in found:
        ok(f"{name}: {text}", text in HI)

ok("language setting is allowed", main.Settings(language="hi").language == "hi")
try:
    main.Settings(language="xx")
    ok("unknown language refused", False)
except ValueError:
    ok("unknown language refused", True)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
