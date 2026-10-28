# -*- coding: utf-8 -*-
"""bt_battery.py —— 读取蓝牙耳机/音箱的电量（Windows 未公开 PnP 属性）

原理
----
Windows 的蓝牙协议栈收到耳机通过 HFP（免提协议）上报的电量后，会把它写进
设备 **Hands-Free / 免提** 节点上的一个未公开 PnP 属性：

    PROPERTYKEY {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2   (DEVPROP_TYPE_BYTE)
    值 = 电量百分比（0-100）

注意两点：
  1. 这个属性挂在 **Hands-Free AG 节点** 上，不在设备主节点上——
     所以很多"查不到电量"的教程都是因为在主节点上找。
  2. 该属性由驱动在收到耳机上报时写入，**耳机没连上/不支持 HFP 电量上报时为 0 或不存在**。

同一个机制对蓝牙鼠标、手柄也有效（微软的 Xbox 手柄就是走这个属性）。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from hid_win import GUID, setupapi, kernel32

# 蓝牙电量属性：{104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
FMTID_BLUETOOTH = GUID(
    0x104EA319, 0x6EE2, 0x4701,
    (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5),
)
PID_BATTERY_LEVEL = 2

DIGCF_ALLCLASSES = 0x04
DIGCF_PRESENT_ = 0x02
SPDRP_FRIENDLYNAME = 0x0C
SPDRP_DEVICEDESC = 0x00
ERROR_NOT_FOUND = 1168

# 蓝牙类 {e0cbf06c-cd8b-4647-bb8a-263b43f0f974}
CLASS_BLUETOOTH = GUID(
    0xE0CBF06C, 0xCD8B, 0x4647,
    (ctypes.c_ubyte * 8)(0xBB, 0x8A, 0x26, 0x3B, 0x43, 0xF0, 0xF9, 0x74),
)
# 系统类 {4d36e97d-e325-11ce-bfc1-08002be10318}（HFP 免提节点在这里）
CLASS_SYSTEM = GUID(
    0x4D36E97D, 0xE325, 0x11CE,
    (ctypes.c_ubyte * 8)(0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18),
)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInfo.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA),
]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(PROPERTYKEY),
    ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]


@dataclass
class BluetoothDevice:
    name: str
    instance_id: str
    battery: Optional[int] = None
    has_property: bool = False
    reason: str = ""

    @property
    def is_handsfree(self) -> bool:
        low = self.name.lower()
        return "hands-free" in low or "免提" in self.name or "handsfree" in low


def _device_string(hdev, info, prop: int) -> str:
    buf = ctypes.create_string_buffer(1024)
    need = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceRegistryPropertyW(
            hdev, ctypes.byref(info), prop, None, buf, 1024, ctypes.byref(need)):
        return ""
    return buf.raw.decode("utf-16-le", errors="ignore").split("\x00")[0]


def _instance_id(hdev, info) -> str:
    buf = ctypes.create_unicode_buffer(512)
    need = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceInstanceIdW(
            hdev, ctypes.byref(info), buf, 512, ctypes.byref(need)):
        return ""
    return buf.value


def _read_battery_property(hdev, info) -> tuple[Optional[int], bool, str]:
    """返回 (电量, 属性是否存在, 说明)。"""
    key = PROPERTYKEY(FMTID_BLUETOOTH, PID_BATTERY_LEVEL)
    ptype = wintypes.ULONG(0)
    value = ctypes.c_ubyte(0)
    need = wintypes.DWORD(0)
    ok = setupapi.SetupDiGetDevicePropertyW(
        hdev, ctypes.byref(info), ctypes.byref(key), ctypes.byref(ptype),
        ctypes.byref(value), 1, ctypes.byref(need), 0,
    )
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None, False, "该设备没有电池属性（耳机可能未连接或不上报电量）"
        return None, False, f"读取失败 err={err}"
    level = int(value.value)
    if level == 0:
        return 0, True, "属性存在但值为 0（通常表示未连接或未上报）"
    return min(100, level), True, "来自蓝牙 HFP 电量上报"


def list_bluetooth_devices() -> list[BluetoothDevice]:
    """列出所有蓝牙相关设备及其电量（有的话）。

    两条枚举路径都试一遍再合并：有些 BTHENUM 节点只在设备已连接时存在，
    而且枚举器（enumerator）参数与 DIGCF_ALLCLASSES 的表现不完全一致。
    """
    found: dict[str, BluetoothDevice] = {}
    attempts = (
        (None, None, DIGCF_ALLCLASSES),
        ("BTHENUM", None, 0),
        (None, CLASS_SYSTEM, 0),
        (None, CLASS_BLUETOOTH, 0),
    )
    for enumerator, class_guid, flags in attempts:
        hdev = setupapi.SetupDiGetClassDevsW(
            ctypes.byref(class_guid) if class_guid is not None else None,
            enumerator, None, flags | DIGCF_PRESENT_,
        )
        if not hdev or hdev == ctypes.c_void_p(-1).value:
            continue
        try:
            index = 0
            while True:
                info = SP_DEVINFO_DATA()
                info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
                if not setupapi.SetupDiEnumDeviceInfo(hdev, index, ctypes.byref(info)):
                    break
                index += 1
                iid = _instance_id(hdev, info)
                if not iid.upper().startswith(("BTHENUM", "BTHLE")) or iid in found:
                    continue
                name = _device_string(hdev, info, SPDRP_FRIENDLYNAME)
                if not name:
                    name = _device_string(hdev, info, SPDRP_DEVICEDESC)
                level, has, reason = _read_battery_property(hdev, info)
                found[iid] = BluetoothDevice(
                    name=name or "(无名称)", instance_id=iid,
                    battery=level, has_property=has, reason=reason,
                )
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return list(found.values())


def find_battery_devices() -> list[BluetoothDevice]:
    """只返回真正带电量值的蓝牙设备（优先 Hands-Free 节点）。"""
    devs = [d for d in list_bluetooth_devices()
            if d.has_property and d.battery is not None]
    devs.sort(key=lambda d: (0 if d.is_handsfree else 1, -(d.battery or 0)))
    return devs


def displayable_devices() -> list[BluetoothDevice]:
    """界面用：只保留“可能有电量”的节点，避免把 AVRCP 之类的杂项全列出来。"""
    keys = ("hands-free", "免提", "handsfree", "ag audio")
    out = []
    for d in list_bluetooth_devices():
        low = d.name.lower()
        if d.has_property or any(k in low for k in keys):
            out.append(d)
    return out


def refresh(dev: BluetoothDevice) -> BluetoothDevice:
    """重新读一次指定设备的电量。"""
    for d in list_bluetooth_devices():
        if d.instance_id == dev.instance_id:
            return d
    dev.battery = None
    dev.has_property = False
    dev.reason = "设备已不存在（耳机断开了）"
    return dev


if __name__ == "__main__":
    print("=== 所有蓝牙 HID/音频节点 ===")
    for d in list_bluetooth_devices():
        tag = "🔋" if (d.has_property and d.battery) else "  "
        print(f" {tag} {d.name}   电量={d.battery}  {d.reason}")
        print(f"      {d.instance_id}")
