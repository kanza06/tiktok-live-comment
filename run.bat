@echo off
cd /d %~dp0
if not exist venv312 (
    echo Membuat virtual environment...
    python -m venv venv312
)
call venv312\Scripts\activate
echo Memasang dependensi...
pip install -r requirements.txt
python main.py
pause
