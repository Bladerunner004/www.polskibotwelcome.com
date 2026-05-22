import os
import sqlite3
import requests
import json
import time
try:
    import stripe
except ImportError:
    stripe = None
import uuid
from datetime import datetime, timedelta

# Ścieżka do statusu (dla PythonAnywhere)
STATUS_FILE_PATH = "/home/BLADERUNNER009/AntigravityProjekt/bot_status.json"
if not os.path.exists("/home/BLADERUNNER009"):
    STATUS_FILE_PATH = "bot_status.json" # Fallback lokalny
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from base import BOT_TOKEN
from database import get_settings, save_settings, get_command_settings, save_command_settings, get_welcome_configs, save_welcome_config, delete_welcome_config, get_audit_logs
from werkzeug.utils import secure_filename

config_bp = Blueprint('config', __name__)

# Awatar bota cache (klucz: guild_id lub "main" -> {"url": url, "last_fetched": timestamp})
_bot_avatar_cache = {}

def get_bot_avatar_cached(guild_id=None):
    now = time.time()
    token_to_use = BOT_TOKEN
    cache_key = "main"

    if guild_id:
        try:
            from database import get_custom_bot
            custom_bot = get_custom_bot(guild_id)
            if custom_bot and custom_bot.get('enabled') and custom_bot.get('token'):
                token_to_use = custom_bot['token']
                cache_key = str(guild_id)
        except Exception as e:
            print(f"[BOT AVATAR] Błąd pobierania custom bota z DB dla {guild_id}: {e}")

    try:
        force_refresh = request.args.get('refresh') == 'true'
    except Exception:
        force_refresh = False

    cached = _bot_avatar_cache.get(cache_key)
    if not force_refresh and cached and (now - cached.get("last_fetched", 0) < 600):
        return cached["url"]
        
    try:
        headers = {"Authorization": f"Bot {token_to_use}"}
        resp = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            b_id = data.get("id")
            b_av = data.get("avatar")
            if b_id and b_av:
                ext = 'gif' if b_av.startswith('a_') else 'png'
                url = f"https://cdn.discordapp.com/avatars/{b_id}/{b_av}.{ext}"
            else:
                url = "/static/img/polskibot_logo.png"
            _bot_avatar_cache[cache_key] = {
                "url": url,
                "last_fetched": now
            }
            return url
    except Exception as e:
        print(f"[BOT AVATAR FETCH] Error dla {cache_key}: {e}")
        
    if cached:
        return cached["url"]
    return "/static/img/polskibot_logo.png"


def check_guild_access(guild_id):
    """Sprawdza czy zalogowany użytkownik ma dostęp do zarządzania danym serwerem."""
    if 'user' not in session: return False
    user_data = session.get('user')
    if not user_data: return False
    user_id = user_data.get('id')
    if not user_id: return False
    
    from run import _guilds_memory_cache
    managed_guilds = _guilds_memory_cache.get(user_id, [])
    
    # Jeśli cache jest pusty, a mamy access_token, spróbujmy odpytać Discord API
    if not managed_guilds and session.get('access_token'):
        try:
            access_token = session.get('access_token')
            user_headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=user_headers, timeout=5)
            if resp.status_code == 200:
                all_guilds = resp.json()
                managed_guilds = [
                    {
                        'id': g.get('id'),
                        'name': g.get('name'),
                        'icon': g.get('icon'),
                        'permissions': g.get('permissions'),
                        'owner': g.get('owner')
                    }
                    for g in all_guilds
                ]
                _guilds_memory_cache[user_id] = managed_guilds
        except Exception as e:
            print(f"[SECURITY CHECK] Błąd podczas pobierania serwerów z API: {e}")
            
    # Porównujemy ID serwerów jako stringi
    return any(str(g.get('id')) == str(guild_id) for g in managed_guilds)


@config_bp.before_request
def security_check():
    """Globalne zabezpieczenie dla wszystkich ścieżek API i konfiguracji."""
    # Jeśli to ścieżka /api/<guild_id>/..., sprawdź uprawnienia
    if request.path.startswith('/api/'):
        # Wyjątki dla statusu bota
        if request.path.startswith('/api/bot/'): return
        if request.path.startswith('/api/debug/'): return # Opcjonalnie zablokować też to
        
        parts = request.path.split('/')
        if len(parts) >= 3:
            guild_id = parts[2]
            # Sprawdzamy czy to wygląda na ID serwera (same cyfry)
            if guild_id.isdigit() and len(guild_id) > 15:
                if not check_guild_access(guild_id):
                    return jsonify({'success': False, 'error': 'Nie masz uprawnień do zarządzania tym serwerem!'}), 403
    
    # Dla ścieżki /config/<guild_id> (główna strona)
    if request.endpoint == 'config.config':
        guild_id = request.view_args.get('server_id')
        if guild_id and not check_guild_access(guild_id):
            return redirect(url_for('dashboard.dashboard'))

# --- STRIPE CONFIGURATION ---
if stripe:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# --- WEWNĘTRZNA KOMUNIKACJA Z BOTEM ---
BOT_API_URL = "http://127.0.0.1:5006"
_bot_offline_cache = 0  # Timestamp ostatniej nieudanej próby

def call_bot_api(endpoint, method="GET", data=None):
    """Pomocnicza funkcja do komunikacji z wewnętrznym API bota."""
    global _bot_offline_cache
    import time
    import json
    import os

    resp_data = None
    http_success = False

    # 1. Jeśli bot nie był offline w ciągu ostatnich 5 sekund, próbujemy połączenia HTTP
    if time.time() - _bot_offline_cache >= 5:
        try:
            url = f"{BOT_API_URL}{endpoint}"
            if method == "GET":
                resp = requests.get(url, timeout=1.5)
            else:
                resp = requests.post(url, json=data, timeout=1.5)

            if resp.status_code == 200:
                resp_data = resp.json()
                http_success = True
        except Exception as e:
            _bot_offline_cache = time.time()

    # 2. Jeśli to POST i HTTP się NIE powiodło (lub bot jest offline), tworzymy plik synchronizacji
    if method == "POST" and not http_success:
        try:
            guild_id = None
            if '/guilds/' in endpoint:
                guild_id = endpoint.split('/')[2]
            elif data and isinstance(data, dict):
                guild_id = data.get('guild_id') or data.get('server_id')

            if guild_id:
                sync_dir = os.path.dirname(os.path.abspath(__file__))
                filename = f"sync_needed_{guild_id}_{int(time.time()*1000)}.json"
                filepath = os.path.join(sync_dir, filename)
                print(f"[DASHBOARD] Tworzenie sygnalu synchronizacji (FALLBACK): {filepath}")
                with open(filepath, "w") as f:
                    json.dump({"endpoint": endpoint, "time": time.time(), "data": data}, f)
        except Exception as e:
            print(f"[DASHBOARD] Blad tworzenia pliku sync: {e}")

    return resp_data


@config_bp.route('/api/bot/latency')
def api_bot_latency():
    # Na PythonAnywhere używamy pliku statusu dla lepszej stabilności
    try:
        if os.path.exists(STATUS_FILE_PATH):
            with open(STATUS_FILE_PATH, "r") as f:
                data = json.load(f)
                # Sprawdzamy czy status jest "świeży" (ostatnie 30 sekund)
                if time.time() - data.get('last_seen', 0) < 30:
                    return jsonify(data)
    except: pass
    
    # Fallback do starej metody (jeśli bot działa lokalnie na tym samym porcie)
    data = call_bot_api("/latency")
    if data:
        return jsonify(data)
    return jsonify({'latency': 0})

@config_bp.route('/api/debug/sync')
def api_debug_sync():
    """Endpoint diagnostyczny - pokazuje stan systemu synchronizacji."""
    import glob
    import time
    
    sync_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Znajdź pliki sync
    sync_files = glob.glob(os.path.join(sync_dir, "sync_needed_*.json"))
    sync_info = []
    for sf in sync_files:
        try:
            with open(sf, 'r') as f:
                content = json.load(f)
            sync_info.append({
                "file": os.path.basename(sf),
                "age_seconds": round(time.time() - os.path.getmtime(sf), 1),
                "content": content
            })
        except Exception as e:
            sync_info.append({"file": os.path.basename(sf), "error": str(e)})
    
    # Status bota
    bot_status = None
    bot_age = None
    try:
        if os.path.exists(STATUS_FILE_PATH):
            with open(STATUS_FILE_PATH, 'r') as f:
                bot_status = json.load(f)
            bot_age = round(time.time() - bot_status.get('last_seen', 0), 1)
    except Exception as e:
        bot_status = {"error": str(e)}
    
    # Ostatnie logi błędów bota
    bot_log_tail = []
    log_path = os.path.join(sync_dir, "bot_error.log")
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                bot_log_tail = lines[-30:]  # ostatnie 30 linii
    except Exception as e:
        bot_log_tail = [f"Błąd odczytu logu: {e}"]
    
    return jsonify({
        "sync_dir": sync_dir,
        "status_file_path": STATUS_FILE_PATH,
        "status_file_exists": os.path.exists(STATUS_FILE_PATH),
        "bot_status": bot_status,
        "bot_last_seen_seconds_ago": bot_age,
        "pending_sync_files": sync_info,
        "bot_log_tail": bot_log_tail
    })

@config_bp.route('/config/<server_id>/checkout')
def premium_checkout(server_id):
    if 'user' not in session or server_id == 'None':
        return redirect(url_for('dashboard.dashboard'))
    plan_name = request.args.get('plan', 'PREMIUM')
    plan_price = request.args.get('price', '15.00')
    return render_template('glowne/checkout.html', server_id=server_id, plan_name=plan_name, plan_price=plan_price)



@config_bp.route('/config/<server_id>', methods=['GET', 'POST'])
def config(server_id):
    if 'user' not in session or server_id == 'None':
        return redirect(url_for('dashboard.dashboard'))
    
    # POST - Zapisywanie ustawień głównych i komend
    if request.method == 'POST':
        data = request.json
        prefix = data.get('prefix', '!')
        language = data.get('language', 'pl')
        embed_color = data.get('embed_color', '#74b816')
        # Nowe: Ustawienia moderacji i AutoMod
        mod_enabled = data.get('moderation_enabled', True)
        mod_confirm = data.get('moderation_confirm', False)
        am_antilink = data.get('automod_antilink', False)
        am_anticaps = data.get('automod_anticaps', False)
        am_antispam = data.get('automod_antispam', False)
        am_badwords = data.get('automod_badwords', False)
        am_badwords_list = json.dumps(data.get('automod_badwords_list', []))
        am_antiphishing = data.get('automod_antiphishing', False)
        
        rgb_mode = data.get('rgb_mode', 0)
        enabled_cmds = data.get('commands', [])
        
        # Zapisujemy prefix, język, kolory i moderację + automod
        save_settings(server_id, True, mod_enabled, True, prefix, language, embed_color, rgb_mode, mod_confirm, am_antilink, am_anticaps, am_antispam, am_badwords, am_badwords_list, am_antiphishing)
        # Zapisujemy stan komend
        save_command_settings(server_id, enabled_cmds)
        
        return jsonify({'success': True})

    # GET - Wyświetlanie strony
    try:
        guild_id_int = int(server_id)
    except ValueError:
        return redirect(url_for('dashboard.dashboard'))

    # Pobieramy dane serwera przez API (bot może być w innym procesie)
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    # Pobieramy podstawowe info o serwerze (z ilością osób)
    guild_resp = requests.get(f"https://discord.com/api/v10/guilds/{server_id}?with_counts=true", headers=headers)
    if guild_resp.status_code != 200:
        return redirect(url_for('dashboard.dashboard'))
    guild_data = guild_resp.json()

    # Pobieramy kanały i role
    channels = []
    roles = []
    
    # 1. Próbujemy pobrać z lokalnego API bota (szybciej, brak limitów)
    try:
        c_resp = requests.get(f"http://127.0.0.1:5006/guilds/{server_id}/channels", timeout=1.0)
        r_resp = requests.get(f"http://127.0.0.1:5006/guilds/{server_id}/roles", timeout=1.0)
        if c_resp.status_code == 200 and r_resp.status_code == 200:
            channels = c_resp.json()
            roles = r_resp.json()
    except Exception as e:
        pass

    # 2. Fallback: Jeśli lokalne API nie odpowiedziało, odpytujemy bezpośrednio Discorda
    if not channels or not roles:
        if not channels:
            channels_resp = requests.get(f"https://discord.com/api/v10/guilds/{server_id}/channels", headers=headers)
            all_channels = channels_resp.json() if channels_resp.status_code == 200 else []
            channels = [{"id": str(c['id']), "name": c['name']} for c in all_channels if c['type'] in (0, 5)]
        
        if not roles:
            roles_resp = requests.get(f"https://discord.com/api/v10/guilds/{server_id}/roles", headers=headers)
            all_roles = roles_resp.json() if roles_resp.status_code == 200 else []
            roles = []
            for r in all_roles:
                if r['name'] != "@everyone" and not r.get('managed'):
                    color_int = r.get('color', 0)
                    color_hex = f"#{color_int:06x}" if color_int != 0 else "#b5bac1"
                    roles.append({"id": str(r['id']), "name": r['name'], "color": color_hex})
    
    # Pobieramy statystyki (najpierw próbujemy z pliku statusu bota)
    bot_latency = None
    try:
        status_path = "bot_status.json"
        if os.path.exists(status_path):
            with open(status_path, "r") as f:
                bot_status = json.load(f)
                # Sprawdzamy czy status nie jest przestarzały (max 30 sek)
                if time.time() - bot_status.get('last_seen', 0) < 30:
                    bot_latency = bot_status.get('latency')
    except: pass

    # Jeśli z pliku nie wyszło, fallback na API (jeśli bot jest na tym samym serwerze)
    if bot_latency is None:
        bot_info = call_bot_api("/latency")
        bot_latency = bot_info.get('latency') if bot_info else None
    
    # Rozszerzone dane o serwerze (ilość osób itp)
    guild = {
        "name": guild_data.get('name'), 
        "id": server_id,
        "icon": guild_data.get('icon'),
        "member_count": guild_data.get('approximate_member_count') or guild_data.get('member_count', 0),
        "owner_id": guild_data.get('owner_id')
    }
    
    # Pobieramy stan komend i ustawienia (w tym prefix)
    cmd_settings = get_command_settings(server_id)
    main_settings = get_settings(server_id)
    from database import get_role_counters
    role_counters = get_role_counters(server_id)
    audit_logs = get_audit_logs(server_id)
    formatted_logs = []
    import re
    
    def clean_str(s):
        return re.sub(r'[^a-zA-Z0-9]', '', s).lower()
        
    channel_map = {str(c['id']): c['name'] for c in channels}
    role_map = {str(r['id']): r['name'] for r in roles}
    
    for log in audit_logs:
        db_username = log.get('user_name', '')
        user_id = log.get('user_id', '')
        if (not user_id or user_id == '0') and '(' in db_username:
            match = re.search(r'\(([^)]+)\)', db_username)
            if match:
                user_id = match.group(1)
        username = re.sub(r'\s*\([^)]+\)', '', db_username)
        
        details = log.get('details', '')
        
        # 1. Replace <@&ID> with @RoleName
        def rep_role(m):
            rid = m.group(1)
            return f"@{role_map.get(rid, 'rola-' + rid)}"
        details = re.sub(r'<@&([0-9]+)>', rep_role, details)
        
        # 2. Replace <#ID> with #ChannelName
        def rep_chan(m):
            cid = m.group(1)
            return f"#{channel_map.get(cid, 'kanał-' + cid)}"
        details = re.sub(r'<#([0-9]+)>', rep_chan, details)
        
        # 3. Replace <@ID> or <@!ID>
        details = re.sub(r'<@!?([0-9]+)>', r'@użytkownik-\1', details)
        
        # 4. Handle raw IDs
        def rep_raw_id(m):
            raw_id = m.group(2)
            has_parens = m.group(1) is not None
            
            if raw_id in channel_map:
                ch_name = channel_map[raw_id]
                if clean_str(ch_name) in clean_str(details):
                    return ""
                return f"#{ch_name}"
                
            if raw_id in role_map:
                r_name = role_map[raw_id]
                if clean_str(r_name) in clean_str(details):
                    return ""
                return f"@{r_name}"
                
            if has_parens:
                return ""
            return raw_id
            
        details = re.sub(r'(\s*\(([0-9]{17,20})\))|([0-9]{17,20})', rep_raw_id, details)
        
        formatted_logs.append({
            'id': log.get('id'),
            'guild_id': log.get('guild_id'),
            'category': log.get('category'),
            'username': username,
            'user_id': user_id,
            'user_avatar': f"https://cdn.discordapp.com/embed/avatars/{int(user_id or 0) % 5}.png",
            'action_type': log.get('action'),
            'details': details,
            'created_at': log.get('timestamp')
        })
    audit_logs = formatted_logs
    # Awatar bota (bezpieczny fallback pobierany z Discorda)
    bot_avatar_url = get_bot_avatar_cached(server_id)

    # Pobieramy serwery użytkownika i bota dla navbara (server switcher)
    user_data = session.get('user')
    user_id = user_data.get('id') if user_data else None
    user_guilds_filtered = []
    user_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    if user_id:
        try:
            from run import _guilds_memory_cache
            from routes_dashboard import get_bot_guilds_cached
            
            user_guilds = _guilds_memory_cache.get(user_id, [])
            bot_guild_ids = get_bot_guilds_cached()
            
            for g in user_guilds:
                if (int(g.get('permissions', 0)) & 0x8) or g.get('owner'):
                    if str(g['id']) in bot_guild_ids:
                        user_guilds_filtered.append({
                            "id": str(g['id']),
                            "name": g['name'],
                            "icon": g.get('icon')
                        })
            
            if user_data:
                uid = user_data.get('id')
                av_hash = user_data.get('avatar')
                if uid and av_hash:
                    ext = 'gif' if av_hash.startswith('a_') else 'png'
                    user_avatar = f"https://cdn.discordapp.com/avatars/{uid}/{av_hash}.{ext}"
        except: pass

    # Obliczanie dni do końca premium
    days_left = None
    if main_settings.get('premium') and main_settings.get('premium_expiry'):
        try:
            from datetime import datetime
            expiry = datetime.strptime(main_settings['premium_expiry'], '%Y-%m-%d %H:%M')
            delta = expiry - datetime.now()
            days_left = max(0, delta.days)
        except: pass

    return render_template(
        'config.html',
        server_id=server_id,
        guild=guild,
        channels=channels,
        roles=roles,
        command_states=cmd_settings,
        main_settings=main_settings,
        role_counters=role_counters,
        audit_logs=audit_logs,
        bot_avatar_url=bot_avatar_url,
        user_guilds=user_guilds_filtered,
        user_avatar=user_avatar,
        user=user_data,
        days_left=days_left,
        bot_latency=bot_latency,
        member_count=guild['member_count']
    )



@config_bp.route('/api/<guild_id>/welcome', methods=['GET', 'POST'])
def api_welcome(guild_id):
    if request.method == 'GET':
        powitanie = get_welcome_configs(guild_id, 'powitanie')
        pozegnanie = get_welcome_configs(guild_id, 'pozegnanie')
        return jsonify({'powitanie': powitanie, 'pozegnanie': pozegnanie})

    # POST - Zapisywanie
    data = request.json
    config_id = data.get('id')
    config_type = data.get('type', 'powitanie')
    
    # Używamy bezpiecznej funkcji z database.py
    new_id = save_welcome_config(guild_id, config_type, data, config_id)
    
    if new_id:
        return jsonify({'success': True, 'id': new_id})
    return jsonify({'success': False, 'error': 'Błąd zapisu'}), 500

@config_bp.route('/api/<guild_id>/welcome_sync', methods=['POST'])
def api_welcome_sync(guild_id):
    from database import sync_welcome_configs
    data = request.json
    ok = sync_welcome_configs(guild_id, data)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/welcome/<int:config_id>', methods=['DELETE'])
def api_delete_welcome(guild_id, config_id):
    from database import delete_welcome_config
    ok = delete_welcome_config(guild_id, config_id)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/welcome/<int:config_id>/test', methods=['POST'])
def api_test_welcome(guild_id, config_id):
    # Pobierz config, aby wiedzieć czy to powitanie czy pożegnanie
    from database import get_welcome_configs
    cfg_pow = get_welcome_configs(guild_id, 'powitanie')
    cfg_poz = get_welcome_configs(guild_id, 'pozegnanie')
    
    cfg = next((c for c in cfg_pow if c['id'] == config_id), None)
    type = 'powitanie'
    if not cfg:
        cfg = next((c for c in cfg_poz if c['id'] == config_id), None)
        type = 'pozegnanie'
        
    if not cfg: return jsonify({'success': False, 'error': 'Nie znaleziono konfiguracji'}), 404
    
    result = call_bot_api("/test_welcome", method="POST", data={
        'guild_id': guild_id,
        'config_id': config_id,
        'type': type
    })
    
    if result: return jsonify(result)
    return jsonify({'success': False, 'error': 'Błąd komunikacji z botem'}), 500

@config_bp.route('/api/<guild_id>/premium/trial', methods=['POST'])
def api_premium_trial(guild_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Zaloguj się'})
    
    from database import get_settings
    settings = get_settings(guild_id)
    
    if settings.get('trial_used'):
        return jsonify({'success': False, 'error': 'Okres próbny został już wykorzystany na tym serwerze.'})
    
    from database import DB_NAME
    import sqlite3
    from datetime import datetime, timedelta
    
    expiry_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M')
    start_date = datetime.now().isoformat()

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''
            UPDATE settings SET 
                premium = 1, 
                trial_used = 1, 
                trial_start = ?, 
                premium_expiry = ?,
                subscription_type = 'Okres Próbny'
            WHERE guild_id = ?
        ''', (start_date, expiry_date, str(guild_id)))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@config_bp.route('/api/<guild_id>/channels')
def api_channels(guild_id):
    # Najpierw próbujemy z lokalnego API bota
    try:
        resp = requests.get(f"http://127.0.0.1:5006/guilds/{guild_id}/channels", timeout=1.0)
        if resp.status_code == 200:
            return jsonify(resp.json())
    except:
        pass

    # Fallback do bezpośredniego API Discorda
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    resp = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers)
    if resp.status_code == 200:
        all_channels = resp.json()
        channels = [{"id": str(c['id']), "name": c['name']} for c in all_channels if c['type'] in (0, 5)]
        return jsonify(channels)
    return jsonify([])

@config_bp.route('/api/<guild_id>/roles')
def api_roles(guild_id):
    # Najpierw próbujemy z lokalnego API bota
    try:
        resp = requests.get(f"http://127.0.0.1:5006/guilds/{guild_id}/roles", timeout=1.0)
        if resp.status_code == 200:
            return jsonify(resp.json())
    except:
        pass

    # Fallback do bezpośredniego API Discorda
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    resp = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=headers)
    if resp.status_code == 200:
        all_roles = resp.json()
        roles = []
        for r in all_roles:
            if r['name'] != "@everyone" and not r.get('managed'):
                color_int = r.get('color', 0)
                color_hex = f"#{color_int:06x}" if color_int != 0 else "#b5bac1"
                roles.append({"id": str(r['id']), "name": r['name'], "color": color_hex})
        return jsonify(roles)
    return jsonify([])


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@config_bp.route('/api/<guild_id>/upload_bg', methods=['POST'])
def api_upload_bg(guild_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Brak autoryzacji'}), 401

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Brak pliku'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nie wybrano pliku'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Niedozwolony format pliku. Dozwolone: PNG, JPG, GIF, WEBP'}), 400

    # Sprawdzamy rozmiar
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({'success': False, 'error': 'Plik jest za duży (max 5 MB)'}), 400

    try:
        # Generujemy unikalną nazwę pliku
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{guild_id}_{uuid.uuid4().hex[:8]}.{ext}"
        
        upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        url = f"/static/uploads/{filename}"
        return jsonify({'success': True, 'url': url})
    except Exception as e:
        print(f"❌ [UPLOAD] Błąd: {e}")
        return jsonify({'success': False, 'error': 'Błąd serwera podczas zapisu pliku'}), 500

@config_bp.route('/api/<guild_id>/autorole', methods=['POST'])
def api_save_autorole(guild_id):
    from database import save_autorole_settings, get_settings
    data = request.json
    
    # Pobieramy obecne ustawienia, aby nie nadpisać mode/restore_roles jeśli nie zostały przesłane
    current = get_settings(guild_id)
    
    mode = data.get('mode', current.get('autorole_mode', 'black'))
    restore_roles = data.get('restore_roles', current.get('autorole_roles', []))
    
    human_roles = data.get('human_roles', [])
    bot_roles = data.get('bot_roles', [])
    booster_roles = data.get('booster_roles', [])
    booster_remove = data.get('booster_remove', True)
    
    save_autorole_settings(guild_id, mode, restore_roles, human_roles, bot_roles, booster_roles, booster_remove)
    
    # Natychmiastowa synchronizacja boosterów przez API bota
    call_bot_api(f"/guilds/{guild_id}/sync_boosters", method="POST")
        
    return jsonify({'success': True})

@config_bp.route('/api/<guild_id>/counter', methods=['POST'])
def api_save_counter(guild_id):
    from database import save_counter_settings
    data = request.json
    type = data.get('type')
    enabled = data.get('enabled', False)
    name = data.get('name', '')
    thousands = data.get('thousands', False)
    save_counter_settings(guild_id, type, enabled, name, thousands)
    
    # Natychmiastowa aktualizacja licznika przez API bota
    call_bot_api(f"/guilds/{guild_id}/sync_counters", method="POST")
        
    return jsonify({'success': True})

@config_bp.route('/api/<guild_id>/role_counters', methods=['POST'])
def api_save_role_counter(guild_id):
    from database import save_role_counter
    data = request.json
    config_id = data.get('id')
    name = data.get('name')
    mode = data.get('mode', 'white')
    roles = data.get('roles', [])
    enabled = 1 if data.get('enabled', True) else 0
    
    success, result = save_role_counter(guild_id, config_id, name, mode, roles, enabled)
    if success:
        return jsonify({'success': True, 'id': result})
    else:
        return jsonify({'success': False, 'error': result}), 400

@config_bp.route('/api/<guild_id>/role_counters/<int:config_id>', methods=['DELETE'])
def api_delete_role_counter(guild_id, config_id):
    from database import get_role_counters, delete_role_counter
    # Znajdź channel_id przed usunięciem wiersza w bazie
    configs = get_role_counters(guild_id)
    cfg = next((c for c in configs if c['id'] == config_id), None)
    if cfg and cfg.get('channel_id'):
        ch_id = cfg['channel_id']
        if ch_id and str(ch_id).strip() != "None" and str(ch_id).isdigit():
            call_bot_api(f"/guilds/{guild_id}/delete_channel/{ch_id}", method="POST")
            
    ok = delete_role_counter(guild_id, config_id)
    if ok:
        call_bot_api(f"/guilds/{guild_id}/sync_counters", method="POST")
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/role_counters/sync', methods=['POST'])
def api_sync_role_counters(guild_id):
    from database import sync_role_counters
    data = request.json
    configs = data.get('configs', [])
    success, deleted_channel_ids = sync_role_counters(guild_id, configs)
    if success:
        # Usuń skasowane kanały na Discordzie
        for ch_id in deleted_channel_ids:
            call_bot_api(f"/guilds/{guild_id}/delete_channel/{ch_id}", method="POST")
            
        call_bot_api(f"/guilds/{guild_id}/sync_counters", method="POST")
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@config_bp.route('/api/<guild_id>/role_counters/<int:config_id>/sync', methods=['POST'])
def api_sync_single_role_counter(guild_id, config_id):
    call_bot_api(f"/guilds/{guild_id}/sync_counters", method="POST")
    return jsonify({'success': True})

# --- MEDIA / SOCIAL MEDIA ---
@config_bp.route('/api/<guild_id>/media', methods=['GET', 'POST'])
def api_media(guild_id):
    from database import get_media_configs, sync_media_configs
    if request.method == 'GET':
        configs = get_media_configs(guild_id)
        return jsonify(configs)

    # POST - Synchronizacja całej listy
    data = request.json
    configs = data.get('configs', [])
    
    result = sync_media_configs(guild_id, configs)
    # Obsługuje zarówno zwrot (bool, error) jak i sam bool
    if isinstance(result, tuple):
        ok, error = result
    else:
        ok, error = result, None
    
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': error or 'Błąd synchronizacji'}), 400

@config_bp.route('/api/<guild_id>/media/<int:config_id>', methods=['DELETE'])
def api_delete_media(guild_id, config_id):
    from database import delete_media_config
    ok = delete_media_config(guild_id, config_id)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/media/item', methods=['POST'])
def api_save_media_item(guild_id):
    from database import save_media_config
    data = request.json
    config_id = data.get('id')
    new_id = save_media_config(guild_id, data, config_id)
    return jsonify({'success': True, 'id': new_id})

@config_bp.route('/api/<guild_id>/embeds_sync', methods=['POST'])
def api_embeds_sync(guild_id):
    from database import sync_embed_configs, get_embed_configs
    data = request.json
    ok = sync_embed_configs(guild_id, data)
    
    if ok:
        # Powiadamiamy bota o wszystkich włączonych embedach
        configs = get_embed_configs(guild_id)
        for cfg in configs:
            if cfg.get('enabled', 1):
                call_bot_api("/send_embed", method="POST", data={
                    'guild_id': guild_id,
                    'config_id': cfg['id']
                })
                
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/embeds', methods=['GET', 'POST'])
def api_embeds(guild_id):
    from database import get_embed_configs, save_embed_config
    if request.method == 'GET':
        configs = get_embed_configs(guild_id)
        return jsonify(configs)
    
    data = request.json
    config_id = data.get('id')
    # Jeśli id jest długie (timestamp z frontendu), traktujemy jako NOWY
    if config_id and len(str(config_id)) > 10:
        config_id = None
        
    new_id = save_embed_config(guild_id, data, config_id)
    if new_id:
        call_bot_api("/send_embed", method="POST", data={
            'guild_id': guild_id,
            'config_id': config_id or new_id
        })
        return jsonify({'success': True, 'id': new_id})
    return jsonify({'success': False, 'error': 'Błąd zapisu'}), 500

@config_bp.route('/api/<guild_id>/embeds/<int:config_id>/test', methods=['POST'])
def api_embed_test(guild_id, config_id):
    ok = call_bot_api("/test_embed", method="POST", data={
        'guild_id': guild_id,
        'config_id': config_id
    })
    return jsonify({'success': ok})



# --- SELFROLE ---
@config_bp.route('/api/<guild_id>/selfrole', methods=['GET', 'POST'])
def api_selfrole(guild_id):
    from database import get_selfrole_configs, save_selfrole_config
    if request.method == 'GET':
        configs = get_selfrole_configs(guild_id)
        return jsonify(configs)
    
    data = request.json
    config_id = data.get('id')
    # Jeśli id jest długie (timestamp z frontendu), traktujemy jako NOWY
    if config_id and len(str(config_id)) > 10:
        config_id = None
        
    new_id = save_selfrole_config(guild_id, data, config_id)
    if new_id:
        # Powiadamiamy bota o zmianach
        call_bot_api("/send_selfrole", method="POST", data={
            'guild_id': guild_id,
            'config_id': config_id or new_id
        })
        return jsonify({'success': True, 'id': new_id})
    return jsonify({'success': False, 'error': 'Błąd zapisu'}), 500

@config_bp.route('/api/<guild_id>/selfrole/sync', methods=['POST'])
def api_sync_selfrole(guild_id):
    from database import sync_selfrole_configs, get_selfrole_configs
    data = request.json
    ok = sync_selfrole_configs(guild_id, data)
    
    if ok:
        # Powiadamiamy bota o zmianach, aby wysłał/zaktualizował panele
        configs = get_selfrole_configs(guild_id)
        for cfg in configs:
            if cfg.get('enabled', 1):
                call_bot_api("/send_selfrole", method="POST", data={
                    'guild_id': guild_id,
                    'config_id': cfg['id']
                })
                
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/selfrole/<int:config_id>', methods=['DELETE'])
def api_delete_selfrole(guild_id, config_id):
    # Potrzebujemy funkcji w database.py
    from database import delete_selfrole_config
    ok = delete_selfrole_config(guild_id, config_id)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/selfrole/<int:config_id>/sync', methods=['POST'])
def api_sync_single_selfrole(guild_id, config_id):
    call_bot_api("/send_selfrole", method="POST", data={
        'guild_id': guild_id,
        'config_id': config_id
    })
    return jsonify({'success': True})

@config_bp.route('/api/<guild_id>/activity', methods=['GET'])
def api_get_activity(guild_id):
    from database import get_activity_stats
    stats = get_activity_stats(guild_id)
    return jsonify(stats)

# --- WŁASNY BOT (WHITE LABEL) ---
@config_bp.route('/api/<guild_id>/custom_bot', methods=['GET'])
def api_get_custom_bot(guild_id):
    from database import get_custom_bot
    bot_data = get_custom_bot(guild_id)
    return jsonify(bot_data or {})

@config_bp.route('/api/<guild_id>/custom_bot/sync', methods=['POST'])
def api_sync_custom_bot(guild_id):
    from database import save_custom_bot
    data = request.json
    ok = save_custom_bot(
        guild_id, 
        data.get('token'), 
        data.get('bot_name'), 
        data.get('enabled', False)
    )
    if ok:
        g_id_str = str(guild_id)
        if g_id_str in _bot_avatar_cache:
            del _bot_avatar_cache[g_id_str]
    return jsonify({'success': ok})

# --- WEBHOOKS (Stripe/PayPal) ---
@config_bp.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Automatyczna aktywacja premium po otrzymaniu sygnału ze Stripe."""
    payload = request.get_data()
    sig_header = request.environ.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return jsonify({'error': 'Invalid signature'}), 400

    # Obsługa zdarzenia zakończenia płatności
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        guild_id = session_obj.get('metadata', {}).get('guild_id')
        
        if guild_id:
            from database import set_premium
            set_premium(guild_id, True)
            print(f"✅ [STRIPE] Aktywowano Premium dla serwera: {guild_id}")
            return jsonify({'status': 'success', 'message': 'Premium activated'})
    
    return jsonify({'status': 'ignored'}), 200

@config_bp.route('/api/<server_id>/create-checkout-session', methods=['POST'])
def create_checkout_session(server_id):
    """Tworzy dynamiczną sesję Stripe Checkout."""
    if 'user' not in session:
        return jsonify({'error': 'Zaloguj się'}), 401
        
    try:
        # Wybór planu (na razie domyślny 15 PLN)
        plan_name = request.args.get('plan', 'PREMIUM')
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card', 'blik', 'p24', 'google_pay', 'paypal'],
            line_items=[{
                'price_data': {
                    'currency': 'pln',
                    'product_data': {
                        'name': f'PolskiBot {plan_name} - Serwer {server_id}',
                        'description': 'Dostęp do wszystkich zaawansowanych funkcji bota na 30 dni.',
                    },
                    'unit_amount': 1500, # 15.00 PLN w groszach
                },
                'quantity': 1,
            }],
            mode='payment',
            metadata={'guild_id': server_id}, # Przekazujemy ID serwera do webhooka
            success_url=url_for('config.config', server_id=server_id, _external=True) + '?payment=success',
            cancel_url=url_for('config.config', server_id=server_id, _external=True) + '?payment=cancel',
        )
        return jsonify({'url': checkout_session.url})
    except Exception as e:
        print(f"❌ [STRIPE] Błąd tworzenia sesji: {e}")
        return jsonify({'error': str(e)}), 500

@config_bp.route('/api/<guild_id>/premium', methods=['POST'])
def api_set_premium(guild_id):
    from database import set_premium
    data = request.json
    status = data.get('status', False)
    ok = set_premium(guild_id, status)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/embeds/<int:config_id>', methods=['DELETE'])
def api_delete_embed(guild_id, config_id):
    from database import delete_embed_config
    ok = delete_embed_config(guild_id, config_id)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/embeds/<int:config_id>/sync', methods=['POST'])
def api_sync_single_embed(guild_id, config_id):
    call_bot_api("/send_embed", method="POST", data={
        'guild_id': guild_id,
        'config_id': config_id
    })
    return jsonify({'success': True})

@config_bp.route('/api/<guild_id>/logs', methods=['POST'])
def api_save_logs(guild_id):
    import sqlite3
    data = request.json
    
    update_data = {
        'logs_channel_id': data.get('channel_id'),
        'logs_join_leave': 1 if data.get('join_leave') else 0,
        'logs_mod_actions': 1 if data.get('mod_actions') else 0,
        'logs_role_updates': 1 if data.get('role_updates') else 0,
        'logs_voice_activity': 1 if data.get('voice_activity') else 0,
        'logs_guild_updates': 1 if data.get('guild_updates') else 0,
        'logs_msg_updates': 1 if data.get('msg_updates') else 0
    }
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    for key, val in update_data.items():
        cursor.execute(f"UPDATE settings SET {key} = ? WHERE guild_id = ?", (val, guild_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})
