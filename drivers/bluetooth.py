# -*- coding: utf-8 -*-
"""蓝牙通用驱动：读取 Windows 蓝牙协议栈记录的电量（无需设备私有协议）
params:
    instance_id  设备实例 ID（添加设备时自动填写，最精确）
    name         设备名关键字（instance_id 找不到时按名称匹配，不区分大小写）
"""

from __future__ import annotations

import bt_battery
from .base import BaseDriver, BatteryReading


class BluetoothDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        iid = str(self.params.get("instance_id", "")).upper()
        keyword = str(self.params.get("name", "")).lower()
        devices = [d for d in bt_battery.list_bluetooth_devices() if d.has_property]

        match = next((d for d in devices if iid and d.instance_id.upper() == iid), None)
        if match is None and keyword:
            named = [d for d in devices if keyword in d.name.lower()]
            named.sort(key=lambda d: (0 if d.battery else 1, 0 if d.is_handsfree else 1))
            match = named[0] if named else None

        if match is None:
            return BatteryReading(self.device_id, self.name, error="蓝牙设备未连接")
        if not match.battery:
            return BatteryReading(self.device_id, self.name, error="设备已连接但未上报电量 (可能已休眠)")
        return BatteryReading(
            device_id=self.device_id,
            name=self.name,
            level=match.battery,
            status="正常使用",
            detail=f"Bluetooth · {match.name}",
        )
