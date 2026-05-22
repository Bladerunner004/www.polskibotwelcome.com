import os
import base64
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# Pobieranie tokena bota z pliku .env
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Automatyczne dekodowanie CLIENT_ID z pierwszego członu tokena bota (Base64)
def _extract_client_id(token):
    if not token or '.' not in token:
        return None
    try:
        first_part = token.split('.')[0]
        # Dopełnienie do wielokrotności 4 znaków dla Base64
        missing_padding = len(first_part) % 4
        if missing_padding:
            first_part += '=' * (4 - missing_padding)
        decoded = base64.b64decode(first_part).decode('utf-8')
        if decoded.isdigit():
            return decoded
    except Exception:
        pass
    return None

extracted_id = _extract_client_id(BOT_TOKEN)

# --- KONFIGURACJA DISCORD OAuth2 ---
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID") or extracted_id or "1489047223160541295"
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "NXfIWXi2Tdgcl1qBZBSLwJYTVelt_fFj")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://BLADERUNNER009.pythonanywhere.com/callback")


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
        f"&redirect_uri={quote(REDIRECT_URI, safe='')}"
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
GLOBAL_STYLE = """
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
"""

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
# Ostateczna poprawka linku i stylu