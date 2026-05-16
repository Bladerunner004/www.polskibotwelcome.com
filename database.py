import os
import sqlite3
import json
from base import LIMITS_FREE, LIMITS_PREMIUM
from badwords_list import GLOBAL_BADWORDS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "database.db")



# Lista wszystkich komend w bocie â€“ to jest "ĹşrĂłdĹ‚o prawdy"
ALL_COMMANDS = [
    "ticket", "claim", "close", "unclaim",
    "level", "toplevel", "exp",
    "ban", "unban", "kick", "mute", "unmute",
    "slowmode", "warn", "warns", "modinfo", "clear",
    "temprole", "votemute", "massrole",
    "iq", "cat", "meme", "slap", "info", "pomoc"
]

def init_db():
    """Tworzy bazÄ™ danych i tabele, jeĹ›li nie istniejÄ…."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Tabela ustawieĹ„ gĹ‚Ăłwnych
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
                        guild_id TEXT PRIMARY KEY,
                        ticket_enabled INTEGER DEFAULT 1,
                        moderation_enabled INTEGER DEFAULT 1,
                        levels_enabled INTEGER DEFAULT 1,
                        prefix TEXT DEFAULT '!',
                        autorole_mode TEXT DEFAULT 'disabled',
                        autorole_roles TEXT DEFAULT '[]',
                        autorole_human_roles TEXT DEFAULT '[]',
                        autorole_bot_roles TEXT DEFAULT '[]',
                        autorole_booster_roles TEXT DEFAULT '[]',
                        autorole_booster_remove INTEGER DEFAULT 1,
                        counter_humans_enabled INTEGER DEFAULT 0,
                        counter_humans_channel_id TEXT,
                        counter_humans_name TEXT DEFAULT 'Humans: {count}',
                        counter_humans_thousands INTEGER DEFAULT 0,
                        counter_bots_enabled INTEGER DEFAULT 0,
                        counter_bots_channel_id TEXT,
                        counter_bots_name TEXT DEFAULT 'Bots: {count}',
                        counter_bots_thousands INTEGER DEFAULT 0,
                        counter_bans_enabled INTEGER DEFAULT 0,
                        counter_bans_channel_id TEXT,
                        counter_bans_name TEXT DEFAULT 'Bans: {count}',
                        counter_bans_thousands INTEGER DEFAULT 0,
                        premium INTEGER DEFAULT 0,
                        premium_expiry TEXT,
                        subscription_type TEXT DEFAULT 'jednorazowa',
                        trial_used INTEGER DEFAULT 0,
                        trial_start TEXT,
                        language TEXT DEFAULT 'pl'
                    )''')
    
    # Automatyczne dodawanie brakujÄ…cych kolumn (dla starych baz)
    needed_columns = [
        ("ticket_enabled", "INTEGER DEFAULT 1"),
        ("moderation_enabled", "INTEGER DEFAULT 1"),
        ("moderation_confirm", "INTEGER DEFAULT 0"),
        ("automod_antilink", "INTEGER DEFAULT 0"),
        ("automod_anticaps", "INTEGER DEFAULT 0"),
        ("automod_antispam", "INTEGER DEFAULT 0"),
        ("automod_badwords", "INTEGER DEFAULT 0"),
        ("automod_badwords_list", "TEXT DEFAULT '[]'"),
        ("automod_antiphishing", "INTEGER DEFAULT 0"),
        ("levels_enabled", "INTEGER DEFAULT 1"),
        ("prefix", "TEXT DEFAULT '!'"),
        ("autorole_mode", "TEXT DEFAULT 'disabled'"),
        ("autorole_roles", "TEXT DEFAULT '[]'"),
        ("autorole_human_roles", "TEXT DEFAULT '[]'"),
        ("autorole_bot_roles", "TEXT DEFAULT '[]'"),
        ("autorole_booster_roles", "TEXT DEFAULT '[]'"),
        ("autorole_booster_remove", "INTEGER DEFAULT 1"),
        ("counter_humans_enabled", "INTEGER DEFAULT 0"),
        ("counter_humans_channel_id", "TEXT"),
        ("counter_humans_name", "TEXT DEFAULT 'Humans: {count}'"),
        ("counter_humans_thousands", "INTEGER DEFAULT 0"),
        ("counter_bots_enabled", "INTEGER DEFAULT 0"),
        ("counter_bots_channel_id", "TEXT"),
        ("counter_bots_name", "TEXT DEFAULT 'Bots: {count}'"),
        ("counter_bots_thousands", "INTEGER DEFAULT 0"),
        ("counter_bans_enabled", "INTEGER DEFAULT 0"),
        ("counter_bans_channel_id", "TEXT"),
        ("counter_bans_name", "TEXT DEFAULT 'Bans: {count}'"),
        ("counter_bans_thousands", "INTEGER DEFAULT 0"),
        ("premium", "INTEGER DEFAULT 0"),
        ("premium_expiry", "TEXT"),
        ("subscription_type", "TEXT DEFAULT 'jednorazowa'"),
        ("trial_used", "INTEGER DEFAULT 0"),
        ("trial_start", "TEXT"),
        ("language", "TEXT DEFAULT 'pl'"),
        ("embed_color", "TEXT DEFAULT '#74b816'"),
        ("rgb_mode", "INTEGER DEFAULT 0"),
        ("logs_channel_id", "TEXT"),
        ("logs_join_leave", "INTEGER DEFAULT 0"),
        ("logs_mod_actions", "INTEGER DEFAULT 0"),
        ("logs_role_updates", "INTEGER DEFAULT 0"),
        ("logs_voice_activity", "INTEGER DEFAULT 0"),
        ("logs_guild_updates", "INTEGER DEFAULT 0"),
        ("logs_msg_updates", "INTEGER DEFAULT 0"),
        ("level_up_channel_id", "TEXT"),
        ("level_up_msg_enabled", "INTEGER DEFAULT 1"),
        ("counter_toplevel_enabled", "INTEGER DEFAULT 0"),
        ("counter_toplevel_channel_id", "TEXT"),
        ("counter_toplevel_name", "TEXT DEFAULT 'Top Level: {count}'")
    ]
    for col_name, col_type in needed_columns:
        try:
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}")
        except: pass

    # Tabela dynamicznych licznikĂłw rĂłl
    cursor.execute('''CREATE TABLE IF NOT EXISTS role_counters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        mode TEXT DEFAULT 'black',
                        roles TEXT DEFAULT '[]',
                        channel_id TEXT,
                        enabled INTEGER DEFAULT 1
                    )''')
    
    try:
        cursor.execute("ALTER TABLE role_counters ADD COLUMN enabled INTEGER DEFAULT 1")
    except: pass

    cursor.execute('''CREATE TABLE IF NOT EXISTS member_roles (
                        guild_id TEXT,
                        user_id TEXT,
                        roles TEXT,
                        PRIMARY KEY(guild_id, user_id)
                    )''')
    # NOWA tabela: stan kaĹĽdej komendy per serwer
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS command_settings (
            guild_id INTEGER,
            command_name TEXT,
            enabled INTEGER DEFAULT 1,
            PRIMARY KEY (guild_id, command_name)
        )
    ''')
    # Tabela konfiguracji powitaĹ„ i poĹĽegnaĹ„
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS welcome_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            config_type TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            is_embed INTEGER DEFAULT 1,
            author TEXT DEFAULT '',
            description TEXT DEFAULT '',
            footer TEXT DEFAULT '',
            plain_text TEXT DEFAULT '',
            has_image INTEGER DEFAULT 0,
            line1 TEXT DEFAULT 'WELCOME',
            line2 TEXT DEFAULT '{nick}',
            has_frame INTEGER DEFAULT 0,
            title TEXT DEFAULT '',
            bg_url TEXT DEFAULT '',
            color TEXT DEFAULT '#74b816'
        )''')
    
    # Tabela konfiguracji osadzeĹ„ (Embeds)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS embed_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            name TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            author TEXT DEFAULT '',
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            footer TEXT DEFAULT '',
            color TEXT DEFAULT '#74b816',
            image_url TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            title_url TEXT DEFAULT '',
            author_url TEXT DEFAULT '',
            link_color TEXT DEFAULT '#00a8fc',
            timestamp INTEGER DEFAULT 0,
            outer_text TEXT DEFAULT ''
        )''')
    
    # Migracja dla embed_configs
    embed_columns = [
        ("title_url", "TEXT DEFAULT ''"),
        ("author_url", "TEXT DEFAULT ''"),
        ("link_color", "TEXT DEFAULT '#00a8fc'"),
        ("category", "TEXT DEFAULT 'general'"),
        ("reaction_emoji", "TEXT DEFAULT ''"),
        ("reaction_role_id", "TEXT DEFAULT ''"),
        ("last_message_id", "TEXT DEFAULT ''"),
        ("enabled", "INTEGER DEFAULT 1"),
        ("outer_text", "TEXT DEFAULT ''"),
        ("has_frame", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in embed_columns:
        try:
            cursor.execute(f"ALTER TABLE embed_configs ADD COLUMN {col_name} {col_type}")
        except: pass

    # Migracja dla welcome_configs
    welcome_columns = [
        ('color', 'TEXT DEFAULT "#74b816"'),
        ('bg_url', 'TEXT DEFAULT ""'),
        ('title', 'TEXT DEFAULT ""'),
        ('has_frame', 'INTEGER DEFAULT 0'),
        ('font_name', 'TEXT DEFAULT "Inter-Bold.ttf"'),
        ('img_text_color', 'TEXT DEFAULT "#ffffff"'),
        ('is_enabled', 'INTEGER DEFAULT 1')
    ]
    for col_name, col_type in welcome_columns:
        try:
            cursor.execute(f"ALTER TABLE welcome_configs ADD COLUMN {col_name} {col_type}")
        except: pass

    # Tabela Selfrole
    cursor.execute('''CREATE TABLE IF NOT EXISTS self_role_configs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        type TEXT NOT NULL,
                        name TEXT DEFAULT '',
                        channel_id TEXT DEFAULT '',
                        message_id TEXT DEFAULT '',
                        role_id TEXT DEFAULT '',
                        roles_json TEXT DEFAULT '[]',
                        enabled INTEGER DEFAULT 1
                    )''')
    
    # Migracja dla self_role_configs
    selfrole_cols = [
        ("enabled", "INTEGER DEFAULT 1"),
        ("image_url", "TEXT DEFAULT ''"),
        ("thumbnail_url", "TEXT DEFAULT ''"),
        ("description", "TEXT DEFAULT ''")
    ]
    for col_name, col_type in selfrole_cols:
        try:
            cursor.execute(f"ALTER TABLE self_role_configs ADD COLUMN {col_name} {col_type}")
        except: pass

    # Tabela konfiguracji mediĂłw (Social Media)
    cursor.execute('''CREATE TABLE IF NOT EXISTS media_configs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        account_id TEXT,
                        discord_channel_id TEXT,
                        message TEXT,
                        enabled INTEGER DEFAULT 1
                    )''')



    # Tabela statystyk aktywnoĹ›ci
    cursor.execute('''CREATE TABLE IF NOT EXISTS activity_stats (
                        guild_id TEXT,
                        date TEXT,
                        messages_count INTEGER DEFAULT 0,
                        joins_count INTEGER DEFAULT 0,
                        PRIMARY KEY(guild_id, date)
                    )''')

    # Tabela kanałów (stats)
    cursor.execute('''CREATE TABLE IF NOT EXISTS channel_stats (
                        guild_id TEXT,
                        channel_id TEXT,
                        date TEXT,
                        messages_count INTEGER DEFAULT 0,
                        PRIMARY KEY(guild_id, channel_id, date)
                    )''')
    
    # NOWA TABELA: LOGI AUDYTU (Dla zakładki Zmiany na serwerze)
    cursor.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT,
                        category TEXT,
                        user_name TEXT,
                        user_id TEXT,
                        action TEXT,
                        details TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')


    # Tabela WĹ‚asny Bot (White Label)
    cursor.execute('''CREATE TABLE IF NOT EXISTS custom_bots (
                        guild_id TEXT PRIMARY KEY,
                        token TEXT,
                        bot_name TEXT,
                        status TEXT DEFAULT 'offline',
                        enabled INTEGER DEFAULT 0
                    )''')

    # Tabela OstrzeĹĽeĹ„ (Warnings)
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_warnings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        moderator_id TEXT,
                        reason TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')

    # Tabela PoziomĂłw (Levels)
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_levels (
                        guild_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        xp INTEGER DEFAULT 0,
                        level INTEGER DEFAULT 1,
                        last_msg_at REAL DEFAULT 0,
                        PRIMARY KEY(guild_id, user_id)
                    )''')

    conn.commit()
    conn.close()
    print("[DB] Baza danych zostaĹ‚a zsynchronizowana.")

def log_message_activity(guild_id, channel_id):
    """Loguje aktywnoĹ›Ä‡ wiadomoĹ›ci."""
    import datetime
    date_str = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''INSERT INTO activity_stats (guild_id, date, messages_count) 
                     VALUES (?, ?, 1) 
                     ON CONFLICT(guild_id, date) DO UPDATE SET messages_count = messages_count + 1''', (str(guild_id), date_str))
        c.execute('''INSERT INTO channel_stats (guild_id, channel_id, date, messages_count) 
                     VALUES (?, ?, ?, 1) 
                     ON CONFLICT(guild_id, channel_id, date) DO UPDATE SET messages_count = messages_count + 1''', (str(guild_id), str(channel_id), date_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d log_message: {e}")

def log_join_activity(guild_id):
    """Loguje doĹ‚Ä…czenie uĹĽytkownika."""
    import datetime
    date_str = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''INSERT INTO activity_stats (guild_id, date, joins_count) 
                     VALUES (?, ?, 1) 
                     ON CONFLICT(guild_id, date) DO UPDATE SET joins_count = joins_count + 1''', (str(guild_id), date_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d log_join: {e}")

def get_activity_stats(guild_id, days=7):
    """Pobiera dane aktywnoĹ›ci z ostatnich dni."""
    import datetime
    date_limit = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT date, messages_count, joins_count FROM activity_stats WHERE guild_id=? AND date >= ? ORDER BY date ASC', (str(guild_id), date_limit))
        rows = c.fetchall()
        c.execute('SELECT channel_id, SUM(messages_count) as total FROM channel_stats WHERE guild_id=? AND date >= ? GROUP BY channel_id ORDER BY total DESC LIMIT 5', (str(guild_id), date_limit))
        top_channels = c.fetchall()
        conn.close()
        return {
            'history': [ {'date': r[0], 'messages': r[1], 'joins': r[2]} for r in rows ],
            'top_channels': [ {'id': r[0], 'count': r[1]} for r in top_channels ]
        }
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d get_activity: {e}")
        return {'history': [], 'top_channels': []}

def get_custom_bot(guild_id):
    """Pobiera konfiguracjÄ™ wĹ‚asnego bota."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT token, bot_name, status, enabled FROM custom_bots WHERE guild_id=?', (str(guild_id),))
        row = c.fetchone()
        conn.close()
        if row:
            return {'token': row[0], 'bot_name': row[1], 'status': row[2], 'enabled': bool(row[3])}
        return None
    except: return None

# --- MODERACJA: OSTRZEĹ»ENIA ---

def add_warning(guild_id, user_id, moderator_id, reason):
    """Dodaje ostrzeĹĽenie uĹĽytkownikowi."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('INSERT INTO user_warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)',
                  (str(guild_id), str(user_id), str(moderator_id), reason))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d add_warning: {e}")
        return False

def get_warnings(guild_id, user_id):
    """Pobiera listÄ™ ostrzeĹĽeĹ„ uĹĽytkownika."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT id, moderator_id, reason, timestamp FROM user_warnings WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC',
                  (str(guild_id), str(user_id)))
        rows = c.fetchall()
        conn.close()
        return [ {'id': r[0], 'moderator_id': r[1], 'reason': r[2], 'timestamp': r[3]} for r in rows ]
    except: return []

def clear_warnings(guild_id, user_id):
    """Usuwa wszystkie ostrzeĹĽenia uĹĽytkownika."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM user_warnings WHERE guild_id=? AND user_id=?', (str(guild_id), str(user_id)))
        conn.commit()
        conn.close()
        return True
    except: return False

# --- SYSTEM POZIOMĂ“W ---

def get_user_level(guild_id, user_id):
    """Pobiera dane o poziomie uĹĽytkownika."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT xp, level, last_msg_at FROM user_levels WHERE guild_id=? AND user_id=?',
                  (str(guild_id), str(user_id)))
        row = c.fetchone()
        conn.close()
        if row:
            return {'xp': row[0], 'level': row[1], 'last_msg_at': row[2]}
        return {'xp': 0, 'level': 1, 'last_msg_at': 0}
    except: return {'xp': 0, 'level': 1, 'last_msg_at': 0}

def add_xp(guild_id, user_id, amount):
    """Dodaje XP uĹĽytkownikowi i sprawdza awans."""
    import time
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        
        # Pobierz obecny stan
        c.execute('SELECT xp, level FROM user_levels WHERE guild_id=? AND user_id=?', (str(guild_id), str(user_id)))
        row = c.fetchone()
        
        if not row:
            new_xp = amount
            new_level = 1
            c.execute('INSERT INTO user_levels (guild_id, user_id, xp, level, last_msg_at) VALUES (?, ?, ?, ?, ?)',
                      (str(guild_id), str(user_id), new_xp, new_level, time.time()))
        else:
            curr_xp, curr_level = row
            new_xp = curr_xp + amount
            # Prosty wzĂłr na poziom: level = floor(sqrt(xp/100)) + 1
            import math
            new_level = math.floor(math.sqrt(new_xp / 100)) + 1
            
            c.execute('UPDATE user_levels SET xp=?, level=?, last_msg_at=? WHERE guild_id=? AND user_id=?',
                      (new_xp, new_level, time.time(), str(guild_id), str(user_id)))
            
        conn.commit()
        conn.close()
        
        if row and new_level > row[1]:
            return True, new_level # Awans!
        return False, new_level
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d add_xp: {e}")
        return False, 1

def get_top_levels(guild_id, limit=10):
    """Pobiera ranking poziomĂłw."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT user_id, xp, level FROM user_levels WHERE guild_id=? ORDER BY xp DESC LIMIT ?',
                  (str(guild_id), limit))
        rows = c.fetchall()
        conn.close()
        return [ {'user_id': r[0], 'xp': r[1], 'level': r[2]} for r in rows ]
    except: return []

def save_custom_bot(guild_id, token, bot_name, enabled):
    """Zapisuje konfiguracjÄ™ wĹ‚asnego bota."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''INSERT INTO custom_bots (guild_id, token, bot_name, enabled) 
                     VALUES (?, ?, ?, ?) 
                     ON CONFLICT(guild_id) DO UPDATE SET token=?, bot_name=?, enabled=?''', 
                     (str(guild_id), token, bot_name, 1 if enabled else 0, token, bot_name, 1 if enabled else 0))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ [DB] BĹ‚Ä…d save_custom_bot: {e}")
        return False

def save_autorole_settings(guild_id, mode, restore_roles, human_roles, bot_roles, booster_roles, booster_remove):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Upewnij się, że wiersz istnieje
    cursor.execute("INSERT OR IGNORE INTO settings (guild_id) VALUES (?)", (str(guild_id),))
    cursor.execute("UPDATE settings SET autorole_mode = ?, autorole_roles = ?, autorole_human_roles = ?, autorole_bot_roles = ?, autorole_booster_roles = ?, autorole_booster_remove = ? WHERE guild_id = ?", 
                  (mode, json.dumps(restore_roles), json.dumps(human_roles), json.dumps(bot_roles), json.dumps(booster_roles), 1 if booster_remove else 0, str(guild_id)))
    conn.commit()
    conn.close()

def save_counter_settings(guild_id, type, enabled, name, thousands):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    col_en = f"counter_{type}_enabled"
    col_name = f"counter_{type}_name"
    col_th = f"counter_{type}_thousands"
    cursor.execute(f"UPDATE settings SET {col_en} = ?, {col_name} = ?, {col_th} = ? WHERE guild_id = ?", 
                  (1 if enabled else 0, name, 1 if thousands else 0, str(guild_id)))
    conn.commit()
    conn.close()

def update_counter_channel_id(guild_id, type, channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    col_id = f"counter_{type}_channel_id"
    val = str(channel_id) if channel_id is not None else None
    cursor.execute(f"UPDATE settings SET {col_id} = ? WHERE guild_id = ?", (val, str(guild_id)))
    conn.commit()
    conn.close()

# DYNAMICZNE LICZNIKI RĂ“L
def get_role_counters(guild_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, mode, roles, channel_id, enabled FROM role_counters WHERE guild_id = ?", (str(guild_id),))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "mode": r[2], "roles": json.loads(r[3] or '[]'), "channel_id": r[4], "enabled": r[5]} for r in rows]

def save_role_counter(guild_id, counter_id, name, mode, roles, enabled=1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    roles_json = json.dumps(roles)
    if counter_id:
        cursor.execute("UPDATE role_counters SET name = ?, mode = ?, roles = ?, enabled = ? WHERE id = ? AND guild_id = ?", (name, mode, roles_json, enabled, counter_id, str(guild_id)))
    else:
        # Sprawdzamy limit
        premium = is_premium(guild_id)
        limit = LIMITS_PREMIUM["role_counters"] if premium else LIMITS_FREE["role_counters"]
        
        cursor.execute("SELECT COUNT(*) FROM role_counters WHERE guild_id = ?", (str(guild_id),))
        if cursor.fetchone()[0] < limit:
            cursor.execute("INSERT INTO role_counters (guild_id, name, mode, roles, enabled) VALUES (?, ?, ?, ?, ?)", (str(guild_id), name, mode, roles_json, enabled))
        else:
            conn.close()
            return False, f"Osiągnięto limit liczników ({limit}). Kup Premium, aby dodać więcej!"
    conn.commit()
    conn.close()
    return True, None

def delete_role_counter(guild_id, counter_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM role_counters WHERE id = ? AND guild_id = ?", (counter_id, str(guild_id)))
    conn.commit()
    conn.close()

def sync_role_counters(guild_id, configs):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Usuwamy stare, bo to synchronizacja stanu z dashboardu
        cursor.execute("DELETE FROM role_counters WHERE guild_id = ?", (str(guild_id),))
        
        for cfg in configs:
            roles_json = json.dumps(cfg.get('roles', []))
            cursor.execute("INSERT INTO role_counters (guild_id, name, mode, roles, enabled) VALUES (?, ?, ?, ?, ?)",
                         (str(guild_id), cfg.get('name'), cfg.get('mode', 'white'), roles_json, 1 if cfg.get('enabled', True) else 0))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d sync_role_counters: {e}")
        return False

def update_role_counter_channel_id(counter_id, channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    val = str(channel_id) if channel_id is not None else None
    cursor.execute("UPDATE role_counters SET channel_id = ? WHERE id = ?", (val, counter_id))
    conn.commit()
    conn.close()

def save_member_roles(guild_id, user_id, roles_list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO member_roles (guild_id, user_id, roles) VALUES (?, ?, ?)",
                  (str(guild_id), str(user_id), json.dumps(roles_list)))
    conn.commit()
    conn.close()

def get_member_roles(guild_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT roles FROM member_roles WHERE guild_id = ? AND user_id = ?", (str(guild_id), str(user_id)))
    result = cursor.fetchone()
    conn.close()
    if result:
        return json.loads(result[0])
    return []

def get_settings(guild_id):
    """Pobiera wszystkie ustawienia modułów dla konkretnego serwera."""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE guild_id = ?", (str(guild_id),))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            res = dict(row)
            # Konwersja pól JSON i bool
            for key in ['autorole_roles', 'autorole_human_roles', 'autorole_bot_roles', 'autorole_booster_roles', 'automod_badwords_list']:
                if res.get(key):
                    try: res[key] = json.loads(res[key])
                    except: res[key] = []
                else: res[key] = []
            
            bool_fields = ['ticket_enabled', 'moderation_enabled', 'moderation_confirm', 
                           'automod_antilink', 'automod_anticaps', 'automod_antispam', 'automod_badwords', 'automod_antiphishing',
                           'levels_enabled', 'premium', 'trial_used',
                           'counter_humans_enabled', 'counter_bots_enabled', 'counter_bans_enabled',
                           'counter_humans_thousands', 'counter_bots_thousands', 'counter_bans_thousands',
                           'autorole_booster_remove', 'logs_join_leave', 'logs_mod_actions',
                           'logs_role_updates', 'logs_voice_activity', 'logs_guild_updates', 'logs_msg_updates', 'rgb_mode']
            for field in bool_fields:
                if field in res:
                    res[field] = (res[field] == 1)
            
            # Automatycznie sprawdzanie wygaśnięcia triala
            if res.get('premium') and res.get('trial_start') and res.get('subscription_type') == 'Okres Próbny':
                from datetime import datetime
                try:
                    start_dt = datetime.fromisoformat(res['trial_start'])
                    from datetime import timedelta
                    if datetime.now() > start_dt + timedelta(days=7):
                        # Trial wygasł - aktualizujemy w bazie
                        conn_upd = sqlite3.connect(DB_NAME)
                        curr_upd = conn_upd.cursor()
                        curr_upd.execute("UPDATE settings SET premium = 0, subscription_type = 'Wygasły Trial' WHERE guild_id = ?", (str(guild_id),))
                        conn_upd.commit()
                        conn_upd.close()
                        res['premium'] = False
                        res['subscription_type'] = 'Wygasły Trial'
                        print(f"[PREMIUM] Trial wygasł dla {guild_id}")
                except Exception as e:
                    print(f"[PREMIUM] Błąd sprawdzania triala: {e}")

            return res

        return {
            "ticket_enabled": True, "moderation_enabled": True, "moderation_confirm": False,
            "automod_antilink": False, "automod_anticaps": False, "automod_antispam": False,
            "automod_badwords": False, "automod_badwords_list": [], "automod_antiphishing": False,
            "levels_enabled": True, "prefix": "!", "embed_color": "#74b816", "rgb_mode": False,
            "autorole_mode": 'disabled', "autorole_roles": [], "autorole_human_roles": [], 
            "autorole_bot_roles": [], "autorole_booster_roles": [], "autorole_booster_remove": True,
            "counter_humans_enabled": False, "counter_humans_name": "Humans: {count}", 
            "premium": False, "premium_expiry": None, "subscription_type": "jednorazowa", 
            "trial_used": False, "trial_start": None, "language": "pl"
        }
    except Exception as e:
        print(f"❌ Błąd odczytu bazy: {e}")
        return {
            "ticket_enabled": True, "moderation_enabled": True, "moderation_confirm": False,
            "automod_antilink": False, "automod_anticaps": False, "automod_antispam": False,
            "automod_badwords": False, "automod_badwords_list": [], "automod_antiphishing": False,
            "levels_enabled": True, "prefix": "!", "embed_color": "#74b816", "rgb_mode": False,
            "autorole_mode": 'disabled', "autorole_roles": [], "autorole_human_roles": [], 
            "autorole_bot_roles": [], "autorole_booster_roles": [], "autorole_booster_remove": True,
            "counter_humans_enabled": False, "counter_humans_name": "Humans: {count}", 
            "premium": False, "premium_expiry": None, "subscription_type": "jednorazowa", "language": "pl"
        }

def get_setting(guild_id, module_column):
    """Pomocnicza funkcja dla bota (zostawiamy jÄ…, bo bot.py jej uĹĽywa)"""
    res = get_settings(guild_id)
    return res.get(module_column, True)

def save_settings(guild_id, ticket, moderation, levels, prefix="!", language="pl", embed_color="#74b816", rgb_mode=0, moderation_confirm=0, automod_antilink=0, automod_anticaps=0, automod_antispam=0, automod_badwords=0, automod_badwords_list="[]", automod_antiphishing=0):
    """Zapisuje ustawienia przysĹ‚ane ze strony WWW."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''
            INSERT INTO settings (guild_id, ticket_enabled, moderation_enabled, levels_enabled, prefix, language, embed_color, rgb_mode, moderation_confirm, automod_antilink, automod_anticaps, automod_antispam, automod_badwords, automod_badwords_list, automod_antiphishing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                ticket_enabled=excluded.ticket_enabled,
                moderation_enabled=excluded.moderation_enabled,
                levels_enabled=excluded.levels_enabled,
                prefix=excluded.prefix,
                language=excluded.language,
                embed_color=excluded.embed_color,
                rgb_mode=excluded.rgb_mode,
                moderation_confirm=excluded.moderation_confirm,
                automod_antilink=excluded.automod_antilink,
                automod_anticaps=excluded.automod_anticaps,
                automod_antispam=excluded.automod_antispam,
                automod_badwords=excluded.automod_badwords,
                automod_badwords_list=excluded.automod_badwords_list,
                automod_antiphishing=excluded.automod_antiphishing
        ''', (guild_id, 1 if ticket else 0, 1 if moderation else 0, 1 if levels else 0, prefix, language, embed_color, 1 if rgb_mode else 0, 1 if moderation_confirm else 0, 1 if automod_antilink else 0, 1 if automod_anticaps else 0, 1 if automod_antispam else 0, 1 if automod_badwords else 0, automod_badwords_list, 1 if automod_antiphishing else 0))
        conn.commit()
        conn.close()
        print(f"[OK] Zapisano ustawienia dla {guild_id}")
    except Exception as e:
        print(f"[ERROR] BĹ‚Ä…d zapisu bazy: {e}")

def add_audit_log(guild_id, category, user_name, user_id, action, details):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO audit_logs (guild_id, category, user_name, user_id, action, details) VALUES (?, ?, ?, ?, ?, ?)",
                     (str(guild_id), category, user_name, str(user_id), action, details))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ [DB] Błąd zapisu audit_log: {e}")

def get_audit_logs(guild_id, limit=100):
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?", (str(guild_id), limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except:
        return []

def get_prefix(guild_id):
    settings = get_settings(guild_id)
    return settings.get("prefix", "!")

def reset_to_global_badwords(guild_id):
    """Przywraca globalnÄ… listÄ™ wulgaryzmĂłw dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute("UPDATE settings SET automod_badwords_list = ? WHERE guild_id = ?", (json.dumps(GLOBAL_BADWORDS), str(guild_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] BĹ‚Ä…d reset_to_global_badwords: {e}")
        return False

# =============================================
# NOWE FUNKCJE â€“ zarzÄ…dzanie komendami per guild
# =============================================

def get_command_settings(guild_id):
    """
    Zwraca sĹ‚ownik {nazwa_komendy: True/False} dla danego serwera.
    Komendy, ktĂłrych nie ma w bazie, domyĹ›lnie sÄ… WĹÄ„CZONE (True).
    """
    result = {cmd: True for cmd in ALL_COMMANDS}  # domyĹ›lnie wszystko ON
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute("SELECT command_name, enabled FROM command_settings WHERE guild_id = ?", (guild_id,))
        rows = c.fetchall()
        conn.close()
        for cmd_name, enabled in rows:
            if cmd_name in result:
                result[cmd_name] = (enabled == 1)
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d odczytu komend z bazy: {e}")
    return result

def is_command_enabled(guild_id, command_name):
    """Sprawdza, czy konkretna komenda jest wĹ‚Ä…czona na danym serwerze."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute("SELECT enabled FROM command_settings WHERE guild_id = ? AND command_name = ?", (guild_id, command_name))
        row = c.fetchone()
        conn.close()
        if row is None:
            return True  # DomyĹ›lnie wĹ‚Ä…czona, jeĹ›li nie ma wpisu
        return row[0] == 1
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d sprawdzania komendy: {e}")
        return True  # W razie bĹ‚Ä™du â€“ lepiej wĹ‚Ä…czona niĹĽ zepsuta

def save_command_settings(guild_id, enabled_commands):
    """
    Zapisuje stan komend dla serwera.
    enabled_commands: lista nazw komend, ktĂłre majÄ… byÄ‡ WĹÄ„CZONE.
    Wszystkie inne komendy z ALL_COMMANDS zostanÄ… WYĹÄ„CZONE.
    """
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        for cmd in ALL_COMMANDS:
            enabled = 1 if cmd in enabled_commands else 0
            c.execute('''
                INSERT INTO command_settings (guild_id, command_name, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, command_name) DO UPDATE SET
                    enabled=excluded.enabled
            ''', (guild_id, cmd, enabled))
        conn.commit()
        conn.close()
        print(f"[OK] Zapisano komendy dla {guild_id}: {enabled_commands}")
    except Exception as e:
        print(f"[ERROR] BĹ‚Ä…d zapisu komend: {e}")

# =============================================
# FUNKCJE â€“ konfiguracje powitaĹ„ / poĹĽegnaĹ„
# =============================================

def get_welcome_configs(guild_id, config_type):
    """Pobiera listÄ™ konfiguracji powitaĹ„ lub poĹĽegnaĹ„ dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute(
            'SELECT id, channel_id, channel_name, is_embed, author, description, footer, plain_text, has_image, line1, line2, has_frame, title, bg_url, color, font_name, img_text_color, is_enabled FROM welcome_configs WHERE guild_id=? AND config_type=?',
            (str(guild_id), config_type)
        )
        rows = c.fetchall()
        conn.close()
        keys = ['id', 'channel_id', 'channel_name', 'is_embed', 'author', 'description', 'footer', 'plain_text', 'has_image', 'line1', 'line2', 'has_frame', 'title', 'bg_url', 'color', 'font_name', 'img_text_color', 'is_enabled']
        return [dict(zip(keys, row)) for row in rows]
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d odczytu welcome_configs: {e}")
        return []

def save_welcome_config(guild_id, config_type, data, config_id=None):
    """Tworzy lub aktualizuje konfiguracjÄ™ powitania/poĹĽegnania."""
    try:
        print(f"[DB] Zapisywanie welcome_config: ID={config_id}, Guild={guild_id}, Type={config_type}, Color={data.get('color')}")
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        if config_id:
            c.execute('''
                UPDATE welcome_configs SET
                    channel_id=?, channel_name=?, is_embed=?, author=?, description=?, footer=?,
                    plain_text=?, has_image=?, line1=?, line2=?, has_frame=?, title=?, bg_url=?, color=?,
                    font_name=?, img_text_color=?, is_enabled=?
                WHERE id=? AND guild_id=?
            ''', (
                str(data.get('channel_id', '')), data.get('channel_name', ''),
                1 if data.get('is_embed') else 0,
                data.get('author', ''), data.get('description', ''), data.get('footer', ''),
                data.get('plain_text', ''), 1 if data.get('has_image') else 0,
                data.get('line1', 'WITAJ'), data.get('line2', '{nick}'),
                1 if data.get('has_frame') else 0,
                data.get('title', ''), data.get('bg_url', ''), data.get('color', '#74b816'),
                data.get('font_name', 'Inter-Bold.ttf'), data.get('img_text_color', '#ffffff'),
                1 if data.get('is_enabled') else 0,
                int(config_id), str(guild_id)
            ))
        else:
            # Sprawdzamy limit
            premium = is_premium(guild_id)
            limit = LIMITS_PREMIUM["welcome_configs"] if premium else LIMITS_FREE["welcome_configs"]
            
            c.execute('SELECT COUNT(*) FROM welcome_configs WHERE guild_id=? AND config_type=?', (str(guild_id), config_type))
            if c.fetchone()[0] >= limit:
                conn.close()
                return None 
            
            c.execute('''
                INSERT INTO welcome_configs
                    (guild_id, config_type, channel_id, channel_name, is_embed, author, description, footer, plain_text, has_image, line1, line2, has_frame, title, bg_url, color, font_name, img_text_color, is_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(guild_id), config_type,
                str(data.get('channel_id', '')), data.get('channel_name', ''),
                1 if data.get('is_embed') else 0,
                data.get('author', ''), data.get('description', ''), data.get('footer', ''),
                data.get('plain_text', ''), 1 if data.get('has_image') else 0,
                data.get('line1', 'WITAJ'), data.get('line2', '{nick}'),
                1 if data.get('has_frame') else 0,
                data.get('title', ''), data.get('bg_url', ''), data.get('color', '#74b816'),
                data.get('font_name', 'Inter-Bold.ttf'), data.get('img_text_color', '#ffffff'),
                1 if data.get('is_enabled', True) else 0
            ))
        conn.commit()
        new_id = c.lastrowid if not config_id else config_id
        conn.close()
        return new_id
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d zapisu welcome_config: {e}")
        return None

def sync_welcome_configs(guild_id, data):
    """Synchronizuje listÄ™ powitaĹ„ i poĹĽegnaĹ„ dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        
        # Usuwamy stare
        c.execute('DELETE FROM welcome_configs WHERE guild_id=?', (str(guild_id),))
        
        for type_key in ['powitanie', 'pozegnanie']:
            configs = data.get(type_key, [])
            for cfg in configs:
                c.execute('''
                    INSERT INTO welcome_configs
                        (guild_id, config_type, channel_id, channel_name, is_embed, author, description, footer, plain_text, has_image, line1, line2, has_frame, title, bg_url, color, font_name, img_text_color, is_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(guild_id), type_key,
                    cfg.get('channel_id', ''), cfg.get('channel_name', ''),
                    1 if cfg.get('is_embed') else 0,
                    cfg.get('author', ''), cfg.get('description', ''), cfg.get('footer', ''),
                    cfg.get('plain_text', ''), 1 if cfg.get('has_image') else 0,
                    cfg.get('line1', 'WITAJ'), cfg.get('line2', '{nick}'),
                    1 if cfg.get('has_frame') else 0,
                    cfg.get('title', ''), cfg.get('bg_url', ''),
                    cfg.get('color', '#74b816'), cfg.get('font_name', 'Inter-Bold.ttf'),
                    cfg.get('img_text_color', '#ffffff'), 1 if cfg.get('is_enabled', True) else 0
                ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d sync_welcome_configs: {e}")
        return False

def delete_welcome_config(guild_id, config_id):
    """Usuwa konfiguracjÄ™ powitania/poĹĽegnania."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM welcome_configs WHERE id=? AND guild_id=?', (config_id, str(guild_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d usuwania welcome_config: {e}")
        return False

# =============================================
# FUNKCJE â€“ konfiguracje mediĂłw (Social Media)
# =============================================



def delete_media_config(guild_id, config_id):
    """Usuwa konfiguracjÄ™ mediĂłw."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM media_configs WHERE id=? AND guild_id=?', (config_id, str(guild_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d usuwania media_config: {e}")
        return False

# =============================================
# FUNKCJE â€“ konfiguracje osadzeĹ„ (Embeds)
# =============================================

def get_embed_configs(guild_id):
    """Pobiera listÄ™ osadzeĹ„ dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('SELECT id, name, channel_id, author, title, description, footer, color, image_url, thumbnail_url, title_url, author_url, link_color, category, reaction_emoji, reaction_role_id, last_message_id, timestamp, enabled, outer_text, has_frame FROM embed_configs WHERE guild_id=?', (str(guild_id),))
        rows = c.fetchall()
        conn.close()
        keys = ['id', 'name', 'channel_id', 'author', 'title', 'description', 'footer', 'color', 'image_url', 'thumbnail_url', 'title_url', 'author_url', 'link_color', 'category', 'reaction_emoji', 'reaction_role_id', 'last_message_id', 'timestamp', 'enabled', 'outer_text', 'has_frame']
        return [dict(zip(keys, r)) for r in rows]
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d odczytu embed_configs: {e}")
        return []

def sync_embed_configs(guild_id, data):
    """Synchronizuje całą listę embedów dla serwera (bez usuwania wszystkiego)."""
    try:
        configs = data.get('configs', [])
        for cfg in configs:
            save_embed_config(guild_id, cfg, cfg.get('id'))
        
        # Tworzymy sygnał synchronizacji dla bota (opcjonalnie)
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d sync_embed_configs: {e}")
        return False

def save_embed_config(guild_id, data, config_id=None):
    """Zapisuje lub aktualizuje konfiguracjÄ™ osadzenia."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        if config_id:
            c.execute('''UPDATE embed_configs SET name=?, channel_id=?, author=?, title=?, description=?, footer=?, color=?, image_url=?, thumbnail_url=?, title_url=?, author_url=?, link_color=?, category=?, reaction_emoji=?, reaction_role_id=?, last_message_id=?, timestamp=?, outer_text=?, enabled=?, has_frame=? 
                         WHERE id=? AND guild_id=?''',
                      (data.get('name', 'Nowe Osadzenie'), data.get('channel_id', ''), data.get('author', ''), data.get('title', ''), 
                       data.get('description', ''), data.get('footer', ''), data.get('color', '#74b816'), data.get('image_url', ''),
                       data.get('thumbnail_url', ''), data.get('title_url', ''), data.get('author_url', ''), data.get('link_color', '#00a8fc'),
                       data.get('category', 'general'), data.get('reaction_emoji', ''), data.get('reaction_role_id', ''), data.get('last_message_id', ''),
                       1 if data.get('timestamp') else 0, data.get('outer_text', ''),
                       1 if data.get('enabled') else 0, 1 if data.get('has_frame') else 0, config_id, str(guild_id)))
            new_id = config_id
        else:
            # Sprawdzamy limit
            premium = is_premium(guild_id)
            limit = LIMITS_PREMIUM["embed_configs"] if premium else LIMITS_FREE["embed_configs"]
            
            c.execute('SELECT COUNT(*) FROM embed_configs WHERE guild_id=?', (str(guild_id),))
            if c.fetchone()[0] >= limit:
                conn.close()
                return None
            
            c.execute('''INSERT INTO embed_configs (guild_id, name, channel_id, author, title, description, footer, color, image_url, thumbnail_url, title_url, author_url, link_color, category, reaction_emoji, reaction_role_id, last_message_id, timestamp, outer_text, enabled, has_frame)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (str(guild_id), data.get('name', 'Nowe Osadzenie'), data.get('channel_id', ''), data.get('author', ''), data.get('title', ''),
                       data.get('description', ''), data.get('footer', ''), data.get('color', '#74b816'), data.get('image_url', ''),
                       data.get('thumbnail_url', ''), data.get('title_url', ''), data.get('author_url', ''), data.get('link_color', '#00a8fc'),
                       data.get('category', 'general'), data.get('reaction_emoji', ''), data.get('reaction_role_id', ''), data.get('last_message_id', ''),
                       1 if data.get('timestamp') else 0, data.get('outer_text', ''),
                       1 if data.get('enabled', True) else 0, 1 if data.get('has_frame') else 0))
            new_id = c.lastrowid
        conn.commit()
        conn.close()
        return new_id
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d zapisu embed_config: {e}")
        return None

def delete_embed_config(guild_id, config_id):
    """Usuwa konfiguracjÄ™ osadzenia."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM embed_configs WHERE id=? AND guild_id=?', (config_id, str(guild_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d usuwania embed_config: {e}")
        return False

def get_selfrole_configs(guild_id):
    """Pobiera wszystkie konfiguracje Selfrole dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM self_role_configs WHERE guild_id=?', (str(guild_id),))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d odczytu self_role_configs: {e}")
        return []

def sync_selfrole_configs(guild_id, data):
    """Synchronizuje całą listę Selfrole dla serwera (bez usuwania wszystkiego)."""
    try:
        configs = data.get('configs', [])
        for cfg in configs:
            save_selfrole_config(guild_id, cfg, cfg.get('id'))
        return True
    except Exception as e:
        print(f"❌ Błąd synchronizacji self_role_configs: {e}")
        return False

def save_selfrole_config(guild_id, data, config_id=None):
    """Zapisuje lub aktualizuje pojedynczą konfigurację Selfrole."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        
        roles_json = data.get('roles_json', '[]')
        if not isinstance(roles_json, str):
            import json
            roles_json = json.dumps(roles_json)

        if config_id:
            c.execute('''UPDATE self_role_configs SET 
                         type=?, name=?, channel_id=?, message_id=?, roles_json=?, enabled=?, image_url=?, thumbnail_url=?, description=? 
                         WHERE id=? AND guild_id=?''',
                      (data.get('type', 'reaction'), data.get('name', ''), data.get('channel_id', ''), 
                       data.get('message_id', ''), roles_json, 1 if data.get('enabled') else 0,
                       data.get('image_url', ''), data.get('thumbnail_url', ''), data.get('description', ''),
                       config_id, str(guild_id)))
            new_id = config_id
        else:
            c.execute('''INSERT INTO self_role_configs (guild_id, type, name, channel_id, message_id, roles_json, enabled, image_url, thumbnail_url, description)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (str(guild_id), data.get('type', 'reaction'), data.get('name', ''),
                       data.get('channel_id', ''), data.get('message_id', ''),
                       roles_json, 1 if data.get('enabled') else 0,
                       data.get('image_url', ''), data.get('thumbnail_url', ''), data.get('description', '')))
            new_id = c.lastrowid
            
        conn.commit()
        conn.close()
        return new_id
    except Exception as e:
        print(f"❌ Błąd zapisu selfrole_config: {e}")
        return None

def delete_selfrole_config(guild_id, config_id):
    """Usuwa konfigurację Selfrole."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM self_role_configs WHERE id=? AND guild_id=?', (config_id, str(guild_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Błąd usuwania selfrole_config: {e}")
        return False

def is_premium(guild_id):
    """Sprawdza, czy serwer posiada status Premium."""
    settings = get_settings(guild_id)
    return settings.get("premium", False)

def set_premium(guild_id, status):
    """Nadaje lub odbiera status Premium dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''
            INSERT INTO settings (guild_id, premium)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET premium=excluded.premium
        ''', (str(guild_id), 1 if status else 0))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d zapisu premium: {e}")
        return False

def get_media_configs(guild_id):
    """Pobiera listÄ™ konfiguracji mediĂłw."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM media_configs WHERE guild_id=?', (str(guild_id),))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"❌ Błąd odczytu media_configs: {e}")
        return []



def sync_media_configs(guild_id, configs):
    """Synchronizuje listÄ™ mediĂłw."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM media_configs WHERE guild_id=?', (str(guild_id),))
        for cfg in configs:
            c.execute('''
                INSERT INTO media_configs (guild_id, platform, account_id, discord_channel_id, message, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                str(guild_id), cfg.get('platform'), cfg.get('account_id'),
                cfg.get('discord_channel_id'), cfg.get('message'),
                1 if cfg.get('enabled') else 0
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"âťŚ BĹ‚Ä…d synchronizacji media_configs: {e}")
        return False


def add_audit_log(guild_id, category, user_name, user_id, action, details):
    """Zapisuje zdarzenie do logów audytu."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('''INSERT INTO audit_logs (guild_id, category, user_name, user_id, action, details)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (str(guild_id), category, user_name, str(user_id), action, details))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ [DB] Błąd add_audit_log: {e}")
        return False

def get_audit_logs(guild_id, limit=50):
    """Pobiera historię zdarzeń dla serwera."""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM audit_logs WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?', (str(guild_id), limit))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"❌ [DB] Błąd get_audit_logs: {e}")
        return []

def get_global_color(guild_id):
    """Pobiera globalny kolor embedów dla serwera (z obsługą RGB)."""
    import random
    settings = get_settings(guild_id)
    if settings.get('rgb_mode'):
        return random.randint(0, 0xFFFFFF)
    color_hex = settings.get('embed_color', '#74b816').replace('#', '')
    try: return int(color_hex, 16)
    except: return 0x74b816

# =============================================
# FUNKCJE – Self Role & Media Radar
# =============================================

def get_selfrole_configs(guild_id):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM self_role_configs WHERE guild_id=?', (str(guild_id),))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except: return []

def sync_selfrole_configs(guild_id, configs):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        for cfg in configs:
            c.execute('''
                INSERT INTO self_role_configs (guild_id, type, name, description, image_url, thumbnail_url, roles_json, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type, name=excluded.name, description=excluded.description,
                    image_url=excluded.image_url, thumbnail_url=excluded.thumbnail_url,
                    roles_json=excluded.roles_json, enabled=excluded.enabled
            ''', (
                str(guild_id), cfg.get('type', 'button'), cfg.get('name', ''),
                cfg.get('description', ''), cfg.get('image_url', ''), cfg.get('thumbnail_url', ''),
                json.dumps(cfg.get('roles', [])), 1 if cfg.get('enabled', True) else 0
            ))
        conn.commit(); conn.close()
        return True
    except: return False

def get_media_configs(guild_id):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM media_configs WHERE guild_id=?', (str(guild_id),))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except: return []

def sync_media_configs(guild_id, configs):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        c = conn.cursor()
        c.execute('DELETE FROM media_configs WHERE guild_id=?', (str(guild_id),))
        for cfg in configs:
            c.execute('INSERT INTO media_configs (guild_id, platform, account_id, discord_channel_id, message, enabled) VALUES (?, ?, ?, ?, ?, ?)',
                     (str(guild_id), cfg['platform'], cfg['account_id'], cfg['discord_channel_id'], cfg['message'], 1 if cfg.get('enabled', True) else 0))
        conn.commit(); conn.close()
        return True
    except: return False

init_db()

