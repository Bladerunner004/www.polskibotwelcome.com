import sys
import os

# Ścieżka do Twojego projektu na PythonAnywhere
path = '/home/BLADERUNNER009/AntigravityProjekt'
if path not in sys.path:
    sys.path.insert(0, path)

# Ustawiamy zmienne środowiskowe z pliku .env (PythonAnywhere nie ładuje .env automatycznie)
from dotenv import load_dotenv
load_dotenv(os.path.join(path, '.env'))

# Importujemy aplikację Flask z pliku run.py
from run import app as application
