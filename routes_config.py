import os
import uuid
import requests
import json
import time
import os
import json
import datetime

# Ścieżka do statusu (dla PythonAnywhere)
STATUS_FILE_PATH = "/home/BLADERUNNER009/AntigravityProjekt/bot_status.json"
if not os.path.exists("/home/BLADERUNNER009"):
    STATUS_FILE_PATH = "bot_status.json" # Fallback lokalny
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from base import BOT_TOKEN
from database import get_settings, save_settings, get_command_settings, save_command_settings, get_welcome_configs, save_welcome_config, delete_welcome_config, get_audit_logs
from werkzeug.utils import secure_filename

config_bp = Blueprint('config', __name__)

# --- WEWNĘTRZNA KOMUNIKACJA Z BOTEM ---
BOT_API_URL = "http://127.0.0.1:5006"
_bot_offline_cache = 0  # Timestamp ostatniej nieudanej próby

def call_bot_api(endpoint, method="GET", data=None):
    """Pomocnicza funkcja do komunikacji z wewnętrznym API bota."""
    global _bot_offline_cache
    import time
    import json
    import os
    
    # Jeśli bot był offline w ciągu ostatnich 5 sekund, nie próbuj ponownie (oszczędność czasu ładowania)
    if time.time() - _bot_offline_cache < 5:
        return None

    # Zawsze przy POST tworzymy sygnał plikowy (dla PythonAnywhere)
    if method == "POST":
        try:
            guild_id = endpoint.split('/')[2] if '/guilds/' in endpoint else None
            if guild_id:
                with open(f"sync_needed_{guild_id}.json", "w") as f:
                    json.dump({"endpoint": endpoint, "time": time.time(), "data": data}, f)
        except: pass

    try:
        url = f"{BOT_API_URL}{endpoint}"
        if method == "GET":
            resp = requests.get(url, timeout=1.5)
        else:
            resp = requests.post(url, json=data, timeout=1.5)
        
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        _bot_offline_cache = time.time()
    return None

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
        
        rgb_mode = data.get('rgb_mode', 0)
        enabled_cmds = data.get('commands', [])
        
        # Zapisujemy prefix, język, kolory i moderację + automod
        save_settings(server_id, True, mod_enabled, True, prefix, language, embed_color, rgb_mode, mod_confirm, am_antilink, am_anticaps, am_antispam, am_badwords, am_badwords_list)
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

    # Pobieramy kanały
    channels_resp = requests.get(f"https://discord.com/api/v10/guilds/{server_id}/channels", headers=headers)
    all_channels = channels_resp.json() if channels_resp.status_code == 200 else []
    channels = [{"id": str(c['id']), "name": c['name']} for c in all_channels if c['type'] == 0] # Tylko tekstowe
    
    # Pobieramy role
    roles_resp = requests.get(f"https://discord.com/api/v10/guilds/{server_id}/roles", headers=headers)
    all_roles = roles_resp.json() if roles_resp.status_code == 200 else []
    roles = []
    for r in all_roles:
        if r['name'] != "@everyone" and not r.get('managed'):
            # Konwersja koloru z int na hex
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
        "member_count": guild_data.get('approximate_member_count') or guild_data.get('member_count', 0),
        "owner_id": guild_data.get('owner_id')
    }
    
    # Pobieramy stan komend i ustawienia (w tym prefix)
    cmd_settings = get_command_settings(server_id)
    main_settings = get_settings(server_id)
    from database import get_role_counters
    role_counters = get_role_counters(server_id)
    audit_logs = get_audit_logs(server_id)
    # Awatar bota (bezpieczny fallback)
    bot_avatar_url = "/static/img/default_avatar.png"

    # Pobieramy serwery użytkownika i bota dla navbara (server switcher)
    user_data = session.get('user')
    access_token = session.get('access_token')
    user_guilds_filtered = []
    user_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    if access_token:
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=headers, timeout=5)
            if resp.status_code == 200:
                user_guilds = resp.json()
                bot_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
                bot_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=bot_headers, timeout=5)
                bot_guild_ids = {str(g['id']) for g in bot_resp.json()} if bot_resp.status_code == 200 else set()
                
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

@config_bp.route('/config/<server_id>/checkout')
def checkout(server_id):
    if 'user' not in session:
        return redirect(url_for('home.index'))
    
    plan_name = request.args.get('plan', 'MIESIĘCZNY')
    plan_price = request.args.get('price', '15.00')
    
    from database import get_settings
    main_settings = get_settings(server_id)
    
    return render_template(
        'glowne/checkout.html',
        server_id=server_id,
        plan_name=plan_name,
        plan_price=plan_price,
        main_settings=main_settings
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
    channels = call_bot_api(f"/guilds/{guild_id}/channels")
    return jsonify(channels or [])

@config_bp.route('/api/<guild_id>/roles')
def api_roles(guild_id):
    roles = call_bot_api(f"/guilds/{guild_id}/roles")
    return jsonify(roles or [])

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

@config_bp.route('/api/<guild_id>/role_counters/sync', methods=['POST'])
def api_sync_role_counters(guild_id):
    from database import sync_role_counters, get_role_counters
    data = request.json
    configs = data.get('configs', [])
    
    # KROK 1: Wykrycie "osieroconych" kanałów, zanim wyczyścimy bazę
    old_configs = get_role_counters(guild_id)
    new_ids = [str(c.get('id')) for c in configs]
    orphans = []
    
    for oc in old_configs:
        ch_id = str(oc.get('channel_id'))
        # Jeśli starego ID licznika nie ma na nowej liście i posiadał kanał
        if str(oc['id']) not in new_ids and ch_id and ch_id.strip() and ch_id != "None":
            orphans.append(ch_id)
            
    # KROK 2: Synchronizacja bazy danych
    if sync_role_counters(guild_id, configs):
        # Aktualizacja liczników przez API bota
        call_bot_api(f"/guilds/{guild_id}/sync_counters", method="POST")
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Błąd synchronizacji ról'}), 400

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

@config_bp.route('/api/<guild_id>/embeds_sync', methods=['POST'])
def api_embeds_sync(guild_id):
    from database import sync_embed_configs
    data = request.json
    ok = sync_embed_configs(guild_id, data)
    return jsonify({'success': ok})

@config_bp.route('/api/<guild_id>/embeds', methods=['GET', 'POST'])
def api_embeds(guild_id):
    from database import get_embed_configs, save_embed_config
    if request.method == 'GET':
        configs = get_embed_configs(guild_id)
        return jsonify(configs)

    # POST - Zapisywanie jednej konfiguracji
    data = request.json
    config_id = data.get('id')
    
    new_id = save_embed_config(guild_id, data, config_id)
    
    if new_id:
        # Powiadamiamy bota o nowym embedzie
        call_bot_api("/send_embed", method="POST", data={
            'guild_id': guild_id,
            'config_id': config_id or new_id
        })
        return jsonify({'success': True, 'id': new_id})
    return jsonify({'success': False, 'error': 'Błąd zapisu'}), 500



# --- SELFROLE ---
@config_bp.route('/api/<guild_id>/selfrole', methods=['GET'])
def api_get_selfrole(guild_id):
    from database import get_selfrole_configs
    configs = get_selfrole_configs(guild_id)
    return jsonify(configs)

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
    return jsonify({'success': ok})

# --- WEBHOOKS (Stripe/PayPal) ---
@config_bp.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Placeholder dla automatycznej aktywacji po płatności."""
    # W realnym systemie tutaj sprawdzamy sygnaturę Stripe
    data = request.json
    guild_id = data.get('guild_id') # Przekazane w metadata sesji Stripe
    event_type = data.get('type')
    
    if event_type == 'checkout.session.completed' and guild_id:
        from database import set_premium
        set_premium(guild_id, True)
        return jsonify({'status': 'success', 'message': 'Premium activated via webhook'})
    
    return jsonify({'status': 'ignored'}), 200

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
