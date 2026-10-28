from pathlib import Path
import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
PATHS = {
    "microphone": '<rect x="11" y="3" width="10" height="17" rx="5"/><path d="M7 15v2a9 9 0 0 0 18 0v-2M16 26v4M11 30h10"/>',
    "chevrons": '<path d="m11 12 5-5 5 5m-10 8 5 5 5-5"/>',
    "mouse": '<rect x="7" y="3" width="18" height="26" rx="9"/><path d="M16 4v8M8 13h16"/>',
    "keyboard": '<rect x="2" y="7" width="28" height="19" rx="4"/><path d="M7 12h1m4 0h1m4 0h1m4 0h1M7 17h1m4 0h1m4 0h1m4 0h1M10 22h12"/>',
    "controller": '<path d="M10 9h12a7 7 0 0 1 6.9 5.8l1 6.2a3.6 3.6 0 0 1-6.3 3L21 21h-10l-2.6 3a3.6 3.6 0 0 1-6.3-3l1-6.2A7 7 0 0 1 10 9z"/><path d="M9 13v5M6.5 15.5h5"/><circle cx="21" cy="14" r=".9" fill="COLOR"/><circle cx="24" cy="17" r=".9" fill="COLOR"/>',
    "headset": '<path d="M5 18v-3a11 11 0 0 1 22 0v3M7 26H6a3 3 0 0 1-3-3v-4a3 3 0 0 1 3-3h1zM25 26h1a3 3 0 0 0 3-3v-4a3 3 0 0 0-3-3h-1z"/>',
    "settings": '<path d="M6 8h20M6 16h20M6 24h20"/><circle cx="12" cy="8" r="3" fill="BACKGROUND"/><circle cx="22" cy="16" r="3" fill="BACKGROUND"/><circle cx="11" cy="24" r="3" fill="BACKGROUND"/>',
    "refresh": '<path d="M26 11A11 11 0 1 0 27 20M26 4v8h-8"/>',
    "close": '<path d="m9 9 14 14M23 9 9 23"/>',
    "back": '<path d="m19 7-9 9 9 9"/>',
    "power": '<path d="M16 3v12M9 7a12 12 0 1 0 14 0"/>',
    "tray": '<path d="M24 9A11 11 0 1 0 27 19"/><path d="M11 18v4m5-9v9m5-13v13"/><circle cx="27" cy="13" r="1.2" fill="COLOR" stroke="none"/>',
}


def _renderer(name: str, color: str, background="none", stroke=1.9) -> QSvgRenderer:
    shapes = PATHS.get(name, PATHS["mouse"]).replace("BACKGROUND", background).replace("COLOR", color)
    data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><g fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{shapes}</g></svg>'
    return QSvgRenderer(QByteArray(data.encode()))


def symbol(name: str, color: str, size=24, background="none") -> QIcon:
    renderer = _renderer(name, color, background)
    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(size*scale, size*scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def app_icon() -> QIcon:
    return QIcon(str(ROOT / "assets/app.svg"))


def ring_color(level: int, charging: bool) -> str:
    if charging or level > 50:
        return "#4cd38a"
    if level > 20:
        return "#f5b82e"
    return "#ff5a52"


def tray_icon(glyph: str, level: int | None, charging=False, show_number=False, dark_taskbar=True) -> QIcon:
    """托盘图标：外圈电量环 + 中间设备图标（或电量数字）"""
    fg = QColor("#ffffff" if dark_taskbar else "#1f2427")
    track = QColor(fg)
    track.setAlpha(70)
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(2.0, size * 0.13)
        rect = QRectF(width / 2, width / 2, size - width, size - width)

        painter.setPen(QPen(track, width))
        painter.drawEllipse(rect)
        if level is not None:
            pen = QPen(QColor(ring_color(level, charging)), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap if size >= 24 else Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            # 12 点方向起，顺时针
            painter.drawArc(rect, 90 * 16, -int(360 * 16 * max(0, min(level, 100)) / 100))

        inner = size - width * 2
        if show_number and level is not None:
            text = str(level)
            font = QFont("Segoe UI")
            font.setBold(True)
            font.setPixelSize(max(6, int(inner * (0.62 if len(text) < 3 else 0.46))))
            painter.setFont(font)
            painter.setPen(fg)
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
        else:
            g = inner * 0.78
            offset = (size - g) / 2
            stroke = 2.4 if size >= 32 else 3.0
            _renderer(glyph, fg.name(), stroke=stroke).render(painter, QRectF(offset, offset, g, g))
        painter.end()
        icon.addPixmap(pixmap)
    return icon
