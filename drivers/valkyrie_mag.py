# -*- coding: utf-8 -*-
"""瓦尔基里 (VALKYRIE) VK MAG75 Max 磁轴键盘驱动
协议：基于 WebHID 驱动 (vkhub.valkyrie.com.cn) 逆向的 0xF7 Feature Report
"""

from __future__ import annotations
from typing import Dict, Any

import hid_win as hw
from .base import BaseDriver, BatteryReading


class ValkyrieMagDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        target_vid = int(str(self.params.get("vid", "0x374A")), 16)
        target_pid = int(str(self.params.get("pid", "0xA223")), 16) if "pid" in self.params else None

        # 瓦尔基里 WebHID 协议走 feature_len == 65 的接口 (MI_02)
        matched_target = None
        for d in hw.enumerate_hid():
            if d.vid == target_vid:
                if target_pid is not None and d.pid != target_pid:
                    continue
                if d.feature_len == 65:
                    matched_target = d
                    break

        if not matched_target:
            return BatteryReading(
                device_id=self.device_id,
                name=self.name,
                error="未找到瓦尔基里键盘 HID Feature 接口"
            )

        try:
            with hw.HidDevice(matched_target.path, write=True) as dev:
                # 瓦尔基里 0xF7 电量状态查询指令 (65 字节)
                cmd = bytes([0x00, 0xF7] + [0] * 63)
                dev.set_feature_report(cmd)

                recv = dev.get_feature_report(0x00, matched_target.feature_len)
                if recv and len(recv) >= 7:
                    # 解析格式：
                    # recv[0] = 0x00 (Report ID)
                    # recv[1] / recv[2] = 电量 (实测 0x5D = 93%)
                    # recv[6] = 0x01 (键盘在线标记)
                    bat_val = recv[2] if recv[2] > 0 else recv[1]
                    if 0 < bat_val <= 100:
                        level = bat_val
                        is_online = (recv[6] == 1)
                        status_str = "正常使用" if is_online else "待机"
                        if level >= 99:
                            status_str = "满电 (USB供电)"

                        return BatteryReading(
                            device_id=self.device_id,
                            name=self.name,
                            level=level,
                            status=status_str,
                            is_charging=(level >= 99),
                            detail=f"VK WebHID (0xF7) [Raw: {recv[1]:02X} {recv[2]:02X} {recv[6]:02X}]"
                        )

                return BatteryReading(
                    device_id=self.device_id,
                    name=self.name,
                    error=f"响应数据校验失败: {recv[:8].hex(' ') if recv else 'None'}"
                )
        except Exception as e:
            return BatteryReading(
                device_id=self.device_id,
                name=self.name,
                error=f"通信异常: {e}"
            )
