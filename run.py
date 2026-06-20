import sys
import io
import builtins

# Wymuszenie kodowania UTF-8 dla konsoli Windows, aby zapobiec crashom przy printowaniu emoji (np. 🔗)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Wymuszenie natychmiastowego wypisywania logów (wyłączenie buforowania stdout pod uWSGI)
_orig_print = builtins.print
def unbuffered_print(*args, **kwargs):
    kwargs['flush'] = True
    _orig_print(*args, **kwargs)
builtins.print = unbuffered_print


import datetime
import os
import time
import requests
import threading
import asyncio
import socket
from flask import Flask, session, redirect, url_for, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# Importujemy dane konfiguracyjne z base.py
from base import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, get_user_avatar, DISCORD_INVITE_URL, get_login_url

# Importujemy Blueprinty
from routes_home import home_bp
from routes_dashboard import dashboard_bp
from routes_config import config_bp

from werkzeug.middleware.proxy_fix import ProxyFix

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

_lock_socket = None
_bot_started = False

@app.before_request
def start_bot_on_first_request():
    global _bot_started
    if not _bot_started:
        _bot_started = True
        is_under_uwsgi = 'uwsgi' in sys.modules
        if is_under_uwsgi:
            start_bot_background()

# --- PAMIĘĆ PODRĘCZNA SERWERÓW (zamiast cookie, brak limitu 4KB) ---
# Słownik: user_id -> lista serwerów. Przechowywany w pamięci procesu.
from base import _guilds_memory_cache

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
    
    # Odświeżamy co 60 sekund lub gdy w URL jest refresh=true
    force_refresh = request.args.get('refresh') == 'true'
    
    if force_refresh:
        try:
            from routes_config import _bot_avatar_cache
            _bot_avatar_cache.clear()
            print("🧹 [REFRESH] Wyczyszczono cache awatarów botów (_bot_avatar_cache)")
        except Exception as e:
            print(f"❌ [REFRESH] Błąd czyszczenia cache awatarów botów: {e}")
            
        try:
            from routes_dashboard import clear_bot_guilds_cache
            clear_bot_guilds_cache()
            print("🧹 [REFRESH] Wyczyszczono cache serwerów bota (bot_guilds_cache.json)")
        except Exception as e:
            print(f"❌ [REFRESH] Błąd czyszczenia cache serwerów bota: {e}")
            
    if force_refresh or (now - last_refresh > 60):
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

@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ('pl', 'en'):
        session['lang'] = lang
    ref = request.referrer or '/'
    return redirect(ref)

# --- KONTEKST GLOBALNY ---
@app.context_processor
def inject_global_vars():
    user = session.get('user')
    avatar = session.get('user_avatar') or (get_user_avatar(user) if user else None)
    
    from utils.translations import translate
    lang = session.get('lang', 'pl')
    
    return {
        'user': user,
        'user_avatar': avatar,
        'user_guilds': _guilds_memory_cache.get(user.get('id') if user else None, []),
        'login_url': get_login_url(),
        'discord_invite': DISCORD_INVITE_URL,
        'current_lang': lang,
        '_': lambda key: translate(key, lang)
    }

app.register_blueprint(home_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(config_bp)

# --- AUTOMATYCZNE BUDZENIE BOTA ---
def start_bot_background():
    """Uruchamia bota w osobnym procesie i monitoruje go w tle przed crash-loopami."""
    global _lock_socket
    import subprocess
    import sys
    import threading
    import json
    
    # Wybór właściwego interpretera Python (virtualenv ma pierwszeństwo na PythonAnywhere)
    venv_python = os.path.expanduser("~/.virtualenvs/venv_bot/bin/python")
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable
    
    # Próba zajęcia portu 5005 - jeśli się uda, to ten worker odpala proces bota i monitoruje go
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(('127.0.0.1', 5005))
        # Nie zamykamy gniazda - trzymamy je jako blokadę (Single Instance)
        
        def monitor_bot():
            consecutive_failures = 0
            max_failures = 5
            quick_crash_threshold = 30  # sekundy
            last_env_mtime = 0
            env_path = os.path.join(bot_dir, ".env")
            
            while True:
                # Sprawdzamy czy plik .env został zmodyfikowany
                env_modified = False
                if os.path.exists(env_path):
                    try:
                        mtime = os.path.getmtime(env_path)
                        if mtime > last_env_mtime:
                            last_env_mtime = mtime
                            env_modified = True
                    except Exception as e:
                        print(f"[MONITOR] Błąd odczytu mtime .env: {e}")
                
                if env_modified:
                    print("[MONITOR] Wykryto zmianę w pliku .env, przeładowuję zmienne i resetuję licznik awarii.")
                    consecutive_failures = 0
                    try:
                        load_dotenv(env_path, override=True)
                    except Exception as e:
                        print(f"[MONITOR] Błąd przeładowania .env: {e}")
                
                # Sprawdzenie poprawności tokena bota
                bot_token = os.getenv("DISCORD_BOT_TOKEN")
                if not bot_token or bot_token.strip() == "" or bot_token.strip() == "your_discord_bot_token_here":
                    print("[MONITOR] DISCORD_BOT_TOKEN jest nieprawidłowy lub pusty. Wstrzymuję bota.")
                    try:
                        status = {"status": "error", "error": "Brak poprawnego tokenu bota w .env", "last_seen": time.time()}
                        with open(os.path.join(bot_dir, "bot_status.json"), "w") as f:
                            json.dump(status, f)
                    except Exception as e:
                        print(f"[MONITOR] Błąd zapisu statusu: {e}")
                    time.sleep(10)
                    continue

                if consecutive_failures >= max_failures:
                    print(f"[MONITOR] Wykryto pętlę awarii bota ({consecutive_failures} nieudanych uruchomień). Auto-restart wstrzymany.")
                    try:
                        status = {
                            "status": "error",
                            "error": "Pętla awarii bota. Sprawdź bot_error.log (prawdopodobnie niepoprawny token).",
                            "last_seen": time.time()
                        }
                        with open(os.path.join(bot_dir, "bot_status.json"), "w") as f:
                            json.dump(status, f)
                    except Exception as e:
                        print(f"[MONITOR] Błąd zapisu statusu awarii: {e}")
                    
                    # Wstrzymujemy restarty na 2 minuty, ale sprawdzamy plik .env co 5 sekund na wypadek modyfikacji
                    for _ in range(24):
                        time.sleep(5)
                        if os.path.exists(env_path):
                            try:
                                mtime = os.path.getmtime(env_path)
                                if mtime > last_env_mtime:
                                    last_env_mtime = mtime
                                    print("[MONITOR] Wykryto modyfikację .env podczas oczekiwania. Przerywam uśpienie.")
                                    consecutive_failures = 0
                                    try:
                                        load_dotenv(env_path, override=True)
                                    except: pass
                                    break
                            except: pass
                    
                    if consecutive_failures >= max_failures:
                        # Jeśli nie przerwano przez modyfikację .env, kontynuujemy wstrzymanie
                        continue

                print(f"[SYSTEM] Uruchamiam proces bota w tle... (Python: {python_exe})")
                log_path = os.path.join(bot_dir, "bot_error.log")
                start_time = time.time()
                
                try:
                    with open(log_path, "a") as f:
                        f.write(f"\n--- START BOT {datetime.datetime.now()} (Python: {python_exe}) ---\n")
                        proc = subprocess.Popen(
                            [python_exe, "-u", os.path.join(bot_dir, "bot.py")],
                            stdout=f,
                            stderr=f,
                            cwd=bot_dir,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )
                except Exception as e:
                    print(f"[MONITOR] Błąd uruchamiania bota: {e}")
                    consecutive_failures += 1
                    time.sleep(10)
                    continue

                # Pętla monitorowania procesu bota w czasie rzeczywistym
                while True:
                    if proc.poll() is not None:
                        exit_code = proc.returncode
                        elapsed = time.time() - start_time
                        print(f"[MONITOR] Proces bota zakończył się z kodem {exit_code} po {elapsed:.1f} sekundach.")
                        
                        if elapsed < quick_crash_threshold:
                            consecutive_failures += 1
                            print(f"[MONITOR] Szybka awaria bota. Licznik awarii: {consecutive_failures}/{max_failures}")
                        else:
                            consecutive_failures = 0
                            print("[MONITOR] Proces bota działał stabilnie. Resetuję licznik awarii.")
                        break
                    
                    # W międzyczasie możemy też sprawdzić czy nie zmienił się plik .env.
                    # Jeśli zmienił się w trakcie działania bota, możemy chcieć zrestartować go na nowym tokenie!
                    if os.path.exists(env_path):
                        try:
                            mtime = os.path.getmtime(env_path)
                            if mtime > last_env_mtime:
                                last_env_mtime = mtime
                                print("[MONITOR] Wykryto zmianę .env w trakcie działania bota. Restartuję bota z nową konfiguracją...")
                                proc.terminate()
                                try:
                                    proc.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    proc.kill()
                                consecutive_failures = 0
                                try:
                                    load_dotenv(env_path, override=True)
                                except: pass
                                break
                        except: pass
                        
                    time.sleep(5)
                
                time.sleep(5)

        # Uruchamiamy wątek monitorujący bota
        monitor_thread = threading.Thread(target=monitor_bot, daemon=True)
        monitor_thread.start()
        
        def monitor_custom_bots():
            import time
            import subprocess
            import sqlite3
            from database import update_custom_bot_status, update_music_bot_status
            
            custom_bot_processes = {}  # guild_id -> Popen process
            music_bot_processes = {}   # bot_id -> Popen process
            
            # Statystyki awarii do ochrony przed crash-loopami
            custom_bot_stats = {}  # guild_id -> {'failures': int, 'last_token': str, 'last_enabled': bool}
            music_bot_stats = {}   # bot_id -> {'failures': int, 'last_token': str, 'last_enabled': bool}
            
            quick_crash_threshold = 30  # sekundy
            max_failures = 3
            
            while True:
                try:
                    from database import DB_NAME
                    conn = None
                    rows = []
                    m_rows = []
                    try:
                        conn = sqlite3.connect(DB_NAME, timeout=10)
                        c = conn.cursor()
                        c.execute('SELECT guild_id, token, enabled FROM custom_bots')
                        rows = c.fetchall()
                        c.execute('SELECT id, token, enabled, guild_id FROM music_bots')
                        m_rows = c.fetchall()
                    finally:
                        if conn:
                            conn.close()
                    
                    db_bots = {}
                    from database import is_premium
                    for row in rows:
                        g_id, tok, en = row
                        if tok and tok.strip():
                            # Jeśli własny bot jest włączony, ale serwer nie ma już Premium, wyłączamy go
                            if en and not is_premium(g_id):
                                try:
                                    conn_upd = sqlite3.connect(DB_NAME, timeout=10)
                                    c_upd = conn_upd.cursor()
                                    c_upd.execute("UPDATE custom_bots SET enabled = 0, status = 'offline' WHERE guild_id = ?", (str(g_id),))
                                    conn_upd.commit()
                                    conn_upd.close()
                                    print(f"⚠️ [MONITOR] Wyłączono własnego bota dla gildii {g_id} z powodu braku subskrypcji Premium.")
                                except Exception as ex:
                                    print(f"❌ [MONITOR] Błąd wyłączania własnego bota dla gildii {g_id}: {ex}")
                                en = 0
                            
                            db_bots[str(g_id)] = {'token': tok, 'enabled': bool(en)}
                            
                    db_music_bots = {}
                    for row in m_rows:
                        m_id, tok, en, g_id = row
                        if tok and tok.strip():
                            # Jeśli bot muzyczny jest włączony, ale serwer nie ma już Premium, wyłączamy go
                            if en and not is_premium(g_id):
                                try:
                                    conn_upd = sqlite3.connect(DB_NAME, timeout=10)
                                    c_upd = conn_upd.cursor()
                                    c_upd.execute("UPDATE music_bots SET enabled = 0, status = 'offline' WHERE id = ?", (int(m_id),))
                                    conn_upd.commit()
                                    conn_upd.close()
                                    print(f"⚠️ [MONITOR] Wyłączono bota muzycznego ID {m_id} dla gildii {g_id} z powodu braku subskrypcji Premium.")
                                except Exception as ex:
                                    print(f"❌ [MONITOR] Błąd wyłączania bota muzycznego ID {m_id}: {ex}")
                                en = 0
                            
                            db_music_bots[str(m_id)] = {'token': tok, 'enabled': bool(en)}
                    
                    # Inicjalizacja/Aktualizacja liczników awarii dla custom botów
                    for g_id, bot_info in db_bots.items():
                        stats = custom_bot_stats.setdefault(g_id, {
                            'failures': 0, 
                            'last_token': bot_info['token'], 
                            'last_enabled': bot_info['enabled']
                        })
                        if stats['last_token'] != bot_info['token']:
                            stats['last_token'] = bot_info['token']
                            stats['failures'] = 0
                        if not stats['last_enabled'] and bot_info['enabled']:
                            stats['failures'] = 0
                        stats['last_enabled'] = bot_info['enabled']
                        
                    # Inicjalizacja/Aktualizacja liczników awarii dla botów muzycznych
                    for m_id, bot_info in db_music_bots.items():
                        stats = music_bot_stats.setdefault(m_id, {
                            'failures': 0, 
                            'last_token': bot_info['token'], 
                            'last_enabled': bot_info['enabled']
                        })
                        if stats['last_token'] != bot_info['token']:
                            stats['last_token'] = bot_info['token']
                            stats['failures'] = 0
                        if not stats['last_enabled'] and bot_info['enabled']:
                            stats['failures'] = 0
                        stats['last_enabled'] = bot_info['enabled']
                    
                    # 1. Monitorowanie Custom Botów (White Label)
                    to_remove = []
                    for g_id, proc in list(custom_bot_processes.items()):
                        poll = proc.poll()
                        if poll is not None:
                            print(f"[CUSTOM BOT MONITOR] Proces dla gildii {g_id} zakończył się z kodem {poll}.")
                            to_remove.append(g_id)
                            
                            # Obsługa wykrywania szybkiego crashu
                            elapsed = time.time() - getattr(proc, 'custom_bot_start_time', time.time())
                            stats = custom_bot_stats.setdefault(g_id, {'failures': 0, 'last_token': '', 'last_enabled': True})
                            
                            if elapsed < quick_crash_threshold:
                                stats['failures'] += 1
                                print(f"[CUSTOM BOT MONITOR] Szybka awaria bota dla gildii {g_id}. Awarii z rzędu: {stats['failures']}/{max_failures}")
                            else:
                                stats['failures'] = 0
                                print(f"[CUSTOM BOT MONITOR] Proces bota dla gildii {g_id} działał stabilnie. Resetuję licznik.")
                                
                            if stats['failures'] >= max_failures:
                                print(f"[CUSTOM BOT MONITOR] Custom bot dla gildii {g_id} przekroczył limit awarii. Zawieszam go.")
                                try:
                                    conn_d = sqlite3.connect(DB_NAME, timeout=10)
                                    try:
                                        c_d = conn_d.cursor()
                                        c_d.execute('UPDATE custom_bots SET enabled=0, status=? WHERE guild_id=?', ('suspended', str(g_id)))
                                        conn_d.commit()
                                    finally:
                                        conn_d.close()
                                except Exception as dbe:
                                    print(f"[CUSTOM BOT MONITOR] Błąd zawieszania bota w bazie: {dbe}")
                                stats['last_enabled'] = False
                                update_custom_bot_status(g_id, "suspended")
                            else:
                                update_custom_bot_status(g_id, "offline")
                                
                        elif g_id not in db_bots or not db_bots[g_id]['enabled']:
                            print(f"[CUSTOM BOT MONITOR] Zamykanie bota dla gildii {g_id}...")
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            update_custom_bot_status(g_id, "offline")
                            to_remove.append(g_id)
                            
                    for g_id in to_remove:
                        if g_id in custom_bot_processes:
                            del custom_bot_processes[g_id]
                            
                    for g_id, bot_info in db_bots.items():
                        stats = custom_bot_stats.get(g_id, {})
                        failures = stats.get('failures', 0)
                        if bot_info['enabled'] and g_id not in custom_bot_processes and failures < max_failures:
                            print(f"[CUSTOM BOT MONITOR] Uruchamianie bota dla gildii {g_id}...")
                            try:
                                log_path = os.path.join(bot_dir, f"bot_error_custom_{g_id}.log")
                                f_log = open(log_path, "a", encoding="utf-8", errors="replace")
                                f_log.write(f"\n--- START CUSTOM BOT {datetime.datetime.now()} ---\n")
                                proc = subprocess.Popen(
                                    [python_exe, "-u", os.path.join(bot_dir, "bot.py"), "--guild", g_id],
                                    stdout=f_log,
                                    stderr=f_log,
                                    cwd=bot_dir,
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                                )
                                proc.custom_bot_start_time = time.time()
                                custom_bot_processes[g_id] = proc
                                update_custom_bot_status(g_id, "online")
                            except Exception as e:
                                print(f"[CUSTOM BOT MONITOR] Błąd podczas uruchamiania bota dla {g_id}: {e}")
                                update_custom_bot_status(g_id, "offline")
                                
                    # 2. Monitorowanie Botów Muzycznych
                    to_remove_music = []
                    for m_id, proc in list(music_bot_processes.items()):
                        poll = proc.poll()
                        if poll is not None:
                            print(f"[MUSIC BOT MONITOR] Proces dla bota ID {m_id} zakończył się z kodem {poll}.")
                            to_remove_music.append(m_id)
                            
                            # Obsługa wykrywania szybkiego crashu
                            elapsed = time.time() - getattr(proc, 'custom_bot_start_time', time.time())
                            stats = music_bot_stats.setdefault(m_id, {'failures': 0, 'last_token': '', 'last_enabled': True})
                            
                            if elapsed < quick_crash_threshold:
                                stats['failures'] += 1
                                print(f"[MUSIC BOT MONITOR] Szybka awaria bota ID {m_id}. Awarii z rzędu: {stats['failures']}/{max_failures}")
                            else:
                                stats['failures'] = 0
                                print(f"[MUSIC BOT MONITOR] Proces bota ID {m_id} działał stabilnie. Resetuję licznik.")
                                
                            if stats['failures'] >= max_failures:
                                print(f"[MUSIC BOT MONITOR] Bot muzyczny ID {m_id} przekroczył limit awarii. Zawieszam go.")
                                try:
                                    conn_d = sqlite3.connect(DB_NAME, timeout=10)
                                    try:
                                        c_d = conn_d.cursor()
                                        c_d.execute('UPDATE music_bots SET enabled=0, status=? WHERE id=?', ('suspended', int(m_id)))
                                        conn_d.commit()
                                    finally:
                                        conn_d.close()
                                except Exception as dbe:
                                    print(f"[MUSIC BOT MONITOR] Błąd zawieszania bota w bazie: {dbe}")
                                stats['last_enabled'] = False
                                update_music_bot_status(m_id, "suspended")
                            else:
                                update_music_bot_status(m_id, "offline")
                                
                        elif m_id not in db_music_bots or not db_music_bots[m_id]['enabled']:
                            print(f"[MUSIC BOT MONITOR] Zamykanie bota dla ID {m_id}...")
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            update_music_bot_status(m_id, "offline")
                            to_remove_music.append(m_id)
                            
                    for m_id in to_remove_music:
                        if m_id in music_bot_processes:
                            del music_bot_processes[m_id]
                            
                    for m_id, bot_info in db_music_bots.items():
                        stats = music_bot_stats.get(m_id, {})
                        failures = stats.get('failures', 0)
                        if bot_info['enabled'] and m_id not in music_bot_processes and failures < max_failures:
                            print(f"[MUSIC BOT MONITOR] Uruchamianie bota dla ID {m_id}...")
                            try:
                                log_path = os.path.join(bot_dir, f"bot_error_music_{m_id}.log")
                                f_log = open(log_path, "a", encoding="utf-8", errors="replace")
                                f_log.write(f"\n--- START MUSIC BOT {datetime.datetime.now()} ---\n")
                                proc = subprocess.Popen(
                                    [python_exe, "-u", os.path.join(bot_dir, "bot.py"), "--music-bot-id", m_id],
                                    stdout=f_log,
                                    stderr=f_log,
                                    cwd=bot_dir,
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                                )
                                proc.custom_bot_start_time = time.time()
                                music_bot_processes[m_id] = proc
                                update_music_bot_status(m_id, "online")
                            except Exception as e:
                                print(f"[MUSIC BOT MONITOR] Błąd podczas uruchamiania bota dla ID {m_id}: {e}")
                                update_music_bot_status(m_id, "offline")
                                
                except Exception as ex:
                    print(f"[BOT MONITOR] Wyjątek w pętli monitorowania: {ex}")
                    
                time.sleep(5)
            
        custom_bots_thread = threading.Thread(target=monitor_custom_bots, daemon=True)
        custom_bots_thread.start()
        
    except socket.error:
        # Bot już prawdopodobnie działa w innym procesie (port zablokowany przez inny worker)
        pass
    except Exception as e:
        print(f"[SYSTEM] Błąd startu bota: {e}")

# Uruchamiamy bota przy starcie aplikacji (tylko jeśli nie jesteśmy w reloaderze Flaska i nie jesteśmy pod uWSGI)
is_under_uwsgi = 'uwsgi' in sys.modules
if not is_under_uwsgi and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
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
            try:
                token_data = token_resp.json()
            except ValueError:
                token_data = {"error": "Invalid JSON response", "text": token_resp.text}
            
            try:
                with open("auth_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"  Status tokena: {token_resp.status_code}\n")
                    f.write(f"  Token dane: {token_data}\n")
            except Exception as log_err:
                print(f"⚠️ [AUTH] Nie udało się zapisać statusu tokena do logu: {log_err}")

            if token_resp.status_code == 200:
                access_token = token_data.get('access_token')
                if not access_token:
                    print("⚠️ [AUTH] Brak access_token w odpowiedzi Discorda.")
                    return redirect(url_for('home.index'))

                user_resp = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
                if user_resp.status_code != 200:
                    print(f"⚠️ [AUTH] Błąd pobierania profilu użytkownika ({user_resp.status_code}): {user_resp.text}")
                    return redirect(url_for('home.index'))

                try:
                    user_data = user_resp.json()
                except ValueError:
                    print("⚠️ [AUTH] Błąd parsowania JSON profilu użytkownika.")
                    return redirect(url_for('home.index'))

                user_id = user_data.get('id')
                if not user_id:
                    print(f"⚠️ [AUTH] Brak ID użytkownika w danych profilu: {user_data}")
                    return redirect(url_for('home.index'))

                print(f"👤 [AUTH] Zalogowano użytkownika: {user_data.get('username')} (ID: {user_id})")

                # Pobieramy najświeższe serwery użytkownika z Discorda
                guilds_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
                all_guilds = []
                if guilds_resp.status_code == 200:
                    try:
                        all_guilds = guilds_resp.json()
                    except ValueError:
                        pass
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
                session['user'] = {'id': user_id, 'username': user_data.get('username'), 'avatar': user_data.get('avatar')}
                session['user_avatar'] = get_user_avatar(session['user'])
                session['access_token'] = access_token
                session['last_profile_refresh'] = time.time()
                session.modified = True

                # Zapisujemy serwery w pamięci procesu (nie w cookie!) - brak limitu 4KB
                _guilds_memory_cache[user_id] = managed_guilds
                print(f"💾 [AUTH] Zapisano {len(managed_guilds)} serwerów w pamięci (user: {user_id})")
            else:
                print(f"⚠️ [AUTH] Błąd tokena: {token_data}")
                return redirect(url_for('home.index'))
        except Exception as e:
            print(f"❌ [AUTH] Błąd krytyczny przy wymianie tokena: {e}")
            try:
                with open("auth_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"  Blad krytyczny tokena: {e}\n")
            except: pass
            return redirect(url_for('home.index'))

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
    if not is_local_dev:
        return redirect(url_for('home.index'))
        
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
    secret_param = request.args.get('secret')
    expected_secret = os.getenv("FLASK_SECRET", "polskibot-fixed-key-12345")[:6]
    if not is_local_dev and secret_param != expected_secret:
        return redirect(url_for('home.index'))
        
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
        status_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_status.json")
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

@app.route('/debug_auth_log')
def debug_auth_log():
    secret_param = request.args.get('secret')
    expected_secret = os.getenv("FLASK_SECRET", "polskibot-fixed-key-12345")[:6]
    if not is_local_dev and secret_param != expected_secret:
        return redirect(url_for('home.index'))
        
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_debug.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return f"<pre>{content}</pre>"
        except Exception as e:
            return f"Error reading log: {e}"
    return "Log file not found"

if __name__ == '__main__':
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    print(f"[SYSTEM] Uruchamiam Flask na {host}:{port}")
    app.run(host=host, port=port)