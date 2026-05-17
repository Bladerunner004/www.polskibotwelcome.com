import datetime
import os
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

app.secret_key = os.getenv("FLASK_SECRET", "polskibot-fixed-key-12345")

# Wykrywanie środowiska developerskiego (lokalnego na Windowsie lub z localhost w URI)
import sys
redirect_uri_val = os.getenv("DISCORD_REDIRECT_URI", "")
is_local_dev = (sys.platform == 'win32') or ("127.0.0.1" in redirect_uri_val) or ("localhost" in redirect_uri_val)

app.config.update(
    SESSION_COOKIE_NAME='polskibot_session',
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not is_local_dev, # Wyłączone dla localhost na HTTP, włączone dla HTTPS (produkcja)
    PERMANENT_SESSION_LIFETIME=604800,
    PREFERRED_URL_SCHEME='http' if is_local_dev else 'https',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024 # 16MB limit
)

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
    if not code: return redirect(url_for('home.index'))

    print(f"🔗 [AUTH] Próba logowania. Redirect URI: {REDIRECT_URI}")
    
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
        print(f"📩 [AUTH] Status odpowiedzi Discord: {token_resp.status_code}")
        token_data = token_resp.json()
        
        # Zapis diagnostyczny logowania do pliku
        import datetime
        with open("auth_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now()}] callback() start:\n")
            f.write(f"  Code: {code[:10] if code else 'None'}...\n")
            f.write(f"  Redirect URI: {REDIRECT_URI}\n")
            f.write(f"  Status odpowiedzi Discord: {token_resp.status_code}\n")
            f.write(f"  Dane odpowiedzi: {token_data}\n")
            
        if token_resp.status_code != 200:
            print(f"⚠️ [AUTH] Błąd od Discorda: {token_data}")
            return redirect(url_for('home.index'))
            
        access_token = token_data.get('access_token')

        user_resp = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        user_data = user_resp.json()
        print(f"👤 [AUTH] Zalogowano użytkownika: {user_data.get('username')} (ID: {user_data.get('id')})")
        
        with open("auth_debug.log", "a", encoding="utf-8") as f:
            f.write(f"  Zalogowano użytkownika: {user_data.get('username')} (ID: {user_data.get('id')})\n")

        # Pobieramy serwery
        guilds_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
        all_guilds = guilds_resp.json() if guilds_resp.status_code == 200 else []
        print(f"📊 [AUTH] Pobrano {len(all_guilds)} serwerów")
        
        # Filtrujemy serwery (admin/owner)
        managed_guilds = [g for g in all_guilds if (int(g.get('permissions', 0)) & 0x8) == 0x8 or g.get('owner')]

        session.permanent = True
        session['user'] = {'id': user_data['id'], 'username': user_data['username'], 'avatar': user_data['avatar']}
        session['user_avatar'] = get_user_avatar(session['user'])
        session['user_guilds'] = managed_guilds
        session['access_token'] = access_token
        session.modified = True # Wymuszamy zapis sesji
        
        print("✅ [AUTH] Sesja zapisana. Przekierowuję do dashboardu.")
        return redirect(url_for('dashboard.dashboard'))
    except Exception as e:
        print(f"❌ [AUTH] Błąd krytyczny: {e}")
        import traceback
        with open("auth_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now()}] Błąd krytyczny: {e}\n")
            f.write(traceback.format_exc() + "\n")
        traceback.print_exc()
        return redirect(url_for('home.index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home.index'))

if __name__ == '__main__':
    app.run(port=5000)