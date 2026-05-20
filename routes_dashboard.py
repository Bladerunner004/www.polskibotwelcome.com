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

def get_bot_guilds_cached():
    global _bot_guilds_cache, _bot_guilds_last_update
    import time
    from base import BOT_TOKEN
    
    if _bot_guilds_cache and (time.time() - _bot_guilds_last_update < 60):
        return _bot_guilds_cache

    # 1. Próbujemy pobrać listę serwerów z lokalnego API bota (jest natychmiastowe i nie ma limitów)
    try:
        resp = requests.get("http://127.0.0.1:5006/guilds", timeout=1.0)
        if resp.status_code == 200:
            guild_ids = resp.json().get('guild_ids', [])
            _bot_guilds_cache = set(guild_ids)
            _bot_guilds_last_update = time.time()
            return _bot_guilds_cache
    except Exception as e:
        # Bot offline - przechodzimy do fallbacka
        pass
        
    # 2. Fallback: Pobieramy z oficjalnego API Discorda
    if BOT_TOKEN:
        try:
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=headers, timeout=2)
            if resp.status_code == 200:
                _bot_guilds_cache = {str(g['id']) for g in resp.json()}
                _bot_guilds_last_update = time.time()
                return _bot_guilds_cache
        except: pass
    return _bot_guilds_cache or set()

@dashboard_bp.route('/dashboard')
def dashboard():
    global _bot_guilds_last_update
    if request.args.get('refresh') == 'true':
        _bot_guilds_last_update = 0
        session.pop('user_guilds', None)

    # 1. Sprawdzamy sesję
    if 'user' not in session or 'access_token' not in session:
        return redirect(url_for('home.index'))

    user_data = session.get('user')
    access_token = session.get('access_token')
    
    # 2. Pobieramy serwery użytkownika (z obsługą cache i ochroną przed wylogowaniem przy Rate Limitach/Timeoutach)
    user_guilds = session.get('user_guilds', [])
    user_headers = {"Authorization": f"Bearer {access_token}"}
    try:
        user_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=user_headers, timeout=5)
        if user_resp.status_code == 200:
            user_guilds = user_resp.json()
            # Optimize to prevent Flask cookie size overflow (limit 4KB)
            optimized_guilds = []
            for g in user_guilds:
                optimized_guilds.append({
                    'id': g.get('id'),
                    'name': g.get('name'),
                    'icon': g.get('icon'),
                    'permissions': g.get('permissions'),
                    'owner': g.get('owner')
                })
            session['user_guilds'] = optimized_guilds
            session.modified = True
        elif user_resp.status_code == 429:
            print("[DASHBOARD] Discord Rate Limit (429). Korzystam z serwerow zapisanych w sesji.")
        else:
            print(f"[DASHBOARD] Blad Discord API ({user_resp.status_code}). Korzystam z serwerow w sesji.")
    except Exception as e:
        print(f"[DASHBOARD] Blad polaczenia z Discord API ({e}). Korzystam z serwerow w sesji.")

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

    # Link zaproszenia bota z przekierowaniem z powrotem na stronę
    discord_invite = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code"

    return render_template(
        'dashboard.html', 
        servers=user_servers,
        user=user_data,
        user_avatar=user_avatar,
        discord_invite=discord_invite
    )