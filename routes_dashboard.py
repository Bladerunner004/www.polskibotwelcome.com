import os
import requests
import urllib.parse
import datetime
from flask import Blueprint, render_template, session, redirect, url_for, request
from base import BOT_TOKEN, CLIENT_ID, REDIRECT_URI

dashboard_bp = Blueprint('dashboard', __name__)

# --- CACHE DLA SERWERÓW BOTA (Plikowy cache współdzielony między procesami) ---
def get_bot_guilds_cached():
    import time
    import json
    
    cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_guilds_cache.json")
    
    # Próbujemy odczytać cache z pliku
    cache_data = None
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass
            
    # Jeśli cache jest świeży (młodszy niż 30 sekund), używamy go
    if cache_data and isinstance(cache_data, dict):
        last_update = cache_data.get("last_update", 0)
        if time.time() - last_update < 30:
            return set(cache_data.get("guild_ids", []))
            
    # W przeciwnym razie aktualizujemy cache
    guild_ids_list = []
    
    # 1. Próbujemy pobrać z lokalnego API bota
    try:
        resp = requests.get("http://127.0.0.1:5006/guilds", timeout=1.0)
        if resp.status_code == 200:
            guild_ids_list = [str(g) for g in resp.json().get('guild_ids', [])]
    except Exception:
        pass
        
    # 2. Fallback: Pobieramy bezpośrednio z Discord API
    if not guild_ids_list and BOT_TOKEN:
        try:
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get(
                "https://discord.com/api/v10/users/@me/guilds?limit=200",
                headers=headers,
                timeout=5
            )
            if resp.status_code == 200:
                guild_ids_list = [str(g['id']) for g in resp.json()]
            else:
                print(f"[BOT GUILDS] Discord API błąd: {resp.status_code}")
        except Exception as e:
            print(f"[BOT GUILDS] Błąd połączenia: {e}")
            
    # Zapisujemy nowy cache do pliku
    if guild_ids_list or not cache_data:
        try:
            with open(cache_file, "w") as f:
                json.dump({
                    "last_update": time.time(),
                    "guild_ids": guild_ids_list
                }, f)
        except Exception:
            pass
        return set(guild_ids_list)
        
    # Fallback do starego cache jeśli API nie odpowiedziało
    return set(cache_data.get("guild_ids", []))

def clear_bot_guilds_cache():
    cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_guilds_cache.json")
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
        except Exception:
            pass



@dashboard_bp.route('/dashboard')
def dashboard():
    if request.args.get('refresh') == 'true':
        clear_bot_guilds_cache()

    # 1. Sprawdzamy sesję
    if 'user' not in session or 'access_token' not in session:
        return redirect(url_for('home.index'))

    user_data = session.get('user')
    access_token = session.get('access_token')
    user_id = user_data.get('id') if user_data else None

    # 2. Pobieramy serwery użytkownika z pamięci procesu (nie z cookie - brak limitu 4KB)
    from base import _guilds_memory_cache
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
            
            # Sprawdzamy obecność bota - albo jest główny bot na serwerze,
            # albo istnieje w bazie danych skonfigurowany custom bot lub bot muzyczny dla tej gildii
            has_custom_bot = False
            has_music_bot = False
            try:
                from database import get_custom_bot, get_music_bots
                c_bot = get_custom_bot(guild_id)
                if c_bot and c_bot.get('token'):
                    has_custom_bot = True
                m_bots = get_music_bots(guild_id)
                if m_bots:
                    has_music_bot = True
            except:
                pass

            bot_present = (guild_id in bot_guild_ids) or has_custom_bot or has_music_bot

            from database import is_premium
            premium_status = is_premium(guild_id) if bot_present else False

            icon_hash = guild.get('icon')
            icon_url = None
            if icon_hash:
                ext = 'gif' if icon_hash.startswith('a_') else 'png'
                icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}"

            user_servers.append({
                "id": guild_id,
                "name": guild.get('name'),
                "role": "Właściciel" if guild.get('owner') else "Administrator",
                "icon": icon_hash,
                "icon_url": icon_url,
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

    # Link zaproszenia bota - po zaproszeniu Discord sam wróci na /callback z guild_id
    discord_invite = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code"

    return render_template(
        'dashboard.html', 
        servers=user_servers,
        user=user_data,
        user_avatar=user_avatar,
        discord_invite=discord_invite
    )