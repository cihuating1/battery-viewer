# -*- coding: utf-8 -*-
"""罗技 HID++ 2.0/4.5 电量驱动
支持：GPW3 (G PRO X SUPERLIGHT 2), GPW1/2, G502X, G913 等罗技无线外设
"""

from __future__ import annotations
from typing import Dict, Any, Optional

import hid_win as hw
from .base import BaseDriver, BatteryReading


class LogitechHidppDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        target_vid = int(str(self.params.get("vid", "0x046D")), 16)
        target_pid = int(str(self.params.get("pid", "0xC54D")), 16) if "pid" in self.params else None

        # 匹配对应接收器/设备的短报文接口 (input_len == 20)
        matched_target = None
        for d in hw.enumerate_hid():
            if d.vid == target_vid:
                if target_pid is not None and d.pid != target_pid:
                    continue
                if d.input_len == 20 and d.usage_page == 0xFF00 and d.usage == 0x0002:
                    matched_target = d
                    break
        if not matched_target:
            for d in hw.enumerate_hid():
                if d.vid == target_vid and d.input_len == 20:
                    matched_target = d
                    break

        if not matched_target:
            return BatteryReading(
                device_id=self.device_id,
                name=self.name,
                error="未找到罗技接收器/USB设备或接口不可用"
            )

        try:
            with hw.HidDevice(matched_target.path, write=True) as dev:
                dev.drain()

                # 0. 先发送 Ping 唤醒/激活设备 (Device Index 0x01 = 配对槽1)
                ping = bytes([0x11, 0x01, 0x00, 0x00, 0x00, 0x00, 0x5A] + [0] * 13)
                dev.write_output(ping)
                dev.read_input(timeout_ms=100)

                # 1. 探测 Feature 0x1004 (Unified Battery)
                get_feat = bytearray(20)
                get_feat[0] = 0x11
                get_feat[1] = 0x01
                get_feat[2] = 0x00
                get_feat[3] = 0x00
                get_feat[4] = 0x10
                get_feat[5] = 0x04
                dev.write_output(bytes(get_feat))
                resp = dev.read_input(timeout_ms=400)
                feat_idx = resp[4] if (resp and len(resp) >= 5 and resp[0] == 0x11 and resp[1] == 0x01) else None

                # 2. 如果找到 0x1004，查询 getBatteryStatus (Function 1 -> 0x10)
                if feat_idx and feat_idx > 0:
                    query_cmd = bytearray(20)
                    query_cmd[0] = 0x11
                    query_cmd[1] = 0x01
                    query_cmd[2] = feat_idx
                    query_cmd[3] = 0x10  # Function 1: getBatteryStatus

                    dev.write_output(bytes(query_cmd))
                    bat_resp = dev.read_input(timeout_ms=400)
                    if bat_resp and len(bat_resp) >= 6 and bat_resp[0] == 0x11 and bat_resp[2] == feat_idx:
                        level = bat_resp[4]
                        status_flags = bat_resp[6] if len(bat_resp) > 6 else 0
                        is_charging = (status_flags in (1, 2, 3))

                        status_str = "充电中" if is_charging else ("满电" if level >= 99 else "正常使用")

                        return BatteryReading(
                            device_id=self.device_id,
                            name=self.name,
                            level=level,
                            status=status_str,
                            is_charging=is_charging,
                            detail=f"HID++ 2.0 (Unified 0x1004) [Raw: {level}%]"
                        )

                # 3. 降级尝试 Feature 0x1000 (BATTERY_LEVEL_STATUS)
                get_feat[4] = 0x10
                get_feat[5] = 0x00
                dev.write_output(bytes(get_feat))
                resp = dev.read_input(timeout_ms=400)
                if resp and len(resp) >= 5 and resp[4] > 0:
                    feat_idx = resp[4]
                    query_cmd = bytearray(20)
                    query_cmd[0] = 0x11
                    query_cmd[1] = 0x01
                    query_cmd[2] = feat_idx
                    query_cmd[3] = 0x00
                    dev.write_output(bytes(query_cmd))
                    bat_resp = dev.read_input(timeout_ms=400)
                    if bat_resp and len(bat_resp) >= 6:
                        level = bat_resp[4]
                        is_charging = (bat_resp[6] if len(bat_resp) > 6 else 0) > 0
                        return BatteryReading(
                            device_id=self.device_id,
                            name=self.name,
                            level=level,
                            status="充电中" if is_charging else "正常使用",
                            is_charging=is_charging,
                            detail=f"HID++ 2.0 (0x1000)"
                        )

                return BatteryReading(
                    device_id=self.device_id,
                    name=self.name,
                    error="设备未响应电量请求 (可能已进入休眠)"
                )
        except Exception as e:
            return BatteryReading(
                device_id=self.device_id,
                name=self.name,
                error=f"通信异常: {e}"
            )
