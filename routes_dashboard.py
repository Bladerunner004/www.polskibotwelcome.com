import os
import requests
import urllib.parse
import datetime
from flask import Blueprint, render_template, session, redirect, url_for, request
from base import BOT_TOKEN, CLIENT_ID, REDIRECT_URI

dashboard_bp = Blueprint('dashboard', __name__)

# --- CACHE DLA SERWERÓW BOTA (Dla szybkości dashboardu) ---
_bot_guilds_cache = None
_bot_guilds_last_update = 0
_bot_token_invalid = False

def get_bot_guilds_cached():
    global _bot_guilds_cache, _bot_guilds_last_update, _bot_token_invalid
    import time
    
    if _bot_guilds_cache and (time.time() - _bot_guilds_last_update < 30):
        return _bot_guilds_cache

    # 1. Próbujemy pobrać z lokalnego API bota (działa gdy bot jest w tej samej maszynie)
    try:
        resp = requests.get("http://127.0.0.1:5006/guilds", timeout=1.0)
        if resp.status_code == 200:
            guild_ids = resp.json().get('guild_ids', [])
            _bot_guilds_cache = set(str(g) for g in guild_ids)
            _bot_guilds_last_update = time.time()
            _bot_token_invalid = False
            return _bot_guilds_cache
    except Exception:
        pass  # Bot offline lub na innym serwerze (PythonAnywhere) - używamy Discord API

    # 2. Fallback: Pobieramy bezpośrednio z Discord API (zawsze działa)
    if BOT_TOKEN:
        try:
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get(
                "https://discord.com/api/v10/users/@me/guilds?limit=200",
                headers=headers,
                timeout=5
            )
            if resp.status_code == 200:
                _bot_guilds_cache = {str(g['id']) for g in resp.json()}
                _bot_guilds_last_update = time.time()
                _bot_token_invalid = False
                return _bot_guilds_cache
            elif resp.status_code == 401:
                print("[BOT GUILDS] Discord API błąd: 401 Unauthorized (Nieprawidłowy token bota!)")
                _bot_token_invalid = True
            else:
                print(f"[BOT GUILDS] Discord API błąd: {resp.status_code}")
        except Exception as e:
            print(f"[BOT GUILDS] Błąd połączenia: {e}")
    else:
        _bot_token_invalid = True

    return _bot_guilds_cache or set()


@dashboard_bp.route('/dashboard')
def dashboard():
    global _bot_guilds_last_update
    if request.args.get('refresh') == 'true':
        _bot_guilds_last_update = 0

    # 1. Sprawdzamy sesję
    if 'user' not in session or 'access_token' not in session:
        return redirect(url_for('home.index'))

    user_data = session.get('user')
    access_token = session.get('access_token')
    user_id = user_data.get('id') if user_data else None

    # 2. Pobieramy serwery użytkownika z pamięci procesu (nie z cookie - brak limitu 4KB)
    from run import _guilds_memory_cache
    user_guilds = _guilds_memory_cache.get(user_id, [])

    if not user_guilds or request.args.get('refresh') == 'true':
        user_headers = {"Authorization": f"Bearer {access_token}"}
        try:
            user_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=user_headers, timeout=5)
            if user_resp.status_code == 200:
                all_guilds = user_resp.json()
                # Zapisujemy w pamięci (nie w ciasteczku)
                user_guilds = [
                    {
                        'id': g.get('id'),
                        'name': g.get('name'),
                        'icon': g.get('icon'),
                        'permissions': g.get('permissions'),
                        'owner': g.get('owner')
                    }
                    for g in all_guilds
                ]
                if user_id:
                    _guilds_memory_cache[user_id] = user_guilds
            elif user_resp.status_code == 429:
                print("[DASHBOARD] Discord Rate Limit (429). Korzystam z cache w pamięci.")
            else:
                print(f"[DASHBOARD] Błąd Discord API ({user_resp.status_code}).")
        except Exception as e:
            print(f"[DASHBOARD] Błąd połączenia z Discord API ({e}).")

    user_servers = []
    bot_guild_ids = get_bot_guilds_cached()

    # 4. Filtrowanie i ikony
    for guild in user_guilds:
        permissions = int(guild.get('permissions', 0))
        is_admin = (permissions & 0x8) == 0x8 or guild.get('owner', False)

        if is_admin:
            guild_id = str(guild.get('id')) 
            bot_present = guild_id in bot_guild_ids

            from database import is_premium
            premium_status = is_premium(guild_id) if bot_present else False

            user_servers.append({
                "id": guild_id,
                "name": guild.get('name'),
                "role": "Właściciel" if guild.get('owner') else "Administrator",
                "icon": guild.get('icon'),
                "has_bot": bot_present,
                "premium": premium_status
            })

    # 5. Przygotowanie danych awatara
    user_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
    if user_data:
        uid = user_data.get('id')
        av_hash = user_data.get('avatar')
        if uid and av_hash:
            ext = 'gif' if av_hash.startswith('a_') else 'png'
            user_avatar = f"https://cdn.discordapp.com/avatars/{uid}/{av_hash}.{ext}"

    # Link zaproszenia bota - po zaproszeniu Discord sam wróci na /callback z guild_id i pełnym tokenem (scope)
    discord_invite = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands%20identify%20guilds&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code"

    return render_template(
        'dashboard.html', 
        servers=user_servers,
        user=user_data,
        user_avatar=user_avatar,
        discord_invite=discord_invite,
        bot_token_error=_bot_token_invalid
    )