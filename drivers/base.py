# -*- coding: utf-8 -*-
"""外设电量驱动基类与数据结构"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class BatteryReading:
    """标准电量读取结果"""
    device_id: str
    name: str
    level: Optional[int] = None       # 0~100，None 表示读取失败/离线
    status: str = ""                  # 状态描述：如 "正常使用"、"充电中"、"满电"、"未连接"
    is_charging: bool = False         # 是否处于充电中
    voltage_mv: Optional[int] = None  # 电压 (毫伏)，可选
    detail: str = ""                  # 详细技术信息 (如协议版本、响应帧摘要)
    error: str = ""                   # 报错信息

    @property
    def ok(self) -> bool:
        return self.level is not None and self.error == ""


class BaseDriver:
    """外设驱动基类"""
    def __init__(self, device_id: str, name: str, params: Dict[str, Any]):
        self.device_id = device_id
        self.name = name
        self.params = params

    def read_battery(self) -> BatteryReading:
        """读取电量，由具体驱动实现"""
        raise NotImplementedError("驱动必须实现 read_battery 方法")
