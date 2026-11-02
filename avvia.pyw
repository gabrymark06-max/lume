"""Apre Lume in una finestra dedicata e riusa il server già avviato."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Lume'
ADDRESS = 'http://127.0.0.1:8766/'


def ready():
    try:
        with urllib.request.urlopen(ADDRESS + 'api/health', timeout=1) as r:
            return json.load(r).get('app') == 'lume'
    except Exception:
        return False


def open_window():
    edge = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
    if edge.is_file():
        subprocess.Popen([str(edge), '--app=' + ADDRESS, '--user-data-dir=' + str(DATA / 'browser')], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        import webbrowser
        webbrowser.open(ADDRESS)


try:
    if not ready():
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / 'avvio.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', '8766'], cwd=str(ROOT),
                             stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(30):
            if ready():
                break
            time.sleep(.2)
        else:
            raise RuntimeError('Il server locale non si è avviato. Vedi %LOCALAPPDATA%/Lume/avvio.log.')
    open_window()
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None, str(exc), 'Lume — avvio non riuscito', 0x10)
