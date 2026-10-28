# -*- coding: utf-8 -*-
"""我的外设电量监控窗口（动态设备与精美深色卡片）
支持：GPW3、瓦尔基里 MAG75 Max，以及 config.json 中配置的任何新设备
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

from drivers import create_driver
from drivers.base import BatteryReading

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "poll_interval_sec": 30,
            "devices": []
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_all_devices() -> List[BatteryReading]:
    cfg = load_config()
    results = []
    for dev in cfg.get("devices", []):
        if not dev.get("enabled", True):
            continue
        try:
            drv = create_driver(dev["driver"], dev["id"], dev["name"], dev.get("params", {}))
            res = drv.read_battery()
            results.append(res)
        except Exception as e:
            results.append(BatteryReading(
                device_id=dev.get("id", "unknown"),
                name=dev.get("name", "未知设备"),
                error=f"驱动加载异常: {e}"
            ))
    return results


# ==========================================================================
# 命令行测试
# ==========================================================================
def cli_once() -> None:
    results = read_all_devices()
    print("=" * 50)
    print("当前外设电量状态：")
    print("=" * 50)
    for r in results:
        if r.ok:
            charge = " [充电中]" if r.is_charging else ""
            print(f"[+] {r.name}: {r.level}% [{r.status}]{charge}")
            if r.detail:
                print(f"    详情: {r.detail}")
        else:
            print(f"[x] {r.name}: 读取失败 -> {r.error}")


# ==========================================================================
# UI 界面 (现代半透明深色卡片)
# ==========================================================================
BG = "#1b1c1f"
PANEL = "#232529"
PANEL2 = "#2b2e33"
FG = "#e8e8ea"
MUTED = "#9aa0a6"
FONT = ("Microsoft YaHei UI", 10)

LEVEL_STYLE = [
    (60, "#5ddc8a", "电量健康"),
    (30, "#f5c451", "电量中等"),
    (0,  "#ff6b6b", "电量偏低"),
]


def level_color(level: Optional[int]) -> str:
    if level is None:
        return MUTED
    for threshold, color, _ in LEVEL_STYLE:
        if level >= threshold:
            return color
    return LEVEL_STYLE[-1][1]


class DeviceCard:
    """一个设备卡片"""

    def __init__(self, parent, title: str):
        import tkinter as tk
        from tkinter import ttk

        self.frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        self.lab_title = ttk.Label(self.frame, text=title, style="CardTitle.TLabel")
        self.lab_title.pack(anchor="w")
        self.lab_sub = ttk.Label(self.frame, text="正在读取...", style="CardSub.TLabel")
        self.lab_sub.pack(anchor="w", pady=(2, 0))

        self.lab_level = ttk.Label(self.frame, text="--", style="CardBig.TLabel")
        self.lab_level.pack(anchor="w", pady=(10, 0))
        self.lab_status = ttk.Label(self.frame, text="", style="CardSub.TLabel")
        self.lab_status.pack(anchor="w")

        # 进度条
        self.canvas = tk.Canvas(self.frame, height=6, bg=PANEL2, highlightthickness=0)
        self.canvas.pack(fill="x", pady=(10, 4))
        self._bar = None

        self.lab_extra = ttk.Label(self.frame, text="", style="CardSub.TLabel")
        self.lab_extra.pack(anchor="w", pady=(4, 0))

    def update_view(self, r: BatteryReading) -> None:
        if r.ok:
            color = level_color(r.level)
            self.lab_level.config(text=f"{r.level}%", foreground=color)
            sub_text = r.status or "正常工作"
            if r.is_charging:
                sub_text += " (充电中 ⚡)"
            self.lab_sub.config(text=sub_text, foreground=color)
            self.lab_status.config(text=r.detail or "", foreground=MUTED)
            self.lab_extra.config(text="")

            # 绘制进度条
            w = self.canvas.winfo_width()
            if w <= 1:
                w = 200
            fill_w = max(0, min(w, int(w * (r.level / 100.0))))
            self.canvas.delete("all")
            self.canvas.create_rectangle(0, 0, fill_w, 6, fill=color, width=0)
        else:
            self.lab_level.config(text="--", foreground=MUTED)
            self.lab_sub.config(text="未连接 / 休眠", foreground=MUTED)
            self.lab_status.config(text=r.error or "设备无响应", foreground="#ff6b6b")
            self.lab_extra.config(text="")
            self.canvas.delete("all")


class MainApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.root.title("外设电量监控 (GPW3 + MAG75)")
        self.root.configure(bg=BG)
        self.root.geometry("420x460")
        self.root.minsize(380, 380)

        # 样式
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=FONT)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("CardTitle.TLabel", font=("Microsoft YaHei UI", 12, "bold"), foreground=FG, background=PANEL)
        style.configure("CardSub.TLabel", font=("Microsoft YaHei UI", 9), foreground=MUTED, background=PANEL)
        style.configure("CardBig.TLabel", font=("Microsoft YaHei UI", 26, "bold"), background=PANEL)

        # 头部
        top_frame = ttk.Frame(root, padding=(16, 16, 16, 8))
        top_frame.pack(fill="x")
        lab_header = ttk.Label(top_frame, text="外设电量实时监控", font=("Microsoft YaHei UI", 14, "bold"))
        lab_header.pack(side="left")

        self.btn_refresh = tk.Button(
            top_frame, text="刷新", bg=PANEL2, fg=FG, activebackground=PANEL,
            activeforeground=FG, bd=0, padx=12, pady=4, cursor="hand2",
            font=("Microsoft YaHei UI", 9), command=self.trigger_refresh
        )
        self.btn_refresh.pack(side="right")

        # 卡片容器
        self.cards_frame = ttk.Frame(root, padding=16)
        self.cards_frame.pack(fill="both", expand=True)

        self.cards: Dict[str, DeviceCard] = {}
        self.cfg = load_config()
        for dev in self.cfg.get("devices", []):
            if not dev.get("enabled", True):
                continue
            card = DeviceCard(self.cards_frame, dev["name"])
            card.frame.pack(fill="x", pady=6)
            self.cards[dev["id"]] = card

        # 底部状态栏
        bottom_frame = ttk.Frame(root, padding=(16, 8, 16, 12))
        bottom_frame.pack(fill="x", side="bottom")
        self.lab_time = ttk.Label(bottom_frame, text="就绪", font=("Microsoft YaHei UI", 8), foreground=MUTED)
        self.lab_time.pack(side="left")

        self.queue: queue.Queue = queue.Queue()
        self._closing = False

        # 启动后台刷新
        self.trigger_refresh()
        self.schedule_next_poll()
        self.check_queue()

    def schedule_next_poll(self):
        interval_ms = int(self.cfg.get("poll_interval_sec", 30)) * 1000
        self.root.after(interval_ms, self._on_timer)

    def _on_timer(self):
        if not self._closing:
            self.trigger_refresh()
            self.schedule_next_poll()

    def trigger_refresh(self):
        self.btn_refresh.config(state="disabled", text="读取中...")
        self.lab_time.config(text="正在与硬件通信...")
        threading.Thread(target=self._worker_read, daemon=True).start()

    def _worker_read(self):
        results = read_all_devices()
        self.queue.put(results)

    def check_queue(self):
        try:
            while True:
                results = self.queue.get_nowait()
                for r in results:
                    if r.device_id in self.cards:
                        self.cards[r.device_id].update_view(r)
                now_str = time.strftime("%H:%M:%S")
                self.lab_time.config(text=f"最后更新: {now_str} (每 30 秒自动刷新)")
                self.btn_refresh.config(state="normal", text="刷新")
        except queue.Empty:
            pass

        if not self._closing:
            self.root.after(200, self.check_queue)


def main():
    parser = argparse.ArgumentParser(description="我的外设电量查看器")
    parser.add_argument("--once", action="store_true", help="命令行只读一次并退出")
    args = parser.parse_args()

    if args.once:
        cli_once()
        return

    import tkinter as tk
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
