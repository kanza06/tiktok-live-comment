"""TikTok Live Reader - pembaca komentar & gift TikTok Live (PySide6 + TikTokLive)."""
import asyncio
import html
import json
import sys
import time

try:
    import psutil
except ImportError:
    psutil = None
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizeGrip, QSlider, QSplitter, QVBoxLayout, QWidget,
)

SETTINGS_FILE = Path(__file__).with_name("settings.json")
DEFAULTS = {"username": "", "opacity": 90, "font_size": 14, "font_family": "Segoe UI", "theme": "dark",
            "speed_unit": "kbps"}
def fmt_speed(bytes_per_sec, unit="kbps"):
    """Format kecepatan jaringan. Data dasar psutil = Bytes per detik (B/s)."""
    if bytes_per_sec is None:
        return "--"
    b = max(bytes_per_sec, 0)
    if unit == "kbps":
        # (Bytes * 8) / 1024 -> Kilobit per detik
        val, label = (b * 8) / 1024, "Kbps"
    elif unit == "mbps":
        # (Bytes * 8) / (1024 * 1024) -> Megabit per detik
        val, label = (b * 8) / (1024 * 1024), "Mbps"
    elif unit == "MBps":
        # Bytes / (1024 * 1024) -> Megabyte per detik (tanpa dikali 8)
        val, label = b / (1024 * 1024), "MBps"
    else:
        val, label = (b * 8) / 1024, "Kbps"
    if val < 10:
        return f"{val:.1f} {label}"
    return f"{val:.0f} {label}"
MAX_CHIPS = 9
TITLE_H = 50

THEMES = {
    "dark": dict(bg="18,18,23", panel="#1C1C24", panel2="#252530", text="#EDEDF2",
                 muted="#A8A8BA", accent="#25F4EE", accent2="#E8204F",
                 border="#2E2E3B", input="#22222C"),
    "light": dict(bg="245,246,250", panel="#FFFFFF", panel2="#EEF0F6", text="#1A1A22",
                  muted="#5C5C6E", accent="#0E8F8A", accent2="#D91E48",
                  border="#DCDDE6", input="#FFFFFF"),
}
AVATAR_COLORS = ["#25F4EE", "#FE2C55", "#F5C451", "#9B8CFF", "#3DDC84", "#FF9F5A"]


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_settings(cfg):
    try:
        SETTINGS_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def fmt_dur(sec):
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h} jam {m} mnt"
    if m:
        return f"{m} mnt {s} dtk"
    return f"{s} dtk"


# --------------------------------------------------------------------------
# Koneksi TikTok Live (berjalan di thread terpisah supaya UI tidak macet)
# --------------------------------------------------------------------------
class TikTokWorker(QThread):
    comment = Signal(str, str, str)
    gift = Signal(str, str, int, str)
    joined = Signal(str, str)
    status = Signal(str, bool)

    @staticmethod
    def _avatar_url(user):
        """Ambil URL foto profil dari user.avatar_thumb.avatar_urls."""
        try:
            t = user.avatar_thumb
            if t and t.url_list:
                return t.url_list[0]
        except Exception:
            pass
        return ""

    @staticmethod
    def _gift_image_url(gift):
        """Ambil URL gambar gift (icon/preview) dari objek Gift."""
        try:
            for attr in ("icon", "preview_image", "image"):
                img = getattr(gift, attr, None)
                if img and getattr(img, "url_list", None):
                    return img.url_list[0]
        except Exception:
            pass
        return ""

    def __init__(self, username):
        super().__init__()
        self.username = username.strip().lstrip("@")
        self.loop = None
        self.client = None

    @staticmethod
    def _name(user):
        return getattr(user, "nickname", None) or getattr(user, "unique_id", None) or "?"

    def run(self):
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import (
                CommentEvent, ConnectEvent, DisconnectEvent, GiftEvent, JoinEvent,
                LiveEndEvent,
            )
            from TikTokLive.client.errors import UserOfflineError
        except ImportError:
            self.status.emit("Library TikTokLive belum terpasang", False)
            return

        self._stopping = False

        def wire(cl):
            @cl.on(ConnectEvent)
            async def on_connect(event):
                self.status.emit(f"Terhubung ke @{self.username}", True)

            @cl.on(DisconnectEvent)
            async def on_disconnect(event):
                self.status.emit("Terputus", False)

            @cl.on(JoinEvent)
            async def on_join(event):
                self.joined.emit(self._name(event.user), self._avatar_url(event.user))

            @cl.on(CommentEvent)
            async def on_comment(event):
                # Log diagnosis: event masuk dari sumber TikTok
                print(f"[COMMENT-RECV] {time.strftime('%H:%M:%S')} "
                      f"user={self._name(event.user)!r} text={event.comment!r}",
                      flush=True)
                self.comment.emit(self._name(event.user), event.comment,
                                  self._avatar_url(event.user))

            @cl.on(GiftEvent)
            async def on_gift(event):
                # Gift beruntun: kirim hanya saat rangkaian selesai
                if getattr(event.gift, "streakable", False) and getattr(event, "streaking", False):
                    return
                img = self._gift_image_url(event.gift)
                self.gift.emit(self._name(event.user), event.gift.name,
                               int(getattr(event, "repeat_count", 1) or 1), img)

            @cl.on(LiveEndEvent)
            async def on_live_end(event):
                self.status.emit("Live berakhir", False)

        self._wire = wire

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        client = TikTokLiveClient(unique_id="@" + self.username)
        self.client = client
        self._wire(client)

        async def runner():
            task = await client.start()
            await task

        # Coba hubungkan sampai 3 kali: TikTok sering membatasi request
        # sementara (deteksi/captcha), mencoba lagi biasanya berhasil.
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            try:
                self.loop.run_until_complete(runner())
                break  # terputus dengan normal
            except UserOfflineError:
                self.status.emit("Live sudah selesai / user offline", False)
                break
            except Exception as e:
                if self._stopping:
                    break
                name = type(e).__name__
                msg = str(e).split("->", 1)[-1].strip()[:120]
                if attempt < max_tries:
                    self.status.emit(
                        f"Gagal ({name}), mencoba lagi ({attempt}/{max_tries - 1})...", False
                    )
                    time.sleep(3)
                    # buat client baru untuk percobaan berikutnya
                    client = TikTokLiveClient(unique_id="@" + self.username)
                    self.client = client
                    self._wire(client)
                    continue
                self.status.emit(f"Gagal: {name} - {msg}", False)

        try:
            self.loop.close()
        except Exception:
            pass

    def stop(self):
        self._stopping = True
        if self.client and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)


# --------------------------------------------------------------------------
# Widget kecil
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Cache & pemuat gambar (non-blocking, agar UI tidak lag)
# --------------------------------------------------------------------------
class ImageCache:
    """Unduh gambar secara asinkron (QtNetwork) + cache memori & disk.
    QNetworkAccessManager dibuat lazily (setelah QApplication ada)."""

    MEM_LIMIT = 300  # maksimal gambar di memori

    def __init__(self):
        self._nam = None
        self.mem = {}          # url -> QPixmap
        self.pending = {}      # url -> [callback]
        self.dir = Path("image_cache")
        try:
            self.dir.mkdir(exist_ok=True)
        except Exception:
            self.dir = None

    @property
    def nam(self):
        if self._nam is None:
            self._nam = QNetworkAccessManager()
        return self._nam

    def _disk_path(self, url):
        if self.dir is None:
            return None
        import hashlib
        h = hashlib.md5(url.encode()).hexdigest()
        ext = ".png" if ".png" in url.lower() else ".jpg"
        return self.dir / (h + ext)

    def get(self, url, callback):
        """callback dipanggil dengan QPixmap saat gambar siap (bisa seketika)."""
        if not url:
            return
        pm = self.mem.get(url)
        if pm is not None:
            callback(pm)
            return
        path = self._disk_path(url)
        if path and path.exists() and path.stat().st_size > 0:
            img = QImage(str(path))
            if not img.isNull():
                pm = QPixmap.fromImage(img)
                self.mem[url] = pm
                callback(pm)
                return
        if url in self.pending:
            self.pending[url].append(callback)
            return
        self.pending[url] = [callback]
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self.nam.get(req)
        reply.finished.connect(lambda: self._done(url, reply))

    def _done(self, url, reply: QNetworkReply):
        cbs = self.pending.pop(url, [])
        data = bytes(reply.readAll())
        reply.deleteLater()
        pm = QPixmap()
        if data and pm.loadFromData(data):
            if len(self.mem) >= self.MEM_LIMIT:
                self.mem.clear()  # reset sederhana agar memori tidak terus tumbuh
            self.mem[url] = pm
            path = self._disk_path(url)
            if path:
                try:
                    path.write_bytes(data)
                except Exception:
                    pass
            for cb in cbs:
                cb(pm)


IMG_CACHE = None


def get_img_cache():
    global IMG_CACHE
    if IMG_CACHE is None:
        IMG_CACHE = ImageCache()
    return IMG_CACHE


def round_pixmap(src: QPixmap, size: int) -> QPixmap:
    """Potong pixmap menjadi bulat."""
    pm = src.scaled(size, size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
    d = max((pm.width() - size) // 2, 0)
    pm = pm.copy(d, d, size, size)
    mask = QPixmap(size, size)
    mask.fill(Qt.GlobalColor.transparent)
    p = QPainter(mask)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(0, 0, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.end()
    pm.setMask(mask.mask())
    return pm


class Avatar(QLabel):
    """Avatar: foto profil asli dimuat asinkron; sementara tampil huruf pertama."""

    def __init__(self, name, size=30, image_url=""):
        super().__init__((name.strip()[:1] or "?").upper())
        color = AVATAR_COLORS[sum(map(ord, name)) % len(AVATAR_COLORS)]
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:{color};color:#0B0B10;border-radius:{size // 2}px;"
            "font-size:12px;font-weight:700;"
        )
        if image_url:
            self._size = size
            self._url = image_url
            get_img_cache().get(image_url, self._apply)

    def _apply(self, pm):
        if pm != get_img_cache().mem.get(self._url):
            return  # callback usang (widget lama yang sudah dihapus)
        self.setPixmap(round_pixmap(pm, self._size))
        self.setText("")
        self.setStyleSheet(self.styleSheet().split("background:")[0] +
                           self.styleSheet().split(";")[-1])


class ViewerChip(Avatar):
    """Avatar penonton; popup tooltip menampilkan lama menonton."""

    def __init__(self, name, joined_at, image_url=""):
        super().__init__(name, image_url=image_url)
        self.name, self.joined_at = name, joined_at

    def enterEvent(self, e):
        self.setToolTip(f"{self.name}\nMenonton {fmt_dur(time.time() - self.joined_at)}")
        super().enterEvent(e)


class Feed(QScrollArea):
    def __init__(self, newest_top=False, limit=150):
        super().__init__()
        self.setObjectName("feed")
        self.newest_top, self.limit = newest_top, limit
        self.auto_scroll = True  # ikut otomatis; mati saat user scroll ke atas
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setObjectName("inner")
        self.box = QVBoxLayout(inner)
        self.box.setContentsMargins(10, 10, 10, 10)
        self.box.setSpacing(10)
        self.box.addStretch(1)
        self.setWidget(inner)

    def _on_scroll(self, value):
        # user scroll menjauh dari ujung -> hentikan auto-follow agar bisa
        # membaca komentar lama; kembali ke ujung -> auto-follow aktif lagi.
        # Diabaikan jika pergeseran nilai disebabkan sendiri oleh _pin_bottom.
        if getattr(self, "_pinning", False):
            return
        bar = self.verticalScrollBar()
        at_end = value >= bar.maximum() - 30
        if self.newest_top:
            self.auto_scroll = value <= 30
        else:
            self.auto_scroll = at_end

    def add(self, widget, highlight=False):
        if self.newest_top:
            self.box.insertWidget(0, widget)
        else:
            self.box.insertWidget(self.box.count() - 1, widget)
        if self.box.count() - 1 > self.limit:
            idx = self.box.count() - 2 if self.newest_top else 0
            item = self.box.takeAt(idx)
            if item and item.widget():
                item.widget().deleteLater()
        # auto-scroll setelah layout selesai — terbaru selalu terlihat
        if self.newest_top:
            if self.auto_scroll:
                QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))
            if highlight:
                self._flash(widget)
        else:
            if self.auto_scroll:
                widget.installEventFilter(self)
                self._scroll_target = widget
                self._pin_bottom()
            if highlight:
                self._flash(widget)

    def _pin_bottom(self):
        """Kunci ke dasar; diulang beberapa tick sampai scrollbar stabil."""
        self._pinning = True
        try:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())
            if getattr(self, "_pin_tries", 0) < 8 and bar.value() < bar.maximum():
                self._pin_tries += 1
                QTimer.singleShot(16, self._pin_bottom)
                return  # jangan reset flag — masih dalam rangkaian pin
        finally:
            if not (getattr(self, "_pin_tries", 0) < 8 and bar.value() < bar.maximum()):
                self._pin_tries = 0
                self._pinning = False

    def _flash(self, widget):
        """Sorot komentar baru: highlight putih lalu memudar ke normal."""
        base = widget.styleSheet()
        widget.setStyleSheet("background:#FFFFFF; border-radius:10px; padding:3px;")

        def fade1():
            widget.setStyleSheet("background:rgba(255,255,255,0.6); border-radius:10px; padding:3px;")

        def fade2():
            widget.setStyleSheet("background:rgba(255,255,255,0.3); border-radius:10px; padding:3px;")

        def done():
            widget.setStyleSheet(base)

        QTimer.singleShot(200, fade1)
        QTimer.singleShot(450, fade2)
        QTimer.singleShot(750, done)

    def eventFilter(self, obj, event):
        # segera setiap widget komentar selesai di-layout, kunci scroll ke dasar
        if obj is getattr(self, "_scroll_target", None) and event.type() == QEvent.Type.LayoutRequest:
            if self.auto_scroll:
                self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            obj.removeEventFilter(self)
            self._scroll_target = None
        return super().eventFilter(obj, event)

    def scroll_to_latest(self):
        """Paksa langsung ke komentar terbaru (dipakai saat auto-scroll aktif lagi)."""
        self.auto_scroll = True
        bar = self.verticalScrollBar()
        bar.setValue(0 if self.newest_top else bar.maximum())


avatar_urls = {}  # cache username -> URL avatar asli (diisi saat join/komen)


def comment_row(name, text):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    h.addWidget(Avatar(name, 28, avatar_urls.get(name, "")), 0, Qt.AlignmentFlag.AlignTop)
    lab = QLabel(f"<b>{html.escape(name)}</b><br>{html.escape(text)}")
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setWordWrap(True)
    h.addWidget(lab, 1)
    return w


def join_row(names):
    """Baris "X dan Y bergabung" — beberapa penonton digabung dalam satu baris
    dengan pemisah, dan otomatis ikut ter-scroll di feed komentar."""
    f = QFrame()
    f.setObjectName("joinrow")
    h = QHBoxLayout(f)
    h.setContentsMargins(10, 6, 12, 6)
    h.setSpacing(8)
    shown = []
    for i, nm in enumerate(names[:2]):
        if i:
            sep = QLabel("·")
            sep.setObjectName("muted")
            h.addWidget(sep)
        h.addWidget(Avatar(nm, 24, avatar_urls.get(nm, "")))
        lab = QLabel(f"<b>{html.escape(nm)}</b> bergabung")
        lab.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(lab, 1 if i else 0)
        shown.append(nm)
    return f


def gift_row(name, gift, count, image_url=""):
    f = QFrame()
    f.setObjectName("giftrow")
    h = QHBoxLayout(f)
    h.setContentsMargins(10, 8, 12, 8)
    h.setSpacing(10)
    h.addWidget(Avatar(name, 30, avatar_urls.get(name, "")))
    # gambar gift (mis. mawar) dimuat asinkron dari cache
    if image_url:
        gif = QLabel()
        gif.setFixedSize(44, 44)
        gif.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def _apply(pm, lab=gif):
            lab.setPixmap(pm.scaled(44, 44,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation))

        IMG_CACHE = get_img_cache()
        IMG_CACHE.get(image_url, _apply)
        h.addWidget(gif)
    col = QVBoxLayout()
    col.setSpacing(0)
    n = QLabel(f"<b>{html.escape(name)}</b>")
    n.setTextFormat(Qt.TextFormat.RichText)
    s = QLabel(f"mengirim {gift}")
    s.setObjectName("muted")
    col.addWidget(n)
    col.addWidget(s)
    h.addLayout(col, 1)
    c = QLabel(f"x{count}")
    c.setObjectName("count")
    h.addWidget(c)
    return f


# --------------------------------------------------------------------------
# Dialog pengaturan (menu gear)
# --------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, main):
        super().__init__(None)  # jendela independen, bukan child form utama
        self.main = main
        c = main.cfg
        self.setWindowTitle("Pengaturan")
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedWidth(340)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # --- title bar ala form utama (hanya minimize & close)
        tb = QWidget()
        tb.setObjectName("titlebar")
        tb.setFixedHeight(42)
        th = QHBoxLayout(tb)
        th.setContentsMargins(14, 0, 10, 0)
        th.setSpacing(6)
        title = QLabel("Pengaturan")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setText("<b>Pengaturan</b>")
        th.addWidget(title, 1)
        th.addWidget(self._tbtn("–", self.showMinimized))
        th.addWidget(self._tbtn("✕", self.close, "close"))
        v.addWidget(tb)

        body = QVBoxLayout()
        body.setContentsMargins(18, 14, 18, 18)
        body.setSpacing(8)
        v.addLayout(body, 1)

        body.addWidget(self._sec("Username TikTok"))
        row = QHBoxLayout()
        self.user = QLineEdit(c["username"])
        self.user.setPlaceholderText("contoh: kahfi_live (tanpa @)")
        self.btn = QPushButton()
        self.btn.setObjectName("primary")
        row.addWidget(self.user, 1)
        row.addWidget(self.btn)
        body.addLayout(row)
        self.btn.clicked.connect(lambda: main.toggle_connect(self.user.text()))
        self.user.returnPressed.connect(lambda: main.toggle_connect(self.user.text()))

        self._slider(body, "Transparansi jendela", 30, 100, c["opacity"], "%", main.set_opacity)
        hint = QLabel("Panel gift dan komentar tetap solid.")
        hint.setObjectName("muted")
        body.addWidget(hint)
        self._slider(body, "Ukuran font", 10, 24, c["font_size"], " px", main.set_font)

        body.addWidget(self._sec("Jenis font"))
        from PySide6.QtGui import QFontDatabase
        self.font_combo = QComboBox()
        families = QFontDatabase.families()
        self.font_combo.addItems(families)
        cur = c.get("font_family", "Segoe UI")
        if cur not in families:
            cur = "Segoe UI"
        self.font_combo.setCurrentText(cur)
        self.font_combo.currentTextChanged.connect(main.set_font_family)
        body.addWidget(self.font_combo)

        body.addWidget(self._sec("Satuan kecepatan jaringan"))
        srow = QHBoxLayout()
        sgroup = QButtonGroup(self)
        for key, label in (("kbps", "Kbps"), ("mbps", "Mbps"), ("MBps", "MBps")):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(c.get("speed_unit", "kbps") == key)
            sgroup.addButton(b)
            b.clicked.connect(lambda _=False, k=key: main.set_speed_unit(k))
            srow.addWidget(b)
        body.addLayout(srow)

        body.addWidget(self._sec("Tema"))
        trow = QHBoxLayout()
        group = QButtonGroup(self)
        for key, label in (("light", "Terang"), ("dark", "Gelap")):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(c["theme"] == key)
            group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: main.set_theme(k))
            trow.addWidget(b)
        body.addLayout(trow)

        self.refresh()

    def _tbtn(self, text, slot, name="tbtn"):
        b = QPushButton(text)
        b.setObjectName("close" if name == "close" else "tbtn")
        b.setFixedSize(32, 32)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def mousePressEvent(self, e):
        # drag jendela dari title bar
        if (e.button() == Qt.MouseButton.LeftButton and e.position().y() < 42
                and self.windowHandle()):
            self.windowHandle().startSystemMove()
        super().mousePressEvent(e)

    def _sec(self, text):
        lab = QLabel(f"<b>{text}</b>")
        lab.setTextFormat(Qt.TextFormat.RichText)
        return lab

    def _slider(self, layout, title, lo, hi, val, suffix, cb):
        head = QHBoxLayout()
        head.addWidget(self._sec(title))
        value = QLabel(f"{val}{suffix}")
        value.setObjectName("muted")
        head.addStretch(1)
        head.addWidget(value)
        layout.addLayout(head)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)

        def changed(x):
            value.setText(f"{x}{suffix}")
            cb(x)

        s.valueChanged.connect(changed)
        layout.addWidget(s)

    def refresh(self):
        self.btn.setText("Putus" if self.main.is_live_running() else "Hubungkan")


# --------------------------------------------------------------------------
# Jendela utama
# --------------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        self.worker = None
        self.settings = None
        self.visitors = {}   # semua yang pernah mampir: name -> waktu pertama
        self.first_seen = {} # waktu pertama masuk (untuk urutan & durasi menonton)
        self.gifters = {}    # pemberi gift: name -> total gift
        self.joined = {}
        self._join_queue = []
        self.status_text, self.status_ok = "Belum terhubung", False

        self.setWindowTitle("TikTok Live Reader")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(400, 820)
        self.setMinimumSize(340, 520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("frame")
        outer.addWidget(self.frame)
        root = QVBoxLayout(self.frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- title bar
        tb = QWidget()
        tb.setObjectName("titlebar")
        tb.setFixedHeight(TITLE_H)
        th = QHBoxLayout(tb)
        th.setContentsMargins(12, 0, 10, 0)
        th.setSpacing(6)
        gear = self._tbtn("⚙", self.open_settings)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        th.addWidget(gear)
        th.addWidget(self.title, 1)
        self.pin_btn = self._tbtn("📌", self.toggle_pin)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Selalu di atas")
        th.addWidget(self.pin_btn)
        th.addWidget(self._tbtn("–", self.showMinimized))
        th.addWidget(self._tbtn("□", self.toggle_max))
        th.addWidget(self._tbtn("✕", self.close, "close"))
        root.addWidget(tb)

        # --- baris ikon mata / orang / gift dengan counter, di bawah title bar
        icons = QHBoxLayout()
        icons.setContentsMargins(14, 4, 14, 0)
        icons.setSpacing(4)
        self.eye_btn = self._ibtn("👁")
        self.eye_btn.clicked.connect(lambda: self._show_popup("👁 Penonton aktif", {n: time.time() - t for n, t in self.joined.items()}))
        self.eye_count = self._count_label("0")
        icons.addWidget(self.eye_btn)
        icons.addWidget(self.eye_count)
        icons.addSpacing(8)
        self.people_btn = self._ibtn("👥")
        self.people_btn.clicked.connect(lambda: self._show_popup("👥 Pernah mampir", {n: time.time() - t for n, t in self.first_seen.items()}))
        self.people_count = self._count_label("0")
        icons.addWidget(self.people_btn)
        icons.addWidget(self.people_count)
        icons.addSpacing(8)
        self.gift_btn = self._ibtn("🎁")
        self.gift_btn.clicked.connect(lambda: self._show_popup("🎁 Pemberi gift", dict(self.gifters)))
        self.gift_count = self._count_label("0")
        icons.addWidget(self.gift_btn)
        icons.addWidget(self.gift_count)
        icons.addSpacing(8)
        # kecepatan jaringan (up/down) di samping ikon gift
        self.net_label = QLabel("⬆ --  ⬇ --")
        self.net_label.setObjectName("muted")
        icons.addWidget(self.net_label)
        icons.addStretch(1)
        root.addLayout(icons)

        # --- body
        body = QVBoxLayout()
        body.setContentsMargins(14, 8, 14, 6)
        body.setSpacing(8)

        # panel yang bisa di-geser (gift / bergabung / komentar) pakai splitter
        gift_panel = QWidget()
        gv = QVBoxLayout(gift_panel)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(0)
        self.gifts = Feed(newest_top=True, limit=40)
        gv.addWidget(self.gifts)

        join_panel = QWidget()
        jv = QVBoxLayout(join_panel)
        jv.setContentsMargins(0, 0, 0, 0)
        jv.setSpacing(0)
        self.joins = Feed(newest_top=True, limit=12)
        jv.addWidget(self.joins)

        comment_panel = QWidget()
        cv = QVBoxLayout(comment_panel)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.comments = Feed(newest_top=True, limit=200)
        cv.addWidget(self.comments, 1)

        # splitter vertikal: garis antar panel bisa digeser untuk atur ukuran
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.setObjectName("split")
        splitter.addWidget(gift_panel)
        splitter.addWidget(join_panel)
        splitter.addWidget(comment_panel)
        splitter.setStretchFactor(2, 1)
        body.addWidget(splitter, 1)

        foot = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("muted")
        foot.addWidget(self.footer, 1)
        foot.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        body.addLayout(foot)
        root.addLayout(body, 1)

        self._join_timer = QTimer(self)
        self._join_timer.setSingleShot(True)
        self._join_timer.timeout.connect(self._flush_joins)
        # auto-hapus penonton yang sudah keluar live (tidak aktif 3 menit)
        self._sweep_timer = QTimer(self)
        self._sweep_timer.timeout.connect(self._sweep_viewers)
        self._sweep_timer.start(15000)
        # pemantau kecepatan jaringan (upstream/downstream) via psutil
        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(self._update_net_speed)
        self._net_timer.start(1000)
        self._last_net = psutil.net_io_counters() if psutil else None
        self._last_net_time = time.time()
        self.apply_style()
        self.set_status(self.status_text, False)

    # ---- kecepatan jaringan
    def _update_net_speed(self):
        """Hitung upstream/downstream (bit/s) sejak update terakhir."""
        if not psutil or not self._last_net:
            self.net_label.setText("⬆ --  ⬇ --")
            return
        now = psutil.net_io_counters()
        t = time.time()
        dt = max(t - self._last_net_time, 0.001)
        down = (now.bytes_recv - self._last_net.bytes_recv) / dt  # Bytes/s
        up = (now.bytes_sent - self._last_net.bytes_sent) / dt    # Bytes/s
        self._last_net, self._last_net_time = now, t
        unit = self.cfg.get("speed_unit", "kbps")
        self.net_label.setText(f"⬆ {fmt_speed(up, unit)}  ⬇ {fmt_speed(down, unit)}")

    def set_speed_unit(self, unit):
        self.cfg["speed_unit"] = unit
        save_settings(self.cfg)
        self._update_net_speed()

    # ---- helpers UI
    def _tbtn(self, text, slot, name="tbtn"):
        b = QPushButton(text)
        b.setObjectName("close" if name == "close" else "tbtn")
        b.setFixedSize(32, 32)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _section(self, text):
        lab = QLabel(text)
        lab.setObjectName("section")
        return lab

    def _ibtn(self, text):
        """Tombol ikon kecil (mata/orang/gift) di baris bawah title bar."""
        b = QPushButton(text)
        b.setObjectName("tbtn")
        b.setFixedSize(30, 26)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _count_label(self, text):
        lab = QLabel(text)
        lab.setObjectName("muted")
        lab.setStyleSheet("font-size:12px;font-weight:700;")
        return lab

    def _show_popup(self, title, items):
        """Popup daftar user (nama + info) saat ikon mata/orang/gift diklik."""
        t = THEMES[self.cfg["theme"]]
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        dlg.setStyleSheet(self.styleSheet() + """
            QDialog {{ background:%s; border:1px solid %s; border-radius:12px; }}
            QLabel {{ background:transparent; }}""" % (t['panel'], t['border']))
        dlg.resize(260, 40)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(4)
        head = QLabel(f"<b>{title} ({len(items)})</b>")
        head.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(head)
        if not items:
            empty = QLabel("(belum ada)")
            empty.setObjectName("muted")
            v.addWidget(empty)
        else:
            is_eye = title.startswith("👁")
            is_gift = title.startswith("🎁")
            for name, info in sorted(items.items(), key=lambda kv: -kv[1]):
                if is_gift:
                    row = QLabel(f"{html.escape(name)} — <b>x{int(info)}</b>")
                else:
                    label = "Menonton" if is_eye else "Mampir"
                    row = QLabel(f"{html.escape(name)} <span style='color:{t['muted']}'>· {label} {fmt_dur(max(info, 0))}</span>")
                row.setTextFormat(Qt.TextFormat.RichText)
                row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                v.addWidget(row)
        dlg.adjustSize()
        btn = self.sender()
        if not isinstance(btn, QWidget):
            btn = self.eye_btn
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 4))
        pos.setX(max(10, pos.x() - dlg.width() + btn.width()))
        dlg.move(pos)
        dlg.show()

    def toggle_pin(self):
        """Selalu di atas (always on top) on/off."""
        flags = self.windowFlags()
        on = not bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.pin_btn.setChecked(on)
        self.pin_btn.setToolTip("Selalu di atas: " + ("AKTIF" if on else "nonaktif"))

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton and e.position().y() < TITLE_H
                and not self.isMaximized() and self.windowHandle()):
            self.windowHandle().startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < TITLE_H:
            self.toggle_max()
        super().mouseDoubleClickEvent(e)

    # ---- tema / pengaturan
    def apply_style(self):
        t = THEMES[self.cfg["theme"]]
        alpha = int(self.cfg["opacity"] * 2.55)
        fs = int(self.cfg["font_size"])
        ff = self.cfg.get("font_family", "Segoe UI").replace("'", "")
        self.setStyleSheet(f"""
        * {{ font-family:'{ff}','Segoe UI',sans-serif; font-size:{fs}px; color:{t['text']}; }}
        QFrame#frame {{ background:rgba({t['bg']},{alpha}); border:1px solid {t['border']}; border-radius:16px; }}
        QWidget#titlebar {{ background:transparent; }}
        QLabel {{ background:transparent; }}
        QLabel#section {{ font-weight:700; }}
        QLabel#muted {{ color:{t['muted']}; font-size:{max(fs - 2, 9)}px; }}
        QLabel#count {{ color:{t['accent']}; font-weight:700; }}
        QSplitter::handle {{ background:{t['border']}; }}
        QSplitter::handle:hover {{ background:{t['accent']}; }}
        QSplitter::handle:vertical {{ height:2px; margin:0 8px; border-radius:1px; }}
        QPushButton#tbtn, QPushButton#close {{ background:transparent; border:none; border-radius:8px; }}
        QPushButton#tbtn:hover {{ background:{t['panel2']}; }}
        QPushButton#close:hover {{ background:{t['accent2']}; color:#FFFFFF; }}
        QScrollArea#feed {{ background:{t['panel']}; border-radius:12px; }}
        QScrollArea#feed QWidget#inner {{ background:transparent; }}
        QFrame#giftrow {{ background:{t['panel2']}; border-radius:10px; }}
        QFrame#joinrow {{ background:transparent; border:none; }}
        QToolTip {{ background:{t['panel2']}; color:{t['text']}; border:1px solid {t['border']}; padding:6px 8px; }}
        QDialog {{ background:{t['panel']}; }}
        QLineEdit {{ background:{t['input']}; border:1px solid {t['border']}; border-radius:8px; padding:7px 10px; }}
        QLineEdit:focus {{ border:1px solid {t['accent']}; }}
        QComboBox {{ background:{t['input']}; border:1px solid {t['border']}; border-radius:8px; padding:6px 10px; color:{t['text']}; }}
        QComboBox:hover {{ border:1px solid {t['accent']}; }}
        QComboBox QAbstractItemView {{ background:{t['panel2']}; color:{t['text']}; border:1px solid {t['border']}; selection-background-color:{t['accent2']}; selection-color:#FFFFFF; }}
        QPushButton#primary {{ background:{t['accent2']}; color:#FFFFFF; border:none; border-radius:8px; padding:8px 14px; font-weight:600; }}
        QPushButton#seg {{ background:{t['panel2']}; border:none; border-radius:8px; padding:8px; }}
        QPushButton#seg:checked {{ background:{t['accent2']}; color:#FFFFFF; font-weight:600; }}
        QSlider::groove:horizontal {{ height:6px; background:{t['panel2']}; border-radius:3px; }}
        QSlider::sub-page:horizontal {{ background:{t['accent2']}; border-radius:3px; }}
        QSlider::handle:horizontal {{ background:{t['accent2']}; width:16px; margin:-5px 0; border-radius:8px; }}
        QScrollBar:vertical {{ width:8px; background:transparent; margin:0; }}
        QScrollBar::handle:vertical {{ background:{t['border']}; border-radius:4px; min-height:24px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self.refresh_title()

    def set_opacity(self, v):
        self.cfg["opacity"] = v
        self.apply_style()
        save_settings(self.cfg)

    def set_font(self, v):
        self.cfg["font_size"] = v
        self.apply_style()
        save_settings(self.cfg)

    def set_theme(self, name):
        self.cfg["theme"] = name
        self.apply_style()
        save_settings(self.cfg)

    def set_font_family(self, family):
        self.cfg["font_family"] = family
        self.apply_style()
        save_settings(self.cfg)

    def open_settings(self):
        if self.settings is None:
            self.settings = SettingsDialog(self)
        self.settings.refresh()
        self.settings.move(self.mapToGlobal(QPoint(30, 60)))
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    # ---- status
    def refresh_title(self):
        t = THEMES[self.cfg["theme"]]
        color = "#3DDC84" if self.status_ok else t["accent2"]
        self.title.setText(
            f'<span style="color:{color}">●</span>&nbsp; <b>{html.escape(self.status_text)}</b>'
        )

    def set_status(self, text, ok):
        self.status_text, self.status_ok = text, ok
        self.refresh_title()
        self.footer.setText(text)
        if self.settings:
            self.settings.refresh()

    def is_live_running(self):
        return bool(self.worker and self.worker.isRunning())

    # ---- koneksi
    def toggle_connect(self, username):
        if self.is_live_running():
            self.worker.stop()
            self.worker.wait(6000)
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(2000)
            self.set_status("Terputus", False)
            return
        username = username.strip().lstrip("@")
        if not username:
            self.set_status("Isi username TikTok dulu", False)
            return
        self.cfg["username"] = username
        save_settings(self.cfg)
        self.worker = TikTokWorker(username)
        self.worker.comment.connect(self.on_comment)
        self.worker.gift.connect(self.on_gift)
        self.worker.joined.connect(self.on_join)
        self.worker.status.connect(self.set_status)
        self.set_status(f"Menghubungkan ke @{username}...", False)
        self.worker.start()
        if self.settings:
            self.settings.btn.setText("Putus")

    # ---- event masuk
    def on_join(self, name, avatar=""):
        if name not in self.joined and avatar:
            avatar_urls[name] = avatar
        if name in self.joined:
            return
        self.joined[name] = time.time()
        self.eye_count.setText(str(len(self.joined)))
        if name not in self.first_seen:
            self.first_seen[name] = time.time()
        if name not in self.visitors:
            self.visitors[name] = time.time()
            self.people_count.setText(str(len(self.visitors)))
        # antre baris "bergabung" di feed komentar; 2 orang digabung satu baris
        self._join_queue.append(name)
        self._join_timer.start(500)

    def _flush_joins(self):
        if not self._join_queue:
            return
        names = self._join_queue[:2]
        del self._join_queue[:2]
        self.joins.add(join_row(names))

    def _sweep_viewers(self):
        """Hapus avatar penonton yang sudah keluar live (tidak terlihat 3 menit)."""
        now = time.time()
        gone = [n for n, t in self.joined.items() if now - t > 180]
        if not gone:
            return
        for n in gone:
            del self.joined[n]
        self.eye_count.setText(str(len(self.joined)))

    def on_comment(self, name, text, avatar=""):
        # Log diagnosis: event sampai di UI thread
        print(f"[COMMENT-UI]   {time.strftime('%H:%M:%S')} user={name!r} text={text!r}",
              flush=True)
        if name in self.joined:
            self.joined[name] = time.time()  # masih aktif
        else:
            self.on_join(name, avatar)
        self.comments.add(comment_row(name, text), highlight=True)
        # Log diagnosis: widget benar2 sudah dimasukkan ke feed
        print(f"[COMMENT-ADD]  {time.strftime('%H:%M:%S')} "
              f"total_widget={self.comments.box.count() - 1} "
              f"scrolled_bottom={self.comments.verticalScrollBar().value() >= self.comments.verticalScrollBar().maximum() - 2}",
              flush=True)

    def on_gift(self, name, gift, count, image=""):
        if name in self.joined:
            self.joined[name] = time.time()  # masih aktif
        else:
            self.on_join(name, avatar_urls.get(name, ""))
        self.gifters[name] = self.gifters.get(name, 0) + count
        self.gift_count.setText(str(len(self.gifters)))
        self.gifts.add(gift_row(name, gift, count, image))

    # ---- tutup
    def closeEvent(self, e):
        if self.is_live_running():
            self.worker.stop()
            self.worker.wait(6000)
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(2000)
        save_settings(self.cfg)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    # icon aplikasi (taskbar & window) dari 1.png di samping script/exe
    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "1.png"
    if not icon_path.exists():
        icon_path = Path.cwd() / "1.png"
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
