import sys
import os

# Ścieżka do Twojego projektu
path = '/home/BLADERUNNER009/AntigravityProjekt/AntigravityProjekt'
if path not in sys.path:
    sys.path.append(path)

# Importujemy aplikację Flask z pliku run.py
from run import app as application
