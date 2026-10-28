# TikTok Live Reader 🎥💬

Aplikasi desktop (Windows) untuk membaca **komentar, gift, dan penonton TikTok Live** secara real-time — dibuat dengan Python + PySide6.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey) ![Release](https://img.shields.io/badge/Release-v1.0-green)

---

## ✨ Fitur

- 📖 **Feed komentar live** — komentar penonton tampil real-time dengan avatar asli TikTok
- 🎁 **Panel gift** — pengirim, jenis gift, jumlah, plus gambar gift yang dimuat otomatis
- 👁 👥 🎁 **Counter penonton** — penonton aktif, yang pernah mampir, dan pemberi gift (klik ikonnya untuk lihat daftar + lama menonton)
- 🌐 **Kecepatan jaringan (upstream/downstream)** — tampil di samping ikon gift, update tiap detik
- ⚙️ **Pengaturan lengkap:**
  - Username TikTok
  - Transparansi jendela (slider)
  - Ukuran font & jenis font
  - **Satuan kecepatan jaringan: Kbps / Mbps / MBps**
  - Tema Terang / Gelap
- 📌 Tombol *always on top* (selalu di atas jendela lain)
- 🎨 Jendela tanpa bingkai, transparan, bisa digeser & di-resize
- 💾 Semua pengaturan tersimpan otomatis di `settings.json`

## 📥 Download

Unduh **TikTokLiveReader_v1.0.exe** dari halaman [Releases](../../releases) — portable, tidak perlu install Python apa pun. Tinggal jalankan!

## 🚀 Cara Pakai (versi EXE)

1. Download `TikTokLiveReader_v1.0.exe` dari [Releases](../../releases)
2. Jalankan file-nya (boleh ditaruh di mana saja)
3. Klik ikon **⚙ (gear)**, isi username TikTok **tanpa @**, lalu klik **Hubungkan**
4. Akun tersebut harus sedang **LIVE** 🎬

## 🛠 Cara Pakai (dari source)

1. Pasang **Python 3.10+** (centang *"Add python.exe to PATH"*)
2. Jalankan `run.bat` — otomatis membuat venv, install library, dan membuka aplikasi

   Atau manual:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```

## 🔨 Build EXE sendiri (onefile)

```
pip install pyinstaller
pyinstaller --onefile --noconsole --icon=icon.ico main.py
```

Hasilnya ada di folder `dist\`.

## ⚠️ Masalah Umum

| Masalah | Solusi |
|---|---|
| `UserOfflineError` | Akun belum live / username salah |
| Gagal koneksi lain | TikTok kadang membatasi akses — coba lagi beberapa menit, atau update: `pip install -U TikTokLive` |
| Penonton lama tidak muncul | TikTok tidak selalu mengirim event "join"; yang berkomentar/gift tetap tercatat |

## 📝 Catatan

Library `TikTokLive` **bukan resmi dari TikTok**, jadi perilakunya bisa berubah sewaktu-waktu.

## 📄 Lisensi

Bebas digunakan untuk keperluan pribadi. Kontribusi welcome — silakan buat Pull Request!
