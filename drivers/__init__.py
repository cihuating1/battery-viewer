# -*- coding: utf-8 -*-
"""驱动包注册与工厂

drivers/ 下的每个 .py 文件会被自动扫描：文件名即驱动名（config.json 里的 "driver" 字段），
文件里继承 BaseDriver 的类即该驱动。新增设备只需放一个驱动文件 + 在 config.json 加一条，无需改这里。
"""

import importlib
import inspect
import pkgutil
from typing import Dict, Type
from .base import BaseDriver, BatteryReading
from .logitech_hidpp import LogitechHidppDriver
from .valkyrie_mag import ValkyrieMagDriver
from .template import TemplateDriver
from .bluetooth import BluetoothDriver
from .headsetcontrol import HeadsetcontrolDriver
from .hid_universal import HidUniversalDriver
from .betop import BetopDriver

# 显式注册（PyInstaller 打包后 pkgutil 扫描不到源文件时兜底）
DRIVER_REGISTRY: Dict[str, Type[BaseDriver]] = {
    "logitech_hidpp": LogitechHidppDriver,
    "valkyrie_mag": ValkyrieMagDriver,
    "template": TemplateDriver,
    "bluetooth": BluetoothDriver,
    "headsetcontrol": HeadsetcontrolDriver,
    "hid_universal": HidUniversalDriver,
    "betop": BetopDriver,
}


def _discover() -> None:
    """自动注册 drivers/ 下其余驱动模块"""
    for info in pkgutil.iter_modules(__path__):
        if info.name in ("base",) or info.name in DRIVER_REGISTRY:
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as e:
            print(f"[drivers] 加载 {info.name} 失败: {e}")
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseDriver) and cls is not BaseDriver and cls.__module__ == module.__name__:
                DRIVER_REGISTRY[info.name] = cls
                break


_discover()


def create_driver(driver_name: str, device_id: str, name: str, params: dict) -> BaseDriver:
    """根据配置动态实例化驱动"""
    cls = DRIVER_REGISTRY.get(driver_name)
    if not cls:
        raise ValueError(f"未找到驱动: {driver_name}，可用驱动: {list(DRIVER_REGISTRY.keys())}")
    return cls(device_id=device_id, name=name, params=params)
