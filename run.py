import sys
import io
# Wymuszenie kodowania UTF-8 dla konsoli Windows, aby zapobiec crashom przy printowaniu emoji (np. 🔗)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import datetime
import os
import requests
import threading
import asyncio
import socket
from flask import Flask, session, redirect, url_for, request, jsonify
from flask_session import Session
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
    SESSION_COOKIE_NAME='polskibot_sid',
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_PATH='/',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not is_local_dev,
    PERMANENT_SESSION_LIFETIME=604800,
    PREFERRED_URL_SCHEME='http' if is_local_dev else 'https',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    # --- FLASK-SESSION: sesje po stronie serwera (brak limitu 4KB ciasteczka) ---
    SESSION_TYPE='filesystem',
    SESSION_FILE_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_sessions'),
    SESSION_FILE_THRESHOLD=500,
    SESSION_PERMANENT=True,
    SESSION_USE_SIGNER=True,
)

# Tworzymy folder na pliki sesji i inicjalizujemy Flask-Session
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_sessions'), exist_ok=True)
Session(app)

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
        'user_guilds': session.get('user_guilds', []), # Pobieramy z sesji (stabilność)
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

                session.permanent = True
                session['user'] = {'id': user_data['id'], 'username': user_data['username'], 'avatar': user_data['avatar']}
                session['user_avatar'] = get_user_avatar(session['user'])
                session['user_guilds'] = managed_guilds
                session['access_token'] = access_token
                session.modified = True
            else:
                print(f"⚠️ [AUTH] Błąd tokena: {token_data}")
        except Exception as e:
            print(f"❌ [AUTH] Błąd krytyczny przy wymianie tokena: {e}")
            with open("auth_debug.log", "a", encoding="utf-8") as f:
                f.write(f"  Blad krytyczny tokena: {e}\n")

    # Obsługa dodania bota (powrót z zaproszenia bota na serwer)
    if guild_id:
        print(f"🤖 [BOT INVITE] Bot został pomyślnie dodany do serwera o ID: {guild_id}")
        
        # Resetujemy natychmiast cache serwerów bota na podstronie dashboardu!
        import routes_dashboard
        routes_dashboard._bot_guilds_last_update = 0
        session.pop('user_guilds', None) # Wyczyszczenie starej listy serwerów sesji, by wymusić świeże pobranie z Discorda
        
        # Jeżeli użytkownik jest poprawnie zalogowany, sprawdźmy czy ma prawa do tego serwera
        if 'user' in session:
            user_guilds = session.get('user_guilds') or []
            if not user_guilds and session.get('access_token'):
                try:
                    # Pobieramy awaryjnie w locie jeśli go nie było w sesji
                    g_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"})
                    if g_resp.status_code == 200:
                        user_guilds = [g for g in g_resp.json() if (int(g.get('permissions', 0)) & 0x8) == 0x8 or g.get('owner')]
                        session['user_guilds'] = user_guilds
                        session.modified = True
                except: pass
            
            has_access = any(str(g.get('id')) == str(guild_id) for g in user_guilds)
            if has_access:
                print(f"🚀 [BOT INVITE] Użytkownik posiada uprawnienia! Przekierowanie bezpośrednie do /config/{guild_id}")
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
    session['user_guilds'] = [
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

if __name__ == '__main__':
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    print(f"[SYSTEM] Uruchamiam Flask na {host}:{port}")
    app.run(host=host, port=port)