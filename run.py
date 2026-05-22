import sys
import io
# Wymuszenie kodowania UTF-8 dla konsoli Windows, aby zapobiec crashom przy printowaniu emoji (np. 🔗)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import datetime
import os
import time
import requests
import threading
import asyncio
import socket
from flask import Flask, session, redirect, url_for, request, jsonify
from dotenv import load_dotenv

# Importujemy dane konfiguracyjne z base.py
from base import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, get_user_avatar, DISCORD_INVITE_URL, get_login_url

# Importujemy Blueprinty
from routes_home import home_bp
from routes_dashboard import dashboard_bp
from routes_config import config_bp

from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# Fix dla PythonAnywhere (HTTPS przez Proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Custom Prefix Middleware dla proxy podścieżki Serveo
class ServeoPrefixMiddleware:
    def __init__(self, wsgi_app, prefix):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        redirect_uri_val = os.getenv("DISCORD_REDIRECT_URI", "")
        if "serveousercontent.com" in redirect_uri_val:
            environ['SCRIPT_NAME'] = self.prefix
            path = environ.get('PATH_INFO', '')
            if path.startswith(self.prefix):
                environ['PATH_INFO'] = path[len(self.prefix):]
        return self.wsgi_app(environ, start_response)

app.wsgi_app = ServeoPrefixMiddleware(app.wsgi_app, '/apps/POLSKIBOT.com')

app.secret_key = os.getenv("FLASK_SECRET", "polskibot-fixed-key-12345")

# Wykrywanie środowiska developerskiego (lokalnego bez tunelu HTTPS)
redirect_uri_val = os.getenv("DISCORD_REDIRECT_URI", "")
is_pythonanywhere = "pythonanywhere.com" in redirect_uri_val
is_local_dev = ("127.0.0.1" in redirect_uri_val) or ("localhost" in redirect_uri_val)

app.config.update(
    SESSION_COOKIE_NAME='polskibot_session',
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_PATH='/',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not is_local_dev,
    PERMANENT_SESSION_LIFETIME=604800,
    PREFERRED_URL_SCHEME='http' if is_local_dev else 'https',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)

# --- PAMIĘĆ PODRĘCZNA SERWERÓW (zamiast cookie, brak limitu 4KB) ---
# Słownik: user_id -> lista serwerów. Przechowywany w pamięci procesu.
_guilds_memory_cache = {}

@app.before_request
def refresh_discord_cache():
    # Pomijamy pliki statyczne, webhooki i żądania API bota
    if request.path.startswith('/static/') or request.path.startswith('/webhook/'):
        return
        
    if 'user' not in session or 'access_token' not in session:
        return
        
    user_id = session['user'].get('id')
    if not user_id:
        return
        
    now = time.time()
    last_refresh = session.get('last_profile_refresh', 0)
    
    # Odświeżamy co 5 minut (300 sekund) lub gdy w URL jest refresh=true
    force_refresh = request.args.get('refresh') == 'true'
    
    if force_refresh or (now - last_refresh > 300):
        access_token = session['access_token']
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # 1. Odświeżenie profilu użytkownika (avatar, username itp.)
        try:
            user_resp = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=5)
            if user_resp.status_code == 200:
                user_data = user_resp.json()
                session['user'] = {
                    'id': user_data.get('id'),
                    'username': user_data.get('username'),
                    'avatar': user_data.get('avatar')
                }
                session['user_avatar'] = get_user_avatar(session['user'])
                session.modified = True
                print(f"👤 [REFRESH] Zaktualizowano profil użytkownika {user_id}")
            elif user_resp.status_code == 401:
                # Token wygasł lub został cofnięty
                print(f"⚠️ [REFRESH] Token nieautoryzowany dla {user_id}. Czyszczenie sesji.")
                session.clear()
                return
        except Exception as e:
            print(f"❌ [REFRESH] Błąd podczas odświeżania profilu: {e}")
            
        # 2. Odświeżenie listy serwerów użytkownika (nazwy, ikony, uprawnienia)
        try:
            guilds_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=headers, timeout=5)
            if guilds_resp.status_code == 200:
                all_guilds = guilds_resp.json()
                managed_guilds = []
                for g in all_guilds:
                    is_admin = (int(g.get('permissions', 0)) & 0x8) == 0x8 or g.get('owner')
                    if is_admin:
                        managed_guilds.append({
                            'id': g.get('id'),
                            'name': g.get('name'),
                            'icon': g.get('icon'),
                            'permissions': g.get('permissions'),
                            'owner': g.get('owner')
                        })
                _guilds_memory_cache[user_id] = managed_guilds
                print(f"💾 [REFRESH] Zaktualizowano {len(managed_guilds)} serwerów dla {user_id}")
            elif guilds_resp.status_code == 401:
                session.clear()
                return
        except Exception as e:
            print(f"❌ [REFRESH] Błąd podczas odświeżania serwerów: {e}")
            
        session['last_profile_refresh'] = now
        session.modified = True

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    return response

# --- KONTEKST GLOBALNY ---
@app.context_processor
def inject_global_vars():
    user = session.get('user')
    # Używamy user_avatar zapisanego w sesji lub generujemy go na bieżąco
    avatar = session.get('user_avatar') or (get_user_avatar(user) if user else None)
    
    return {
        'user': user,
        'user_avatar': avatar,
        'user_guilds': _guilds_memory_cache.get(user.get('id') if user else None, []),
        'login_url': get_login_url(),
        'discord_invite': DISCORD_INVITE_URL
    }

app.register_blueprint(home_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(config_bp)

# --- AUTOMATYCZNE BUDZENIE BOTA ---
def start_bot_background():
    """Uruchamia bota w osobnym procesie, aby nie blokować serwera WWW."""
    import subprocess
    import sys
    
    # Wybór właściwego interpretera Python (virtualenv ma pierwszeństwo na PythonAnywhere)
    venv_python = os.path.expanduser("~/.virtualenvs/venv_bot/bin/python")
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable
    
    # Próba zajęcia portu 5005 - jeśli się uda, to ten worker odpala proces bota
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 5005))
        # Nie zamykamy gniazda - trzymamy je jako blokadę (Single Instance)
        
        print(f"[SYSTEM] Uruchamiam proces bota w tle... (Python: {python_exe})")
        log_path = os.path.join(bot_dir, "bot_error.log")
        with open(log_path, "a") as f:
            f.write(f"\n--- START BOT {datetime.datetime.now()} (Python: {python_exe}) ---\n")
            subprocess.Popen(
                [python_exe, os.path.join(bot_dir, "bot.py")],
                stdout=f,
                stderr=f,
                cwd=bot_dir,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
    except socket.error:
        # Bot już prawdopodobnie działa w innym procesie
        pass
    except Exception as e:
        print(f"[SYSTEM] Błąd startu bota: {e}")

# Uruchamiamy bota przy starcie aplikacji (tylko jeśli nie jesteśmy w reloaderze Flaska)
if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
    start_bot_background()

@app.route('/callback')
def callback():
    code = request.args.get('code')
    guild_id = request.args.get('guild_id')

    # Zapis logowania/diagnostyki zaproszenia
    import datetime
    with open("auth_debug.log", "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.datetime.now()}] callback() start:\n")
        f.write(f"  Code: {code[:10] if code else 'None'}...\n")
        f.write(f"  Guild ID: {guild_id if guild_id else 'None'}\n")
        f.write(f"  Redirect URI: {REDIRECT_URI}\n")

    # Jeśli jest code, to zawsze wymieniamy go na token, aby zalogować użytkownika / zsynchronizować jego serwery!
    if code:
        print(f"🔗 [AUTH] Wymiana kodu w callback. Redirect URI: {REDIRECT_URI}")
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'scope': 'identify guilds'
        }
        try:
            token_resp = requests.post("https://discord.com/api/v10/oauth2/token", data=data, timeout=10)
            token_data = token_resp.json()
            
            with open("auth_debug.log", "a", encoding="utf-8") as f:
                f.write(f"  Status tokena: {token_resp.status_code}\n")
                f.write(f"  Token dane: {token_data}\n")

            if token_resp.status_code == 200:
                access_token = token_data.get('access_token')
                user_resp = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
                user_data = user_resp.json()
                print(f"👤 [AUTH] Zalogowano użytkownika: {user_data.get('username')} (ID: {user_data.get('id')})")

                # Pobieramy najświeższe serwery użytkownika z Discorda
                guilds_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
                all_guilds = guilds_resp.json() if guilds_resp.status_code == 200 else []
                print(f"📊 [AUTH] Pobrano {len(all_guilds)} serwerów użytkownika")
                
                # Filtrujemy i optymalizujemy serwery (admin/owner), aby zapobiec przepełnieniu ciasteczka sesji (limit 4KB)
                managed_guilds = []
                for g in all_guilds:
                    is_admin = (int(g.get('permissions', 0)) & 0x8) == 0x8 or g.get('owner')
                    if is_admin:
                        managed_guilds.append({
                            'id': g.get('id'),
                            'name': g.get('name'),
                            'icon': g.get('icon'),
                            'permissions': g.get('permissions'),
                            'owner': g.get('owner')
                        })

                user_id = user_data['id']
                session.permanent = True
                session['user'] = {'id': user_id, 'username': user_data['username'], 'avatar': user_data['avatar']}
                session['user_avatar'] = get_user_avatar(session['user'])
                session['access_token'] = access_token
                session['last_profile_refresh'] = time.time()
                session.modified = True

                # Zapisujemy serwery w pamięci procesu (nie w cookie!) - brak limitu 4KB
                # _guilds_memory_cache is a global variable in this module
                _guilds_memory_cache[user_id] = managed_guilds
                print(f"💾 [AUTH] Zapisano {len(managed_guilds)} serwerów w pamięci (user: {user_id})")
            else:
                print(f"⚠️ [AUTH] Błąd tokena: {token_data}")
        except Exception as e:
            print(f"❌ [AUTH] Błąd krytyczny przy wymianie tokena: {e}")
            with open("auth_debug.log", "a", encoding="utf-8") as f:
                f.write(f"  Blad krytyczny tokena: {e}\n")

    # Obsługa dodania bota (powrót z zaproszenia bota na serwer)
    if guild_id:
        print(f"🤖 [BOT INVITE] Bot został pomyślnie dodany do serwera o ID: {guild_id}")
        
        # Resetujemy natychmiast cache serwerów bota
        from routes_dashboard import clear_bot_guilds_cache
        clear_bot_guilds_cache()

        # Czyścimy cache serwerów użytkownika żeby wymusić świeże pobranie
        if 'user' in session:
            uid = session['user'].get('id')
            if uid and uid in _guilds_memory_cache:
                del _guilds_memory_cache[uid]
        
        # Jeżeli użytkownik jest poprawnie zalogowany, sprawdźmy czy ma prawa do tego serwera
        if 'user' in session:
            uid = session['user'].get('id')
            user_guilds = _guilds_memory_cache.get(uid, [])
            if not user_guilds and session.get('access_token'):
                try:
                    g_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"})
                    if g_resp.status_code == 200:
                        user_guilds = [g for g in g_resp.json() if (int(g.get('permissions', 0)) & 0x8) == 0x8 or g.get('owner')]
                        if uid:
                            _guilds_memory_cache[uid] = user_guilds
                except: pass
            
            has_access = any(str(g.get('id')) == str(guild_id) for g in user_guilds)
            if has_access:
                print(f"🚀 [BOT INVITE] Użytkownik posiada uprawnienia! Przekierowanie bezpośrednio do /config/{guild_id}")
                return redirect(url_for('config.config', server_id=guild_id))
        
        return redirect(url_for('dashboard.dashboard'))

    # Jeśli to standardowe logowanie (bez guild_id)
    if 'user' in session:
        print("✅ [AUTH] Pomyślne logowanie standardowe. Przekierowuję do dashboardu.")
        return redirect(url_for('dashboard.dashboard'))
        
    return redirect(url_for('home.index'))

@app.route('/dev_login')
def dev_login():
    session['user'] = {
        'id': '1234567890',
        'username': 'PolskiBotDev',
        'avatar': 'a_1234567890abcdef'
    }
    session['access_token'] = 'mock_token'
    _guilds_memory_cache['1234567890'] = [
        {
            'id': '1489771395163623527',
            'name': 'Testowy Serwer PolskiBot',
            'permissions': 8,
            'owner': True,
            'icon': None
        }
    ]
    session.modified = True
    return redirect(url_for('dashboard.dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home.index'))

@app.route('/debug_auth')
def debug_auth():
    from base import BOT_TOKEN, CLIENT_ID, REDIRECT_URI
    import requests
    
    debug_info = {
        "env": {
            "DISCORD_CLIENT_ID": CLIENT_ID,
            "DISCORD_REDIRECT_URI": REDIRECT_URI,
            "BOT_TOKEN_SET": BOT_TOKEN is not None and len(BOT_TOKEN) > 0,
            "BOT_TOKEN_LEN": len(BOT_TOKEN) if BOT_TOKEN else 0,
            "BOT_TOKEN_START": BOT_TOKEN[:15] if BOT_TOKEN else "None"
        },
        "session": {
            "user": session.get('user'),
            "has_access_token": 'access_token' in session
        },
        "cache": {
            "cache_keys": list(_guilds_memory_cache.keys()),
            "user_guilds_in_cache": _guilds_memory_cache.get(session.get('user', {}).get('id')) if session.get('user') else None
        }
    }
    
    if BOT_TOKEN:
        # Sprawdzanie pliku bot_status.json
        import time
        import json
        status_file_info = {}
        status_path = "bot_status.json"
        if os.path.exists(status_path):
            status_file_info["exists"] = True
            status_file_info["path"] = os.path.abspath(status_path)
            status_file_info["mtime"] = os.path.getmtime(status_path)
            status_file_info["mtime_ago_sec"] = time.time() - os.path.getmtime(status_path)
            try:
                with open(status_path, "r") as f:
                    status_file_info["content"] = json.load(f)
            except Exception as e:
                status_file_info["error"] = str(e)
        else:
            status_file_info["exists"] = False
            status_file_info["path"] = os.path.abspath(status_path)
            
        debug_info["bot_status_file"] = status_file_info

        # Sprawdzanie lokalnego API bota
        local_api_info = {}
        try:
            resp_local = requests.get("http://127.0.0.1:5006/latency", timeout=1.0)
            local_api_info["status_code"] = resp_local.status_code
            if resp_local.status_code == 200:
                local_api_info["response"] = resp_local.json()
        except Exception as e:
            local_api_info["error"] = str(e)
        debug_info["local_bot_api"] = local_api_info

        try:
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get("https://discord.com/api/v10/users/@me/guilds?limit=200", headers=headers, timeout=5)
            debug_info["bot_api_test"] = {
                "status_code": resp.status_code,
                "guilds_count": len(resp.json()) if resp.status_code == 200 else None,
                "error_response": resp.text if resp.status_code != 200 else None
            }
            if resp.status_code == 200:
                debug_info["bot_api_test"]["guilds_list"] = [
                    {"id": g["id"], "name": g["name"]} for g in resp.json()
                ]
        except Exception as e:
            debug_info["bot_api_test"] = {
                "error": str(e)
            }
    else:
        debug_info["bot_api_test"] = "BOT_TOKEN is missing"
        
    return jsonify(debug_info)

if __name__ == '__main__':
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    print(f"[SYSTEM] Uruchamiam Flask na {host}:{port}")
    app.run(host=host, port=port)