import sys
import os

# Dynamicznie określamy ścieżkę do projektu (katalog, w którym znajduje się ten plik)
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

# Ustawiamy zmienne środowiskowe z pliku .env (PythonAnywhere nie ładuje .env automatycznie)
from dotenv import load_dotenv
load_dotenv(os.path.join(path, '.env'))

# Importujemy aplikację Flask z pliku run.py
from run import app as application
