import sys
import os
import requests
import re
import dbus
import subprocess
import math
import time
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QFont, QFontDatabase, QColor, QFontMetrics
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                             QListWidget, QListWidgetItem, QLabel, QAbstractItemView, 
                             QScroller, QHBoxLayout, QSizePolicy, QStackedWidget)

# === НАСТРОЙКИ ===
FONT_URL = "https://github.com/Hazzz895/ExteraPluginsAssets/raw/refs/heads/dev/lyrics/fonts/YSMusic-Bold.ttf"
FONT_NAME = "YSMusic-Bold.ttf"
LRCLIB_API = "https://lrclib.net/api/get"
NETEASE_SEARCH_API = "http://music.163.com/api/search/pc"
NETEASE_LYRIC_API = "http://music.163.com/api/song/lyric"

SCROLL_SPEED = 600
OFFSET_MS = 200
BACKGROUND_OPACITY = 0.6
SPACER_HEIGHT = 90

# === ПОТОК ЗАГРУЗКИ (MULTI-SOURCE) ===
class LyricsFetcher(QThread):
    lyrics_found = pyqtSignal(dict)
    
    def __init__(self, artist, title):
        super().__init__()
        self.artist = artist
        self.title = title
        self._is_running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        }

    def run(self):
        # 1. LRCLIB
        data = self.fetch_lrclib()
        
        # 2. NetEase (если LRCLIB пуст)
        if self._is_running:
            if not data or not data.get('syncedLyrics'):
                ncm_data = self.fetch_netease()
                if ncm_data:
                    data = ncm_data

        if self._is_running:
            self.lyrics_found.emit(data if data else {})

    def fetch_lrclib(self):
        try:
            params = {'artist_name': self.artist, 'track_name': self.title}
            resp = requests.get(LRCLIB_API, params=params, headers=self.headers, timeout=3)
            if resp.status_code == 200:
                j = resp.json()
                if isinstance(j, list) and j:
                    return j[0]
                elif isinstance(j, dict):
                    return j
                else:
                    return {}
        except:
            return {}
        return {}

    def fetch_netease(self):
        try:
            query = f"{self.artist} {self.title}"
            search_resp = requests.post(
                NETEASE_SEARCH_API, 
                data={'s': query, 'offset': 0, 'limit': 1, 'type': 1}, 
                headers=self.headers, 
                timeout=3
            )
            if search_resp.status_code != 200:
                return {}
            
            songs = search_resp.json().get('result', {}).get('songs', [])
            if not songs:
                return {}
            
            lyric_resp = requests.get(
                NETEASE_LYRIC_API, 
                params={'os': 'pc', 'id': songs[0]['id'], 'lv': -1, 'kv': -1, 'tv': -1}, 
                headers=self.headers, 
                timeout=3
            )
            if lyric_resp.status_code == 200:
                lrc = lyric_resp.json().get('lrc', {}).get('lyric', '')
                if lrc:
                    return {'syncedLyrics': lrc, 'plainLyrics': None}
        except:
            return {}
        return {}

    def stop(self):
        self._is_running = False

# === UI COMPONENTS ===
class LyricItemWidget(QWidget):
    def __init__(self, text, font, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 10, 20, 10) 
        self.layout.setSpacing(0)
        self.label = QLabel(text)
        self.label.setFont(font)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background: transparent; color: #80ffffff;")
        self.layout.addWidget(self.label)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_active(self, active, active_font, passive_font):
        if active:
            self.label.setFont(active_font)
            self.label.setStyleSheet("background: transparent; color: #ffffff;")
        else:
            self.label.setFont(passive_font)
            self.label.setStyleSheet("background: transparent; color: #80ffffff;")

    def get_required_height(self, width):
        margins = self.layout.contentsMargins()
        available_width = width - margins.left() - margins.right()
        if available_width <= 0:
            return 60
        fm = QFontMetrics(self.label.font())
        rect = fm.boundingRect(0, 0, available_width, 0, Qt.TextFlag.TextWordWrap, self.label.text())
        return rect.height() + margins.top() + margins.bottom() + 5

class LyricsList(QListWidget):
    user_scrolled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scroll_locked = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(0)
        self.setStyleSheet("QListWidget { background: transparent; border: none; } QScrollBar { width: 0px; height: 0px; }")

    def wheelEvent(self, event):
        if not self.scroll_locked:
            self.user_scrolled.emit()
            super().wheelEvent(event)
        else:
            event.ignore()

    def resizeEvent(self, event):
        self.adjust_row_heights()
        super().resizeEvent(event)

    def adjust_row_heights(self):
        w = self.viewport().width()
        if w <= 0:
            return
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if isinstance(widget, LyricItemWidget):
                h = widget.get_required_height(w)
                if item.sizeHint().height() != h:
                    item.setSizeHint(QSize(0, h))

class BouncingDots(QWidget):
    def __init__(self, font, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dots = []
        self.base_font = QFont(font)
        self.base_font.setPointSize(35)
        for _ in range(3):
            lbl = QLabel("•")
            lbl.setFont(self.base_font)
            lbl.setStyleSheet("color: #90ffffff; background: transparent;") 
            self.layout.addWidget(lbl)
            self.dots.append(lbl)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.step = 0

    def start(self): 
        if not self.timer.isActive():
            self.timer.start(4)
            self.show()

    def stop(self):
        self.timer.stop()
        self.hide()

    def animate(self):
        self.step += 0.02 
        for i, dot in enumerate(self.dots):
            val = math.sin(self.step - (i * 0.6))
            offset = int(val * 30) if val > 0 else 0
            dot.setContentsMargins(0, 0, 0, offset)

    def set_active(self, active):
        color = "#ffffff" if active else "#90ffffff"
        size = 50 if active else 35
        f = QFont(self.base_font)
        f.setPointSize(size)
        for dot in self.dots:
            dot.setStyleSheet(f"color: {color}; background: transparent;")
            dot.setFont(f)

class InstrumentalSpacer(QWidget):
    def __init__(self, dots_font, timer_font, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addStretch()
        
        self.dots = BouncingDots(dots_font)
        self.layout.addWidget(self.dots, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.timer_lbl = QLabel("")
        f = QFont(timer_font)
        self.timer_lbl.setFont(f)
        self.timer_lbl.setStyleSheet("color: white;")
        self.layout.addWidget(self.timer_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self.timer_lbl.hide()
        
        self.status_lbl = QLabel("")
        f2 = QFont(dots_font)
        f2.setPointSize(24)
        self.status_lbl.setFont(f2)
        self.status_lbl.setStyleSheet("color: white;")
        self.status_lbl.setWordWrap(True)
        self.layout.addWidget(self.status_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.hide()
        
        self.layout.addStretch()
        self.is_active = False
        self.last_mode = None
        self.last_sec = -1

    def set_active(self, active):
        if not self.status_lbl.isHidden():
            active = True
        if self.is_active == active: return
        self.is_active = active
        self.dots.set_active(active)
        self.timer_lbl.setStyleSheet(f"color: {'#ffffff' if active else '#90ffffff'}; background: transparent;")

    def set_content(self, mode="dots", remaining_ms=0, text=""):
        sec = 0
        if mode == "timer":
            sec = math.ceil(remaining_ms / 1000)
            if self.last_mode == "timer" and self.last_sec == sec:
                return
        elif mode == self.last_mode and mode != "text":
            return
        
        self.last_mode = mode
        self.last_sec = sec

        self.dots.stop()
        self.timer_lbl.hide()
        self.status_lbl.hide()
        
        if mode == "dots":
            self.dots.start()
        elif mode == "timer":
            self.timer_lbl.setText(str(sec))
            self.timer_lbl.show()
        elif mode == "text":
            self.status_lbl.setText(text)
            self.status_lbl.show()

# === WORKER (MPRIS) ===
class MPRISWorker(QThread):
    track_changed = pyqtSignal(str, str, str)
    position_updated = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.bus = dbus.SessionBus()
        self.player_interface = None
        self.props_interface = None
        self.current_service_name = None
        self.last_full_name = ""
        self.last_update_time = time.time()

    def find_player(self):
        best = None
        try:
            for s in self.bus.list_names():
                if s.startswith('org.mpris.MediaPlayer2'):
                    score = 0
                    if 'yandex' in s.lower(): score += 50
                    if 'music' in s.lower(): score += 20
                    if 'chromium' in s.lower(): score += 10
                    try:
                        obj = self.bus.get_object(s, '/org/mpris/MediaPlayer2')
                        props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
                        status = props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
                        
                        if status == 'Playing':
                            score += 1000
                        elif status == 'Paused':
                            score += 10
                        
                        if best is None or score > best[1]:
                            best = (s, score, obj)
                    except:
                        continue
        except:
            pass
        return (best[0], best[2]) if best else (None, None)

    def run(self):
        while self.running:
            try:
                if not self.player_interface:
                    name, obj = self.find_player()
                    if name:
                        self.current_service_name = name
                        self.player_interface = dbus.Interface(obj, 'org.mpris.MediaPlayer2.Player')
                        self.props_interface = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
                        print(f"[INFO] Подключен: {name}")
                        # МЫ УБРАЛИ СБРОС self.last_full_name ЗДЕСЬ
                        # Это была причина бесконечного цикла

                if self.props_interface:
                    try:
                        meta = self.props_interface.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
                        
                        # --- БЕЗОПАСНЫЙ ПАРСИНГ ---
                        artist = "Unknown"
                        raw_artist = meta.get('xesam:artist')
                        
                        if isinstance(raw_artist, dbus.Array):
                            if len(raw_artist) > 0:
                                artist = str(raw_artist[0])
                        elif isinstance(raw_artist, list):
                            if len(raw_artist) > 0:
                                artist = str(raw_artist[0])
                        elif isinstance(raw_artist, str):
                            artist = raw_artist
                        
                        title = str(meta.get('xesam:title', 'Unknown'))
                        track_id = str(meta.get('mpris:trackid', ''))

                        if (not artist or artist == "Unknown") and (not title or title == "Unknown"):
                            self.msleep(100)
                            continue
                        
                        self.last_update_time = time.time()
                        full_name = f"{artist} - {title}"
                        
                        if full_name != self.last_full_name:
                            print(f"[INFO] Трек: {full_name}")
                            self.last_full_name = full_name
                            self.track_changed.emit(artist, title, track_id)
                            
                            self.msleep(150)
                            self.player_interface = None
                            self.props_interface = None
                            continue 

                        pos = self.props_interface.Get('org.mpris.MediaPlayer2.Player', 'Position')
                        self.position_updated.emit(int(pos / 1000))
                    except dbus.exceptions.DBusException:
                        self.player_interface = None
            except:
                self.player_interface = None
            self.msleep(100)

    def seek(self, position_ms):
        if not self.current_service_name:
            return
        try:
            player_bin = self.current_service_name.replace("org.mpris.MediaPlayer2.", "")
            s = str(position_ms / 1000.0)
            if position_ms == 0:
                s = "0.001"
            subprocess.run(["playerctl", "-p", player_bin, "position", s], check=False)
        except:
            pass

# === ГЛАВНОЕ ОКНО ===
class LyricsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Yandex Lyrics")
        self.resize(450, 750)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        bg_alpha = int(255 * BACKGROUND_OPACITY)
        self.setStyleSheet(f"QMainWindow {{ background: transparent; }} QWidget#CentralWidget {{ background-color: rgba(18, 18, 18, {bg_alpha}); border-radius: 20px; }} QListWidget::item {{ padding: 6px 0px; border: none; }} QListWidget::item:selected {{ background: transparent; }}")

        self.lyrics_data = [] 
        self.last_active_index = -1
        self.current_pos = 0
        self.is_error_state = False
        self.user_scrolling = False
        self.old_pos = None
        self.fetcher = None 
        self.is_outro = False 

        self.load_font()
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 20, 10, 20)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.list_widget = LyricsList()
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.user_scrolled.connect(self.on_user_scroll)
        self.list_widget.verticalScrollBar().sliderPressed.connect(self.on_user_scroll)
        QScroller.grabGesture(self.list_widget.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.stack.addWidget(self.list_widget)

        self.loading_container = QWidget()
        self.loading_layout = QVBoxLayout(self.loading_container)
        self.loading_layout.setContentsMargins(0,0,0,0)
        self.loading_layout.addStretch()
        self.status_widget = InstrumentalSpacer(self.active_font, self.timer_font)
        self.status_widget.set_active(True)
        self.loading_layout.addWidget(self.status_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        self.loading_layout.addStretch()
        self.stack.addWidget(self.loading_container)

        self.scroll_anim = QPropertyAnimation(self.list_widget.verticalScrollBar(), b"value")
        self.scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.scroll_anim.setDuration(SCROLL_SPEED)

        self.user_scroll_timer = QTimer()
        self.user_scroll_timer.setSingleShot(True)
        self.user_scroll_timer.timeout.connect(self.end_user_scroll)
        
        self.player_stalled_timer = QTimer()
        self.player_stalled_timer.setInterval(1000)
        self.player_stalled_timer.timeout.connect(self.check_player_alive)
        self.player_stalled_timer.start()

        self.worker = MPRISWorker()
        self.worker.track_changed.connect(self.on_track_changed)
        self.worker.position_updated.connect(self.on_position_update)
        self.worker.start()
        self.show_loading_view("dots")

    def load_font(self):
        if not os.path.exists(FONT_NAME):
            try:
                requests.get(FONT_URL)
            except:
                pass
            try:
                with open(FONT_NAME, 'wb') as f:
                    f.write(requests.get(FONT_URL).content)
            except:
                pass
        
        if os.path.exists(FONT_NAME):
            fid = QFontDatabase.addApplicationFont(FONT_NAME)
            fam = QFontDatabase.applicationFontFamilies(fid)[0] if fid != -1 else "Arial"
            self.active_font = QFont(fam, 26)
            self.active_font.setBold(True)
            self.passive_font = QFont(fam, 18)
            self.small_active_font = QFont(fam, 22)
            self.small_active_font.setBold(True)
            self.small_passive_font = QFont(fam, 14)
            self.timer_font = QFont(fam, 40)
            self.timer_font.setBold(True)
        else:
            self.active_font = QFont("Arial", 26, QFont.Weight.Bold)
            self.passive_font = QFont("Arial", 16)
            self.small_active_font = QFont("Arial", 20, QFont.Weight.Bold)
            self.small_passive_font = QFont("Arial", 14)
            self.timer_font = QFont("Arial", 40, QFont.Weight.Bold)

    def clean_query(self, text):
        text = re.sub(r"[\(\[].*?[\)\]]", "", text)
        text = text.replace("feat.", "").replace("ft.", "").replace("Official", "").strip()
        return text

    def on_user_scroll(self):
        if self.stack.currentIndex() == 1:
            return
        self.user_scrolling = True
        self.scroll_anim.stop()
        self.user_scroll_timer.start(5000)

    def end_user_scroll(self):
        self.user_scrolling = False
        if self.last_active_index != -1 and self.stack.currentIndex() == 0:
            self.update_visuals(self.lyrics_data[self.last_active_index]['list_idx'], force_scroll=True)

    def check_player_alive(self):
        if self.is_outro:
            return
        if time.time() - self.worker.last_update_time > 15:
             if self.stack.currentIndex() == 1:
                 if self.status_widget.status_lbl.isHidden():
                     self.status_widget.set_content("text", text="Проблема с треком ):")

    def show_loading_view(self, mode="dots", text=""):
        self.stack.setCurrentIndex(1)
        if mode == "dots":
            self.status_widget.set_content("dots")
        else:
            self.status_widget.set_content("text", text=text)

    def show_lyrics_view(self):
        self.stack.setCurrentIndex(0)
        self.list_widget.adjust_row_heights()

    def on_track_changed(self, artist, title, track_id):
        if self.fetcher and self.fetcher.isRunning():
            self.fetcher.stop()
            self.fetcher.wait()
            
        self.show_loading_view("dots")
        self.user_scrolling = False
        self.lyrics_data = []
        self.last_active_index = -1
        self.is_outro = False 
        
        clean_artist = self.clean_query(artist)
        clean_title = self.clean_query(title)
        
        self.fetcher = LyricsFetcher(clean_artist, clean_title)
        self.fetcher.lyrics_found.connect(self.on_lyrics_received)
        self.fetcher.start()

    def on_lyrics_received(self, data):
        self.list_widget.clear()
        self.list_widget.verticalScrollBar().setValue(0)
        
        if data.get('syncedLyrics'):
            self.parse_lrc(data['syncedLyrics'])
            self.show_lyrics_view()
        elif data.get('plainLyrics'):
            self.show_loading_view("text", text="Слова не синхронизированы ):\n\n" + data['plainLyrics'])
        else:
            self.show_loading_view("text", text="Слова не найдены ):")

    def parse_lrc(self, lrc):
        pad = 7
        for _ in range(pad):
            self.add_spacer()
        
        pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
        raw_lines = []
        for line in lrc.split('\n'):
            m = pattern.match(line)
            if m:
                ms = (int(m.group(1)) * 60 + float(m.group(2))) * 1000
                text = m.group(3).strip()
                if not text:
                    continue
                raw_lines.append({'time': ms, 'text': text})

        current_list_idx = pad
        if raw_lines and raw_lines[0]['time'] > 5500:
            intro_end = raw_lines[0]['time']
            spacer_item = QListWidgetItem()
            spacer_item.setSizeHint(QSize(0, SPACER_HEIGHT))
            spacer_item.setData(Qt.ItemDataRole.UserRole, 0)
            self.list_widget.addItem(spacer_item)
            
            spacer_widget = InstrumentalSpacer(self.active_font, self.timer_font)
            spacer_widget.set_content("empty")
            self.list_widget.setItemWidget(spacer_item, spacer_widget)
            
            self.lyrics_data.append({
                'time': 0, 'end_time': intro_end, 'type': 'instrumental', 
                'widget': spacer_widget, 'list_idx': current_list_idx
            })
            current_list_idx += 1

        for i, line in enumerate(raw_lines):
            self.lyrics_data.append({'time': line['time'], 'type': 'lyric', 'list_idx': current_list_idx})
            
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 60))
            item.setData(Qt.ItemDataRole.UserRole, line['time'])
            
            widget = LyricItemWidget(line['text'], self.passive_font)
            
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
            current_list_idx += 1

            if i < len(raw_lines) - 1:
                next_time = raw_lines[i+1]['time']
                delta = next_time - line['time']
                if delta > 5500:
                    duration = min(delta - 2000, max(2500, len(line['text']) * 150))
                    activation_time = line['time'] + duration
                    
                    spacer_item = QListWidgetItem()
                    spacer_item.setSizeHint(QSize(0, SPACER_HEIGHT))
                    spacer_item.setData(Qt.ItemDataRole.UserRole, line['time'] + duration)
                    self.list_widget.addItem(spacer_item)
                    
                    spacer_widget = InstrumentalSpacer(self.active_font, self.timer_font)
                    spacer_widget.set_content("empty")
                    self.list_widget.setItemWidget(spacer_item, spacer_widget)
                    
                    self.lyrics_data.append({
                        'time': activation_time, 'end_time': next_time, 
                        'type': 'instrumental', 'widget': spacer_widget, 'list_idx': current_list_idx
                    })
                    current_list_idx += 1

        last_time = raw_lines[-1]['time'] + 2000
        spacer_item = QListWidgetItem()
        spacer_item.setSizeHint(QSize(0, SPACER_HEIGHT))
        self.list_widget.addItem(spacer_item)
        
        end_widget = InstrumentalSpacer(self.active_font, self.timer_font)
        end_widget.set_content("empty")
        self.list_widget.setItemWidget(spacer_item, end_widget)
        
        self.lyrics_data.append({
            'time': last_time, 'end_time': 999999999, 'type': 'end_spacer', 
            'widget': end_widget, 'list_idx': current_list_idx
        })
        
        for _ in range(pad):
            self.add_spacer()
        self.list_widget.adjust_row_heights()

    def add_spacer(self):
        item = QListWidgetItem("")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(0, 60))
        self.list_widget.addItem(item)

    def on_position_update(self, pos_ms):
        if self.stack.currentIndex() != 0:
            return
        self.current_pos = pos_ms + OFFSET_MS
        if not self.lyrics_data:
            return

        active_idx = -1
        for i, entry in enumerate(self.lyrics_data):
            if entry['type'] in ['instrumental', 'end_spacer']:
                if self.current_pos >= entry['time']:
                     if i + 1 < len(self.lyrics_data):
                         if self.current_pos < self.lyrics_data[i+1]['time']:
                             active_idx = i
                             break
                     else:
                         active_idx = i
                         break      
            elif entry['type'] == 'lyric':
                next_time = float('inf')
                if i + 1 < len(self.lyrics_data):
                    next_time = self.lyrics_data[i+1]['time']
                if self.current_pos >= entry['time'] and self.current_pos < next_time:
                    active_idx = i
                    break

        last_instrumental_idx = -1
        for idx, entry in enumerate(self.lyrics_data):
            if entry['type'] == 'instrumental':
                last_instrumental_idx = idx

        for idx, entry in enumerate(self.lyrics_data):
            if entry['type'] == 'instrumental':
                is_playing_now = (self.current_pos >= entry['time'] and self.current_pos < entry['end_time'])
                remaining = entry['end_time'] - self.current_pos
                is_last_one = (idx == last_instrumental_idx)
                
                if is_playing_now:
                    # Таймер 3 секунды
                    if remaining <= 3000 and not is_last_one:
                         entry['widget'].set_content("timer", remaining_ms=remaining)
                    else:
                         entry['widget'].set_content("dots")
                else:
                     entry['widget'].set_content("empty")
            
            elif entry['type'] == 'end_spacer':
                if active_idx != -1 and self.lyrics_data[active_idx] == entry:
                    self.is_outro = True 
                    entry['widget'].set_content("dots")
                    if self.stack.currentIndex() == 0:
                        self.show_loading_view("dots")
                else:
                     self.is_outro = False 
                     entry['widget'].set_content("empty")
                     if self.stack.currentIndex() == 1 and active_idx != -1:
                         if self.status_widget.status_lbl.isHidden():
                             self.show_lyrics_view()

        if active_idx != -1:
            if active_idx != self.last_active_index:
                self.last_active_index = active_idx
                self.update_visuals(self.lyrics_data[active_idx]['list_idx'], force_scroll=not self.user_scrolling)

    def update_visuals(self, target_row, force_scroll=True):
        count = self.list_widget.count()
        if count == 0:
            return
        is_end_game = (self.lyrics_data and self.lyrics_data[-1]['list_idx'] == target_row)

        for i in range(count):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if is_end_game:
                item.setHidden(i != target_row)
            else:
                item.setHidden(False)

            if widget:
                is_active = (i == target_row)
                if isinstance(widget, InstrumentalSpacer):
                    widget.set_active(is_active)
                elif isinstance(widget, LyricItemWidget):
                    widget.set_active(is_active, self.active_font, self.passive_font)
                    if is_active:
                        new_h = widget.get_required_height(self.list_widget.viewport().width())
                        if item.sizeHint().height() != new_h:
                            item.setSizeHint(QSize(0, new_h))

        if force_scroll:
            item = self.list_widget.item(target_row)
            if item:
                rect = self.list_widget.visualItemRect(item)
                target_y = self.list_widget.verticalScrollBar().value() + rect.y() - (self.list_widget.viewport().height() // 2) + (rect.height() // 2)
                self.scroll_anim.stop()
                self.scroll_anim.setStartValue(self.list_widget.verticalScrollBar().value())
                self.scroll_anim.setEndValue(target_y)
                self.scroll_anim.start()

    def on_item_clicked(self, item):
        if self.is_error_state:
            return 
        ms = item.data(Qt.ItemDataRole.UserRole)
        if ms is None:
            return 
        self.user_scrolling = False
        self.user_scroll_timer.stop()
        self.update_visuals(self.list_widget.row(item), force_scroll=True)
        self.worker.seek(ms)

    def mousePressEvent(self, event):
        self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if not self.old_pos:
            return
        delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPosition().toPoint()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LyricsWindow()
    window.show()
    sys.exit(app.exec())

