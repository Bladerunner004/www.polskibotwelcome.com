import os
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# --- KONFIGURACJA DISCORD OAuth2 ---
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1489047223160541295")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "NXfIWXi2Tdgcl1qBZBSLwJYTVelt_fFj")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://BLADERUNNER009.pythonanywhere.com/callback")


# Pobieranie tokena bota z pliku .env
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# --- LINKI ---
DISCORD_INVITE_URL = (
    f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}"
    f"&permissions=8&scope=bot%20applications.commands"
)


DISCORD_LINK = "https://discord.gg/RunF9ehW6"

# --- FUNKCJE GENERUJĄCE ---

def get_login_url():
    """Generuje URL do logowania bez /api/ dla lepszej stabilności sesji"""
    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
    )

LOGIN_URL = get_login_url()

def get_user_avatar(user):
    if not user:
        return "https://cdn.discordapp.com/embed/avatars/0.png"
    user_id = user.get('id')
    avatar_hash = user.get('avatar')
    if avatar_hash:
        # Jeśli hash zaczyna się od a_, jest to GIF
        ext = 'gif' if avatar_hash.startswith('a_') else 'png'
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}"
    return f"https://cdn.discordapp.com/embed/avatars/{int(user_id or 0) % 5}.png"


# --- STYLE I STAŁE ---
GLOBAL_STYLE = \"\"\"
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    :root {
        --accent-green: #a3e635;
        --bg-dark: #030508;
    }
    body { 
        font-family: 'Inter', sans-serif; 
        background-color: var(--bg-dark); 
        color: white; 
        margin: 0; 
        padding: 0; 
    }
</style>
\"\"\"

config = {
    "CLIENT_ID": CLIENT_ID,
    "CLIENT_SECRET": CLIENT_SECRET,
    "REDIRECT_URI": REDIRECT_URI,
    "LOGIN_URL": LOGIN_URL,
    "DISCORD_LINK": DISCORD_LINK,
    "DISCORD_INVITE_URL": DISCORD_INVITE_URL,
    "BOT_TOKEN": BOT_TOKEN
}

# --- LIMITS ---
LIMITS_FREE = {
    "role_counters": 3,
    "welcome_configs": 2,
    "embed_configs": 5,
    "media_configs": 2
}

LIMITS_PREMIUM = {
    "role_counters": 15,
    "welcome_configs": 20,
    "embed_configs": 50,
    "media_configs": 10
}