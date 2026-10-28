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
    QScrollArea
)

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
        self.btn_settings.setToolTip("打开设备配置目录 (config.json)")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.controller.open_config_dir)
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

        self.setStyleSheet(f"""
            QWidget {{ color:{c['text']}; font-family:'Segoe UI','Microsoft YaHei UI',sans-serif; font-size:11pt; }}
            QFrame#shell {{ background:{c['bg']}; border:1px solid {c['line']}; border-radius:22px; }}
            QFrame#deviceCard {{ background:{c['card']}; border-radius:15px; border: 1px solid {c['line']}; }}
            QLabel {{ background:transparent; border:0; }}
            QLabel[role='heading'] {{ font-size:17pt; font-weight:650; }}
            QLabel[role='deviceName'] {{ font-size:12pt; font-weight:600; }}
            QLabel[role='percentage'] {{ font-size:23pt; font-weight:600; }}
            QLabel[role='caption'] {{ font-size:9.5pt; color:{c['muted']}; }}
            QLabel#deviceGlyph {{ background:{c['bg']}; border-radius:12px; }}
            QPushButton#iconButton {{ background:transparent; border:1px solid transparent; border-radius:8px; padding:3px; }}
            QPushButton#iconButton:hover {{ background:{c['hover']}; border:1px solid {c['line']}; }}
            QToolTip {{ background:{c['card']}; color:{c['text']}; border:1px solid {c['line']}; padding:4px 8px; border-radius:6px; }}
        """)

        self.btn_settings.setIcon(symbol("settings", c["muted"], 18, c["bg"]))
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
        if self.worker and self.worker.isRunning():
            return
        if self.load_devices():
            self.panel.rebuild_cards()
            self.panel.apply_theme()
            self.poll_timer.setInterval(int(self.cfg.get("poll_interval_sec", 30)) * 1000)
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
