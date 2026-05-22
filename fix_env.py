import os

env_path = ".env"

if not os.path.exists(env_path):
    print("❌ Nie znaleziono pliku .env w bieżącym katalogu!")
    sys.exit(1)

with open(env_path, "r", encoding="utf-8") as f:
    content = f.read()

old_uri = "https://BLADERUNNER009.pythonanywhere.com/callback"
new_uri = "https://polskibot-bladerunner009.pythonanywhere.com/callback"

# Elastyczna zamiana niezależnie od wielkości liter czy drobnych różnic
updated = False
lines = content.splitlines()
new_lines = []

for line in lines:
    if line.strip().startswith("DISCORD_REDIRECT_URI"):
        print(f"Aktualna linia w .env: {line}")
        # Ustawiamy nową wartość
        line = f"DISCORD_REDIRECT_URI={new_uri}"
        updated = True
        print(f"Zmieniono na: {line}")
    new_lines.append(line)

if updated:
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    print("✅ Pomyślnie zaktualizowano plik .env na serwerze!")
    print("👉 Pamiętaj, aby teraz wejść w zakładkę 'Web' na PythonAnywhere i kliknąć zielony przycisk 'Reload'!")
else:
    print("❌ Nie znaleziono klucza DISCORD_REDIRECT_URI w pliku .env!")
