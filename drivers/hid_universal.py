# -*- coding: utf-8 -*-
"""通用 HID 驱动：复用 battery.py 的多策略引擎（原项目内置的协议表）
覆盖：
    - 标准 HID 电量字段（任意厂商，只要设备按 HID 标准上报电量）
    - ATK / VXE / VGN（VID 0x373B / 0x3554，协议 1 与协议 2）
    - Endgame Gear（0x3367）、VAXEE / ZYGEN（0x3057）、Nordic nRF 方案（0x1915）
    - DARKRIM 杰理方案耳机 dongle（0x3654）
    - battery.py「手动标定」保存的自定义协议
params:
    vid / pid    接收器或有线设备的 VID/PID
"""

from __future__ import annotations

import battery as bat
import hid_win as hw
from .base import BaseDriver, BatteryReading

STRATEGIES = (
    bat.strategy_standard_battery_usage,
    bat.strategy_darkrim,
    bat.strategy_vendor_protocol,
)


def known_vids() -> set[int]:
    """内置协议表覆盖的 VID"""
    return {s.vid for s in bat.all_protocols()} | {bat.drp.VID}


class HidUniversalDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        vid = int(str(self.params.get("vid", "0")), 16)
        pid = int(str(self.params.get("pid", "0")), 16) if "pid" in self.params else None
        ifaces = [i for i in hw.enumerate_hid()
                  if i.vid == vid and (pid is None or i.pid == pid) and not i.reserved]
        if not ifaces:
            return BatteryReading(self.device_id, self.name, error="未找到设备（接收器未插入？）")

        # 协议表里登记过 usage page 的接口优先尝试
        pages = {s.usage_page for s in bat.all_protocols() if s.vid == vid}
        ifaces.sort(key=lambda i: (i.usage_page not in pages, not i.is_vendor_page))

        last_error = "设备未响应电量请求 (可能已进入休眠)"
        for iface in ifaces:
            for strategy in STRATEGIES:
                try:
                    res = strategy(iface)
                except Exception as e:
                    res = bat.BatteryResult(ok=False, detail=f"异常：{e}")
                if res is None:
                    continue
                if res.ok and res.level is not None:
                    charging = res.status in ("charging", "full")
                    return BatteryReading(
                        device_id=self.device_id,
                        name=self.name,
                        level=res.level,
                        status="充电中" if res.status == "charging" else (
                            "已充满" if res.status == "full" else "正常使用"),
                        is_charging=charging,
                        voltage_mv=res.voltage_mv,
                        detail=f"{res.source} [{iface.describe_usage()}]",
                    )
                if res.detail:
                    last_error = res.detail
        return BatteryReading(self.device_id, self.name, error=last_error)
