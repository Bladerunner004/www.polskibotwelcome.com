import re, os, sys

issues = []
ok = []

TEMPLATES_DIR = 'templates'

# ===== SPRAWDZANIE PLIKOW PYTHON =====
py_files = ['routes_config.py', 'routes_dashboard.py', 'routes_home.py', 'routes_home.py', 'bot.py', 'database.py', 'base.py', 'run.py']

for pf in py_files:
    if not os.path.exists(pf):
        issues.append(f'[BRAK PLIKU PY] {pf}')
        continue
    content = open(pf, 'r', encoding='utf-8', errors='ignore').read()
    
    # Duplikaty nazw funkcji
    funcs = re.findall(r'^def (\w+)', content, re.MULTILINE)
    dups = set(x for x in funcs if funcs.count(x) > 1)
    for d in dups:
        issues.append(f'[DUPLIKAT FUNKCJI] {pf}: "{d}" wystepuje {funcs.count(d)}x')
    
    # Stary link Discord
    if 'G5F3WBbZ' in content:
        issues.append(f'[STARY LINK] {pf}: stary link Discord!')

# ===== SPRAWDZANIE PLIKOW HTML =====
for root, dirs, files in os.walk(TEMPLATES_DIR):
    for f in files:
        if not f.endswith('.html'):
            continue
        path = os.path.join(root, f)
        rel = path
        try:
            content = open(path, 'r', encoding='utf-8', errors='ignore').read()
        except Exception as e:
            issues.append(f'[BLAD ODCZYTU] {rel}: {e}')
            continue

        # Stary link
        if 'G5F3WBbZ' in content:
            issues.append(f'[STARY LINK] {rel}: stary link Discord!')

        # guild.icon.url
        if 'guild.icon.url' in content:
            issues.append(f'[RYZYKO 500] {rel}: uzywa guild.icon.url')

        # Szukamy extends
        for m in re.finditer(r"extends\s+[\"']([\w/\.]+)[\"']", content):
            layout = m.group(1)
            layout_path = os.path.join(TEMPLATES_DIR, layout)
            if not os.path.exists(layout_path):
                issues.append(f'[BRAK LAYOUTU] {rel}: extends "{layout}" - NIE ISTNIEJE!')

        # Szukamy includes
        for m in re.finditer(r"include\s+[\"']([\w/\.]+)[\"']", content):
            inc = m.group(1)
            inc_path = os.path.join(TEMPLATES_DIR, inc)
            if not os.path.exists(inc_path):
                issues.append(f'[BRAK INCLUDE] {rel}: include "{inc}" - NIE ISTNIEJE!')

# ===== RAPORT =====
print("=" * 60)
print("RAPORT DIAGNOSTYCZNY - POLSKIBOT")
print("=" * 60)

if issues:
    print(f"\n[!] Znaleziono {len(issues)} problemow:\n")
    for i in issues:
        print(f"  {i}")
else:
    print("\n[OK] Brak wykrytych problemow! Projekt jest czysty.")

print("\n" + "=" * 60)
