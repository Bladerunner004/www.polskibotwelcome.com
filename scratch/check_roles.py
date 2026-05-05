import sqlite3
import json

DB_NAME = "database.db"

def check_roles():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    print("--- AUTOROLE (Główne) ---")
    cursor.execute("SELECT guild_id, autorole_human_roles, autorole_bot_roles, autorole_mode FROM settings")
    for row in cursor.fetchall():
        print(f"Server {row[0]}: Humans={row[1]}, Bots={row[2]}, Mode={row[3]}")
        
    print("\n--- SELFROLE (Reakcyjne) ---")
    cursor.execute("SELECT name, roles_json FROM self_role_configs")
    for row in cursor.fetchall():
        print(f"Config '{row[0]}': {row[1]}")

    print("\n--- REACTION ROLES (Osadzenia) ---")
    cursor.execute("SELECT name, reaction_role_id FROM embed_configs")
    for row in cursor.fetchall():
        print(f"Embed '{row[0]}': RoleID={row[1]}")

    conn.close()

if __name__ == "__main__":
    check_roles()
