import os, sqlite3
from dotenv import load_dotenv
load_dotenv()

print("=== .ENV ===")
keys = ["DISCORD_BOT_TOKEN","DISCORD_CLIENT_ID","DISCORD_CLIENT_SECRET","DISCORD_REDIRECT_URI","FLASK_SECRET"]
for k in keys:
    v = os.getenv(k)
    if v:
        masked = v[:6] + "..." + v[-4:] if len(v) > 12 else "***"
        print(f"  OK   {k} = {masked}")
    else:
        print(f"  BRAK {k}")

print("\n=== BAZA DANYCH ===")
db = "database.db"
if os.path.exists(db):
    conn = sqlite3.connect(db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"  OK   {db} istnieje")
    for (t,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"       [{t}]: {count} wierszy")
    conn.close()
else:
    print(f"  BRAK {db}")

print("\n=== IMPORT MODUŁÓW ===")
mods = ["run","bot","database","routes_config","routes_home","routes_dashboard","base"]
for m in mods:
    try:
        __import__(m)
        print(f"  OK   {m}")
    except Exception as e:
        print(f"  ERR  {m}: {e}")

print("\n=== SZABLONY ===")
import pathlib
tpl = pathlib.Path("templates")
required = [
    "config.html","home.html","dashboard.html",
    "glowne/strona_glowna.html","glowne/komendy.html","glowne/ustawienia.html",
    "zarzadzanie_serwerem/powitania.html",
]
for r in required:
    p = tpl / r
    status = "OK  " if p.exists() else "BRAK"
    print(f"  {status} {r}")
