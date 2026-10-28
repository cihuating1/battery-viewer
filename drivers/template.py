# -*- coding: utf-8 -*-
"""新外设驱动模版
你可以复制此文件开发新设备的电量读取逻辑。
"""

from __future__ import annotations
from typing import Dict, Any
from .base import BaseDriver, BatteryReading


class TemplateDriver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        # TODO: 使用 hid_win 枚举和打开设备，收发报文并解析电量
        return BatteryReading(
            device_id=self.device_id,
            name=self.name,
            level=80,
            status="模版演示",
            detail="这是模版驱动返回的示例数据"
        )
