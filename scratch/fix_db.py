import sqlite3
import os

DB_PATH = 'database.db'

def fix():
    if not os.path.exists(DB_PATH):
        print(f"Nie znaleziono bazy w {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Lista kolumn do dodania
    columns_to_add = [
        ('color', 'TEXT DEFAULT "#74b816"'),
        ('bg_url', 'TEXT DEFAULT ""'),
        ('title', 'TEXT DEFAULT ""'),
        ('has_frame', 'INTEGER DEFAULT 0')
    ]
    
    for col_name, col_def in columns_to_add:
        try:
            c.execute(f"ALTER TABLE welcome_configs ADD COLUMN {col_name} {col_def}")
            print(f"Dodano kolumne: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"Kolumna {col_name} juz istnieje.")
            else:
                print(f"Blad przy dodawaniu {col_name}: {e}")
                
    conn.commit()
    conn.close()
    print("Baza danych zostala zaktualizowana.")

if __name__ == "__main__":
    fix()
