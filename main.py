import threading
import time
import asyncio
import sys
from run import app
from bot import run_bot
from database import init_db

RETRY_DELAY = 5

def start_flask():
    """Uruchamia serwer WWW Flask."""
    print("[FLASK] Uruchamianie serwera WWW na porcie 5000...")
    try:
        app.run(port=5000, debug=True, use_reloader=False)
    except Exception as e:
        print(f"[FLASK] Błąd krytyczny: {e}")

def start_discord_bot():
    """Uruchamia bota Discord z automatycznym restartem po błędzie."""
    while True:
        print("[BOT] Łączenie z Discord...")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_bot())
        except Exception as e:
            print(f"[BOT] Błąd: {e}")
        
        print(f"[BOT] Ponowne połączenie za {RETRY_DELAY}s...")
        time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    init_db()
    print("==========================================")
    print("       POLSKIBOT - SYSTEM ZINTEGROWANY    ")
    print("==========================================")

    # Uruchomienie wątków
    bot_thread = threading.Thread(target=start_discord_bot, daemon=True)
    flask_thread = threading.Thread(target=start_flask, daemon=True)

    bot_thread.start()
    time.sleep(2)
    flask_thread.start()

    print("[SYSTEM] Serwisy uruchomione. Naciśnij Ctrl+C aby zatrzymać.")

    try:
        while True:
            time.sleep(5)
            if not bot_thread.is_alive():
                print("[SYSTEM] Restartowanie bota...")
                bot_thread = threading.Thread(target=start_discord_bot, daemon=True)
                bot_thread.start()
            if not flask_thread.is_alive():
                print("[SYSTEM] Restartowanie Flask...")
                flask_thread = threading.Thread(target=start_flask, daemon=True)
                flask_thread.start()
    except KeyboardInterrupt:
        print("\n[SYSTEM] Zamykanie...")
        sys.exit(0)
