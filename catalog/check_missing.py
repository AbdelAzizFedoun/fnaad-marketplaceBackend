import re

with open("urls.py", "r", encoding="utf-8") as f:
    url_content = f.read()
with open("views.py", "r", encoding="utf-8") as f:
    views_content = f.read()

imports = re.findall(r'from \.views import \(([^)]+)\)', url_content, re.DOTALL)
if imports:
    names = re.findall(r'(\w+)', imports[0])
    for name in names:
        if name not in views_content:
            print(f"MISSING in views.py: {name}")
    print(f"Total imported: {len(names)}")
else:
    print("No multi-line imports found")
