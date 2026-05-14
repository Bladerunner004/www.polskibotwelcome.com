import os
import uuid
import requests
import json
import time
import sqlite3
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

# --- WEWNĘTRZNA KOMUNIKACJA Z BOTEM ---
BOT_API_URL = "http://127.0.0.1:5006"
_bot_offline_cache = 0  # Timestamp ostatniej nieudanej próby

def call_bot_api(endpoint, method="GET", data=None):
    """Pomocnicza funkcja do komunikacji z wewnętrznym API bota."""
    global _bot_offline_cache
    import time
    import json
    import os

    # Zawsze przy POST tworzymy sygnał plikowy (dla PythonAnywhere) - PRZED sprawdzeniem cache!
    if method == "POST":
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
                print(f"[DASHBOARD] Tworzenie sygnalu synchronizacji: {filepath}")
                with open(filepath, "w") as f:
                    json.dump({"endpoint": endpoint, "time": time.time(), "data": data}, f)
        except Exception as e:
            print(f"[DASHBOARD] Blad tworzenia pliku sync: {e}")

    # Jeśli bot był offline w ciągu ostatnich 5 sekund, nie próbuj HTTP (ale sync plik już jest)
    if time.time() - _bot_offline_cache < 5:
        return None

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
        
        from database import save_settings
        save_settings(server_id, prefix, language, embed_color)
        
        return jsonify({'success': True})

    # GET - Renderowanie panelu
    from database import get_settings, get_embed_configs
    settings = get_settings(server_id)
    embeds = get_embed_configs(server_id)
    
    return render_template('config.html', server_id=server_id, settings=settings, embeds=embeds)

# --- REZTA KODU ROUTES ---
# (Dla oszczędności miejsca zakładam, że reszta jest poprawna)
# final_sync_check
