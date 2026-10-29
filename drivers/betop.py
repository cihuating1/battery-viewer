# -*- coding: utf-8 -*-
"""北通（BETOP / BEITONG）手柄驱动，实测鲲鹏 70（BTP-KP70C）
协议（被动监听得到，不发送任何命令）：
    usage page 0x00FF / usage 0x0003，64 字节 Input Report，约每秒一条状态包：
    02 15 <电量%> 00 <模式 0x50 无线 / 0x51 有线> <标志> ...
    - 第 2 字节：电量百分比（无线 72↔73 跳变；插线充电时 85→87 上升）
    - 第 5 字节 bit2：有线 / 充电（无线 0x01，插线 0x05）——推测，仅一次插拔样本
插线后手柄会以有线设备（如 20BC:5173）出现，接收器（20BC:5174）消失，因此同 VID 的任一 PID 都接受。
params:
    vid   默认 0x20BC
    pid   优先匹配的 PID（找不到时退而使用同 VID 的其他设备）
"""

from __future__ import annotations

import time

import hid_win as hw
from .base import BaseDriver, BatteryReading


class BetopDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        vid = int(str(self.params.get("vid", "0x20BC")), 16)
        pid = int(str(self.params.get("pid", "0")), 16)
        ifaces = [i for i in hw.enumerate_hid()
                  if i.vid == vid and i.usage_page == 0x00FF and i.input_len == 64]
        if not ifaces:
            return BatteryReading(self.device_id, self.name, error="未找到北通接收器 / 手柄")
        ifaces.sort(key=lambda i: i.pid != pid)

        try:
            with hw.HidDevice(ifaces[0].path, write=False) as dev:
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    r = dev.read_input(timeout_ms=500)
                    if not r or len(r) < 6 or r[0] != 0x02 or r[1] != 0x15:
                        continue
                    level = r[2]
                    if not 0 <= level <= 100:
                        continue
                    charging = bool(r[5] & 0x04)
                    return BatteryReading(
                        device_id=self.device_id,
                        name=self.name,
                        level=level,
                        status="充电中" if charging else "正常使用",
                        is_charging=charging,
                        detail=f"BETOP 状态包 [{r[:8].hex(' ')}]",
                    )
        except Exception as e:
            return BatteryReading(self.device_id, self.name, error=f"通信异常: {e}")
        return BatteryReading(self.device_id, self.name, error="手柄未开机或未连接（接收器没有状态包）")
