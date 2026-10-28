"""
电量岛 · ChargeDock
完美还原官方 Qt6 灵动岛悬浮卡片 UI，支持托盘展开、失去焦点自动隐藏、实时多线程电量轮询。
设备列表来自 config.json（修改后下次刷新自动生效），托盘图标显示电量最低的设备。
"""
import json
import os
import sys
import time
import winreg
from pathlib import Path
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, QEvent, QPoint
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QProgressBar, QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect,
    QScrollArea, QComboBox, QCheckBox
)

import discovery
from drivers import create_driver
from icons import symbol, app_icon, tray_icon

CONFIG_PATH = Path(__file__).parent / "config.json"

PALETTES = {
    "light": {
        "bg": "#f3f5f6", "card": "#ffffff", "text": "#20282a", "muted": "#5e6c70",
        "line": "#dce3e5", "accent": "#087c61", "tint": "#e6f4ee", "track": "#e7eeeb",
        "warning": "#a34b0a", "danger": "#c43933", "hover": "#e5eaec", "blue": "#1464d8"
    },
    "dark": {
        "bg": "#202629", "card": "#2c3438", "text": "#f2f5f5", "muted": "#aab7bc",
        "line": "#424e53", "accent": "#68dcb0", "tint": "#233d34", "track": "#424e49",
        "warning": "#ffbb70", "danger": "#ff8c87", "hover": "#394449", "blue": "#87b8ff"
    }
}

def system_theme() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


def taskbar_is_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return not winreg.QueryValueEx(key, "SystemUsesLightTheme")[0]
    except OSError:
        return True


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"poll_interval_sec": 30, "devices": []}


def save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def base_style(c: dict) -> str:
    return f"""
            QWidget {{ color:{c['text']}; font-family:'Segoe UI','Microsoft YaHei UI',sans-serif; font-size:11pt; }}
            QFrame#shell {{ background:{c['bg']}; border:1px solid {c['line']}; border-radius:22px; }}
            QFrame#deviceCard {{ background:{c['card']}; border-radius:15px; border: 1px solid {c['line']}; }}
            QLabel {{ background:transparent; border:0; }}
            QLabel[role='heading'] {{ font-size:17pt; font-weight:650; }}
            QLabel[role='section'] {{ font-size:10.5pt; font-weight:600; color:{c['muted']}; }}
            QLabel[role='deviceName'] {{ font-size:12pt; font-weight:600; }}
            QLabel[role='percentage'] {{ font-size:23pt; font-weight:600; }}
            QLabel[role='level'] {{ font-size:14pt; font-weight:600; }}
            QLabel[role='caption'] {{ font-size:9.5pt; color:{c['muted']}; }}
            QLabel#deviceGlyph {{ background:{c['bg']}; border-radius:12px; }}
            QPushButton#iconButton {{ background:transparent; border:1px solid transparent; border-radius:8px; padding:3px; }}
            QPushButton#iconButton:hover {{ background:{c['hover']}; border:1px solid {c['line']}; }}
            QPushButton#textButton {{ background:{c['card']}; border:1px solid {c['line']}; border-radius:8px; padding:4px 12px; font-size:10pt; }}
            QPushButton#textButton:hover {{ background:{c['hover']}; }}
            QPushButton#textButton:disabled {{ color:{c['muted']}; }}
            QPushButton#primaryButton {{ background:{c['accent']}; color:{c['bg']}; border:0; border-radius:8px; padding:5px 14px; font-size:10pt; font-weight:600; }}
            QPushButton#primaryButton:disabled {{ background:{c['track']}; color:{c['muted']}; }}
            QComboBox {{ background:{c['card']}; border:1px solid {c['line']}; border-radius:7px; padding:2px 8px; font-size:10pt; }}
            QComboBox QAbstractItemView {{ background:{c['card']}; color:{c['text']}; selection-background-color:{c['hover']}; }}
            QCheckBox {{ font-size:10pt; color:{c['muted']}; background:transparent; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; border:0; }}
            QToolTip {{ background:{c['card']}; color:{c['text']}; border:1px solid {c['line']}; padding:4px 8px; border-radius:6px; }}
    """


@dataclass
class DeviceReading:
    key: str
    title: str
    subtitle: str
    glyph: str  # mouse / keyboard / headset / controller
    level: int | None = None
    charging: bool = False
    status: str = "正在读取"
    error: str = ""
    updated: float = 0


class Worker(QThread):
    finished = Signal(dict)

    def __init__(self, drivers):
        super().__init__()
        self.drivers = drivers

    def run(self):
        results = {}
        for key, info in self.drivers.items():
            driver = info["driver"]
            try:
                res = driver.read_battery()
                results[key] = {
                    "ok": res.ok,
                    "level": res.level,
                    "charging": getattr(res, "is_charging", getattr(res, "charging", False)),
                    "status": res.status,
                    "error": res.error
                }
            except Exception as e:
                results[key] = {
                    "ok": False,
                    "level": None,
                    "charging": False,
                    "status": "读取异常",
                    "error": str(e)
                }
        self.finished.emit(results)


class DeviceCard(QFrame):
    def __init__(self, key: str, glyph_type: str, title_text: str, subtitle_text: str):
        super().__init__()
        self.key = key
        self.glyph_type = glyph_type
        self.setObjectName("deviceCard")
        self.setMinimumHeight(104)
        self.colors = PALETTES["light"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        # 顶行：图标 + 标题/副标题 + 右侧大百分比
        row = QHBoxLayout()
        row.setSpacing(12)

        self.glyph = QLabel()
        self.glyph.setObjectName("deviceGlyph")
        self.glyph.setFixedSize(44, 44)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.glyph)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self.title = QLabel(title_text)
        self.title.setProperty("role", "deviceName")
        self.subtitle = QLabel(subtitle_text)
        self.subtitle.setProperty("role", "caption")
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.subtitle)
        row.addLayout(text_layout, 1)

        self.percentage = QLabel("—")
        self.percentage.setProperty("role", "percentage")
        self.percentage.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.percentage)
        outer.addLayout(row)

        # 底行：进度条 + 状态文字
        lower = QHBoxLayout()
        lower.setSpacing(12)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        lower.addWidget(self.bar, 1)

        self.state_text = QLabel("正在读取")
        self.state_text.setProperty("role", "caption")
        self.state_text.setAlignment(Qt.AlignmentFlag.AlignRight)
        lower.addWidget(self.state_text)
        outer.addLayout(lower)

    def render(self, reading: DeviceReading, colors: dict):
        self.colors = colors
        c = colors
        self.glyph.setPixmap(symbol(self.glyph_type, c["text"], 22, c["bg"]).pixmap(24, 24))

        level = reading.level
        if level is not None:
            self.percentage.setText(f"{level}%")
            self.bar.setValue(level)
            low = level <= 20 and not reading.charging
            color = c["danger"] if low else c["accent"]
            self.bar.setStyleSheet(
                f"QProgressBar{{background:{c['track']};border:0;border-radius:2px;}}"
                f"QProgressBar::chunk{{background:{color};border-radius:2px;}}"
            )
            state = "正在充电" if reading.charging else ("电量偏低" if low else "已连接")
            self.state_text.setText(state)
            self.state_text.setStyleSheet(f"color:{color if low else c['muted']};")
        else:
            self.percentage.setText("—")
            self.bar.setValue(0)
            self.bar.setStyleSheet(
                f"QProgressBar{{background:{c['track']};border:0;border-radius:2px;}}"
                f"QProgressBar::chunk{{background:{c['muted']};border-radius:2px;}}"
            )
            status_desc = "等待唤醒" if "休眠" in reading.error or "未回复" in reading.error else (reading.status or "未连接")
            self.state_text.setText(status_desc)
            self.state_text.setStyleSheet(f"color:{c['muted']};")


class ChargeDockPanel(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.setWindowTitle("电量岛 · ChargeDock")
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(432)
        self.colors = PALETTES["light"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # 外壳卡片带阴影
        self.shell = QFrame()
        self.shell.setObjectName("shell")
        shadow = QGraphicsDropShadowEffect(self.shell)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 50))
        self.shell.setGraphicsEffect(shadow)
        layout.addWidget(self.shell)

        content = QVBoxLayout(self.shell)
        content.setContentsMargins(20, 18, 20, 17)
        content.setSpacing(14)

        # 头部导航
        header = QHBoxLayout()
        header.setSpacing(10)

        self.logo = QLabel()
        self.logo.setPixmap(app_icon().pixmap(32, 32))
        header.addWidget(self.logo)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.heading = QLabel("电量岛")
        self.heading.setProperty("role", "heading")
        self.tagline = QLabel("所有设备，一眼可见")
        self.tagline.setProperty("role", "caption")
        titles.addWidget(self.heading)
        titles.addWidget(self.tagline)
        header.addLayout(titles, 1)

        # 顶部操作按钮
        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("iconButton")
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setToolTip("添加 / 管理设备")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.controller.open_manager)
        header.addWidget(self.btn_settings)

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("iconButton")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setToolTip("收起窗口")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close)

        content.addLayout(header)

        # 设备卡片容器
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(10)
        self.cards = {}
        self.rebuild_cards()

        content.addLayout(self.cards_layout)

        # 底部栏：上次更新时间 + 刷新按钮
        footer = QHBoxLayout()
        self.updated_label = QLabel("正在读取设备电量...")
        self.updated_label.setProperty("role", "caption")
        footer.addWidget(self.updated_label, 1)

        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("iconButton")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setToolTip("立即刷新电量")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.controller.refresh)
        footer.addWidget(self.btn_refresh)

        content.addLayout(footer)

        # 自动收起计时器 (15秒)
        self.auto_dismiss = QTimer(self)
        self.auto_dismiss.setSingleShot(True)
        self.auto_dismiss.timeout.connect(self.check_auto_dismiss)

    def rebuild_cards(self):
        for card in self.cards.values():
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.cards = {}
        for key, r in self.controller.readings.items():
            card = DeviceCard(key, r.glyph, r.title, r.subtitle)
            self.cards[key] = card
            self.cards_layout.addWidget(card)

    def apply_theme(self):
        theme = system_theme()
        self.colors = PALETTES[theme]
        c = self.colors

        self.setStyleSheet(base_style(c))

        self.btn_settings.setIcon(symbol("plus", c["muted"], 18, c["bg"]))
        self.btn_close.setIcon(symbol("close", c["muted"], 18, c["bg"]))
        self.btn_refresh.setIcon(symbol("refresh", c["muted"], 18, c["bg"]))

        for card in self.cards.values():
            reading = self.controller.readings.get(card.key, DeviceReading(card.key, "", "", card.glyph_type))
            card.render(reading, c)

    def place(self):
        # 居中在屏幕右下角托盘上方
        screen = QApplication.primaryScreen()
        room = screen.availableGeometry()
        self.adjustSize()
        x = room.right() - self.width() - 8
        y = room.bottom() - self.height() - 8
        self.move(x, y)

    def reveal(self):
        self.apply_theme()
        self.place()
        self.show()
        self.raise_()
        self.activateWindow()
        self.auto_dismiss.start(15000)

    def check_auto_dismiss(self):
        if not self.underMouse():
            self.hide()
        else:
            self.auto_dismiss.start(3000)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            QTimer.singleShot(180, self.hide_if_inactive)
        super().changeEvent(event)

    def hide_if_inactive(self):
        if not self.isActiveWindow() and not self.underMouse():
            self.hide()


GLYPHS = [("mouse", "鼠标"), ("keyboard", "键盘"), ("headset", "耳机"), ("controller", "手柄")]


class DiscoverWorker(QThread):
    found = Signal(list)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            self.found.emit(discovery.discover(self.cfg))
        except Exception as e:
            print(f"[ChargeDock] 扫描失败: {e}")
            self.found.emit([])


class DeviceManagerWindow(QWidget):
    """添加 / 管理设备：扫描本机可读电量的设备，一键加入 config.json"""

    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.setWindowTitle("管理设备 · 电量岛")
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(472)
        self.colors = PALETTES["light"]
        self.candidates: list = []
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.shell = QFrame()
        self.shell.setObjectName("shell")
        shadow = QGraphicsDropShadowEffect(self.shell)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 50))
        self.shell.setGraphicsEffect(shadow)
        layout.addWidget(self.shell)

        content = QVBoxLayout(self.shell)
        content.setContentsMargins(20, 18, 20, 18)
        content.setSpacing(10)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        heading = QLabel("管理设备")
        heading.setProperty("role", "heading")
        tagline = QLabel("扫描本机外设，能读到电量的一键添加")
        tagline.setProperty("role", "caption")
        titles.addWidget(heading)
        titles.addWidget(tagline)
        header.addLayout(titles, 1)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("iconButton")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(420)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 4, 0)
        self.body.setSpacing(8)
        scroll.setWidget(body)
        content.addWidget(scroll)

        footer = QHBoxLayout()
        self.chk_unknown = QCheckBox("显示无法识别的设备")
        self.chk_unknown.toggled.connect(self.populate)
        footer.addWidget(self.chk_unknown, 1)
        self.btn_scan = QPushButton("重新扫描")
        self.btn_scan.setObjectName("textButton")
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self.scan)
        footer.addWidget(self.btn_scan)
        content.addLayout(footer)

    # ---------- 数据 ----------
    def cfg(self) -> dict:
        return load_config()

    def commit(self, cfg: dict):
        save_config(cfg)
        self.controller.reload_devices()
        self.populate()

    def scan(self):
        if self.worker and self.worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("扫描中…")
        self.candidates = []
        self.populate(scanning=True)
        self.worker = DiscoverWorker(self.cfg())
        self.worker.found.connect(self.on_found)
        self.worker.start()

    def on_found(self, candidates):
        self.candidates = candidates
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("重新扫描")
        self.populate()

    def add_candidate(self, cand, glyph: str):
        cfg = self.cfg()
        devices = cfg.setdefault("devices", [])
        entry = cand.to_config({d["id"] for d in devices})
        entry["glyph"] = glyph
        devices.append(entry)
        ignored = cfg.get("ignored_devices", [])
        if cand.key in ignored:
            ignored.remove(cand.key)
        self.candidates = [c for c in self.candidates if c.key != cand.key]
        self.commit(cfg)

    def ignore_candidate(self, cand):
        cfg = self.cfg()
        ignored = cfg.setdefault("ignored_devices", [])
        if cand.key not in ignored:
            ignored.append(cand.key)
        self.candidates = [c for c in self.candidates if c.key != cand.key]
        self.commit(cfg)

    def update_device(self, dev_id: str, **changes):
        cfg = self.cfg()
        for d in cfg.get("devices", []):
            if d["id"] == dev_id:
                d.update(changes)
        self.commit(cfg)

    def remove_device(self, dev_id: str):
        cfg = self.cfg()
        cfg["devices"] = [d for d in cfg.get("devices", []) if d["id"] != dev_id]
        self.commit(cfg)

    # ---------- 界面 ----------
    def section(self, text: str):
        label = QLabel(text)
        label.setProperty("role", "section")
        self.body.addWidget(label)

    def glyph_combo(self, current: str) -> QComboBox:
        combo = QComboBox()
        for key, label in GLYPHS:
            combo.addItem(symbol(key, self.colors["text"], 16), label, key)
        combo.setCurrentIndex(max(0, [k for k, _ in GLYPHS].index(current) if current in dict(GLYPHS) else 0))
        combo.setFixedWidth(84)
        return combo

    def row(self, glyph: str, title: str, caption: str, level=None) -> tuple[QFrame, QHBoxLayout]:
        """一行设备：上面是图标/名称/电量，下面是操作按钮（返回按钮所在的布局）"""
        c = self.colors
        frame = QFrame()
        frame.setObjectName("deviceCard")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)
        line = QHBoxLayout()
        line.setSpacing(10)
        outer.addLayout(line)
        icon = QLabel()
        icon.setObjectName("deviceGlyph")
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(symbol(glyph, c["text"], 20, c["bg"]).pixmap(20, 20))
        line.addWidget(icon)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel(title)
        name.setProperty("role", "deviceName")
        sub = QLabel(caption)
        sub.setProperty("role", "caption")
        sub.setWordWrap(True)
        texts.addWidget(name)
        texts.addWidget(sub)
        line.addLayout(texts, 1)
        if level is not None:
            lvl = QLabel(f"{level}%")
            lvl.setProperty("role", "level")
            line.addWidget(lvl)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addStretch(1)
        outer.addLayout(actions)
        self.body.addWidget(frame)
        return frame, actions

    def button(self, text: str, primary=False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("primaryButton" if primary else "textButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def populate(self, *_, scanning=False):
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cfg = self.cfg()

        self.section("已添加")
        devices = cfg.get("devices", [])
        if not devices:
            hint = QLabel("还没有设备，从下方扫描结果里添加吧")
            hint.setProperty("role", "caption")
            self.body.addWidget(hint)
        for d in devices:
            reading = self.controller.readings.get(d["id"])
            caption = d.get("subtitle") or d.get("driver", "")
            if not d.get("enabled", True):
                caption = "已隐藏 · " + caption
            _, line = self.row(d.get("glyph", "mouse"), d.get("title") or d.get("short_name") or d["name"],
                               caption, reading.level if reading else None)
            combo = self.glyph_combo(d.get("glyph", "mouse"))
            combo.currentIndexChanged.connect(lambda _, cb=combo, i=d["id"]: self.update_device(i, glyph=cb.currentData()))
            line.addWidget(combo)
            vis = self.button("隐藏" if d.get("enabled", True) else "显示")
            vis.clicked.connect(lambda _, i=d["id"], e=d.get("enabled", True): self.update_device(i, enabled=not e))
            line.addWidget(vis)
            rm = self.button("删除")
            rm.clicked.connect(lambda _, i=d["id"]: self.remove_device(i))
            line.addWidget(rm)

        self.section("发现的设备")
        ignored = set(cfg.get("ignored_devices", []))
        shown = [c for c in self.candidates
                 if c.key not in ignored and (c.supported or self.chk_unknown.isChecked())]
        if scanning:
            hint = QLabel("正在扫描蓝牙、耳机与 2.4G 接收器，并试读电量…")
        elif not shown:
            hint = QLabel("没有发现新的可读设备。确认设备已开机并连接后点「重新扫描」")
        else:
            hint = None
        if hint:
            hint.setProperty("role", "caption")
            hint.setWordWrap(True)
            self.body.addWidget(hint)
        for cand in shown:
            caption = f"{cand.source} · {cand.note}" if cand.note else cand.source
            _, line = self.row(cand.glyph, cand.name, caption, cand.level)
            if not cand.supported:
                continue
            combo = self.glyph_combo(cand.glyph)
            line.addWidget(combo)
            add = self.button("添加", primary=True)
            add.setToolTip("" if cand.readable else "暂未读到电量（设备可能在休眠），添加后会自动重试")
            add.clicked.connect(lambda _, c=cand, cb=combo: self.add_candidate(c, cb.currentData()))
            line.addWidget(add)
            ign = self.button("忽略")
            ign.clicked.connect(lambda _, c=cand: self.ignore_candidate(c))
            line.addWidget(ign)
        self.body.addStretch(1)

    def apply_theme(self):
        self.colors = PALETTES[system_theme()]
        self.setStyleSheet(base_style(self.colors))
        self.btn_close.setIcon(symbol("close", self.colors["muted"], 18, self.colors["bg"]))

    def reveal(self, candidates=None):
        self.apply_theme()
        if candidates is not None:
            self.candidates = candidates
        self.populate()
        room = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(room.right() - self.width() - 8, room.bottom() - self.height() - 8)
        self.show()
        self.raise_()
        self.activateWindow()
        if candidates is None:
            self.scan()


class ChargeDockController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.readings = {}
        self.drivers = {}
        self.cfg = {}
        self.config_mtime = None
        self.load_devices()

        # 创建托盘图标
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("电量岛 · ChargeDock")

        # 托盘右键菜单
        self.menu = QMenu()
        self.menu.addAction("展开电量岛", self.reveal)
        self.menu.addAction("立即刷新", self.refresh)
        self.menu.addAction("添加 / 管理设备", self.open_manager)
        self.menu.addSeparator()
        self.menu.addAction("打开设备配置 (config.json)", self.open_config_dir)
        self.menu.addSeparator()
        self.menu.addAction("退出", self.app.quit)
        self.tray.setContextMenu(self.menu)

        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        # 创建悬浮主面板
        self.panel = ChargeDockPanel(self)

        # 启动后台轮询工作线程
        self.worker = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh)
        self.poll_timer.start(int(self.cfg.get("poll_interval_sec", 30)) * 1000)

        # 设备管理窗口 + 后台自动发现新设备（启动 15 秒后一次，之后每 5 分钟）
        self.manager = DeviceManagerWindow(self)
        self.notified = set()
        self.pending_candidates = []
        self.discover_worker = None
        self.discover_timer = QTimer(self)
        self.discover_timer.timeout.connect(self.auto_discover)
        self.discover_timer.start(5 * 60 * 1000)
        QTimer.singleShot(15000, self.auto_discover)
        self.tray.messageClicked.connect(lambda: self.manager.reveal(self.pending_candidates or None))

        # 启动初次刷新
        self.refresh()

    def load_devices(self) -> bool:
        """读取 config.json 构建设备与驱动；文件未变化时返回 False"""
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self.config_mtime and self.drivers:
            return False
        self.config_mtime = mtime
        self.cfg = load_config()
        old = self.readings
        self.readings, self.drivers = {}, {}
        for dev in self.cfg.get("devices", []):
            if not dev.get("enabled", True):
                continue
            key = dev["id"]
            title = dev.get("title") or dev.get("short_name") or dev["name"]
            try:
                driver = create_driver(dev["driver"], key, dev["name"], dev.get("params", {}))
            except Exception as e:
                print(f"[ChargeDock] 设备 {key} 驱动加载失败: {e}")
                continue
            reading = DeviceReading(key, title, dev.get("subtitle", ""), dev.get("glyph", "mouse"))
            if key in old:
                reading.level, reading.charging, reading.updated = old[key].level, old[key].charging, old[key].updated
            self.readings[key] = reading
            self.drivers[key] = {"name": title, "driver": driver}
        return True

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.panel.isVisible():
                self.panel.hide()
            else:
                self.reveal()

    def reveal(self):
        self.panel.reveal()

    def refresh(self):
        if self.load_devices():
            self.on_devices_changed()
        if self.worker and self.worker.isRunning():
            return
        self.panel.updated_label.setText("正在读取中...")
        self.worker = Worker(self.drivers)
        self.worker.finished.connect(self.on_read_finished)
        self.worker.start()

    def on_read_finished(self, results):
        now = time.time()
        for key, res in results.items():
            if key in self.readings:
                r = self.readings[key]
                r.level = res.get("level")
                r.charging = res.get("charging", False)
                r.status = res.get("status", "")
                r.error = res.get("error", "")
                r.updated = now

        timestr = time.strftime("%H:%M:%S", time.localtime(now))
        self.panel.updated_label.setText(f"上次更新 {timestr}")

        # 刷新卡片与托盘提示
        self.panel.apply_theme()
        tip_lines = ["电量岛 · ChargeDock"]
        for key, r in self.readings.items():
            lvl = f"{r.level}%" if r.level is not None else "离线"
            tip_lines.append(f"{r.title}: {lvl}")
        self.tray.setToolTip("\n".join(tip_lines))
        self.update_tray_icon()

    def on_devices_changed(self):
        self.panel.rebuild_cards()
        self.panel.apply_theme()
        self.poll_timer.setInterval(int(self.cfg.get("poll_interval_sec", 30)) * 1000)
        self.update_tray_icon()

    def reload_devices(self):
        """设备管理窗口改动 config.json 后调用：立即重建并读一次电量"""
        self.refresh()

    def open_manager(self):
        self.panel.hide()
        self.manager.reveal()

    def auto_discover(self):
        if self.discover_worker and self.discover_worker.isRunning():
            return
        if self.manager.isVisible() or not self.cfg.get("auto_discover", True):
            return
        self.discover_worker = DiscoverWorker(load_config())
        self.discover_worker.found.connect(self.on_auto_discovered)
        self.discover_worker.start()

    def on_auto_discovered(self, candidates):
        ignored = set(self.cfg.get("ignored_devices", []))
        fresh = [c for c in candidates if c.readable and c.key not in ignored and c.key not in self.notified]
        if not fresh:
            return
        self.notified.update(c.key for c in fresh)
        self.pending_candidates = candidates
        names = "、".join(f"{c.name} {c.level}%" for c in fresh[:3])
        self.tray.showMessage("发现可读电量的新设备", f"{names}\n点击这里添加到电量岛",
                              QSystemTrayIcon.MessageIcon.Information, 8000)

    def update_tray_icon(self):
        online = [r for r in self.readings.values() if r.level is not None]
        if not online:
            self.tray.setIcon(app_icon())
            return
        lowest = min(online, key=lambda r: r.level)
        self.tray.setIcon(tray_icon(lowest.glyph, lowest.level, lowest.charging,
                                    bool(self.cfg.get("tray_show_number", False)), taskbar_is_dark()))

    def open_config_dir(self):
        import subprocess
        if CONFIG_PATH.exists():
            subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])
        else:
            subprocess.Popen(["explorer.exe", str(CONFIG_PATH.parent)])


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = ChargeDockController(app)
    # 启动时直接弹出一次展示给用户
    controller.reveal()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
