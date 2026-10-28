# -*- coding: utf-8 -*-
"""HeadsetControl 驱动：借用 https://github.com/Sapd/HeadsetControl 已整理好的耳机协议
支持 SteelSeries / Logitech / Corsair / HyperX / Razer 等几十款耳机。
需要 headsetcontrol.exe：放在 PATH 中，或放到本项目 tools/ 目录下，或在 params.exe 指定路径。
params:
    vid / pid    耳机（接收器）的 VID/PID，用于在多个耳机中挑出这一台
    exe          可选，headsetcontrol.exe 的完整路径
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .base import BaseDriver, BatteryReading

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent


def find_executable(custom: str = "") -> Optional[str]:
    if custom and Path(custom).exists():
        return custom
    for local in (ROOT / "tools" / "headsetcontrol.exe", ROOT / "headsetcontrol.exe"):
        if local.exists():
            return str(local)
    return shutil.which("headsetcontrol")


def query_devices(custom_exe: str = "", timeout: float = 8.0) -> list[dict]:
    """调用 headsetcontrol -b -o json，返回 devices 列表；未安装时抛 FileNotFoundError"""
    exe = find_executable(custom_exe)
    if not exe:
        raise FileNotFoundError("未找到 headsetcontrol.exe")
    proc = subprocess.run(
        [exe, "-b", "-o", "json"], capture_output=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    data = json.loads(proc.stdout.decode("utf-8", errors="ignore") or "{}")
    return data.get("devices", [])


def parse_battery(dev: dict) -> tuple[Optional[int], bool, str]:
    """返回 (电量, 是否充电, 状态说明)"""
    battery = dev.get("battery") or {}
    status = str(battery.get("status", ""))
    level = battery.get("level")
    charging = status == "BATTERY_CHARGING"
    if status in ("BATTERY_AVAILABLE", "BATTERY_CHARGING") and isinstance(level, int) and level >= 0:
        return min(level, 100), charging, "充电中" if charging else "正常使用"
    if status == "BATTERY_CHARGING":
        return None, True, "充电中"
    return None, False, "耳机未开机或未连接"


def _hex(value) -> int:
    try:
        return int(str(value), 16)
    except ValueError:
        return -1


class HeadsetcontrolDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        try:
            devices = query_devices(str(self.params.get("exe", "")))
        except FileNotFoundError as e:
            return BatteryReading(self.device_id, self.name, error=f"{e}（请下载放到 tools/ 目录）")
        except Exception as e:
            return BatteryReading(self.device_id, self.name, error=f"HeadsetControl 调用失败: {e}")

        vid = _hex(self.params.get("vid", "-1"))
        pid = _hex(self.params.get("pid", "-1"))
        match = next((d for d in devices
                      if _hex(d.get("id_vendor", "")) == vid and _hex(d.get("id_product", "")) == pid), None)
        if match is None and vid < 0 and devices:
            match = devices[0]
        if match is None:
            return BatteryReading(self.device_id, self.name, error="未检测到该耳机")

        level, charging, status = parse_battery(match)
        if level is None:
            return BatteryReading(self.device_id, self.name, status=status, is_charging=charging,
                                  error=status)
        return BatteryReading(
            device_id=self.device_id,
            name=self.name,
            level=level,
            status=status,
            is_charging=charging,
            detail=f"HeadsetControl · {match.get('device', '')}",
        )
