"""Launcher TikTok Live Reader — pakai Python di venv proyek ini."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
# Pakai venv312 (venv lama tidak ada paket yang benar)
VENV_PY = ROOT / "venv312" / "Scripts" / "python.exe"

def main():
    if not VENV_PY.exists():
        print("venv tidak ditemukan. Buat dulu: python -m venv venv")
        sys.exit(1)
    # Jalankan GUI main.py dengan Python venv (window baru, tanpa wrapper aneh)
    subprocess.Popen([str(VENV_PY), str(ROOT / "main.py")], cwd=str(ROOT))

if __name__ == "__main__":
    main()
