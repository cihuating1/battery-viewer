# -*- coding: utf-8 -*-
"""设备自动发现：扫描本机蓝牙 / HID / HeadsetControl 耳机，找出能读到电量的设备

每个候选设备都带好了 driver + params，加入 config.json 即可使用，不需要用户懂协议。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import bt_battery
import hid_win as hw
from drivers import create_driver
from drivers import headsetcontrol as hsc

# 已知厂商 VID → (通用驱动, 默认图标)（同一厂商共用一套协议）
VENDOR_DRIVERS = {
    0x046D: ("logitech_hidpp", "mouse"),    # Logitech（Lightspeed / Unifying 接收器、有线模式）
    0x374A: ("valkyrie_mag", "keyboard"),   # VALKYRIE 瓦尔基里
    # 以下走 hid_universal（battery.py 内置协议表）
    0x373B: ("hid_universal", "mouse"),     # ATK（协议 1：0xFF02 / 协议 2：0xFF05）
    0x3554: ("hid_universal", "mouse"),     # VXE / VGN
    0x3367: ("hid_universal", "mouse"),     # Endgame Gear
    0x3057: ("hid_universal", "mouse"),     # VAXEE / ZYGEN
    0x1915: ("hid_universal", "mouse"),     # Nordic nRF 方案接收器
    0x3654: ("hid_universal", "headset"),   # DARKRIM 杰理方案耳机
}

GLYPH_KEYWORDS = [
    ("controller", ("controller", "gamepad", "xbox", "手柄", "joy-con", "dualsense", "dualshock")),
    ("headset", ("headset", "headphone", "earbud", "buds", "arctis", "airpods", "耳机", "hands-free", "免提")),
    ("keyboard", ("keyboard", "键盘", "kbd")),
    ("mouse", ("mouse", "鼠标", "superlight", "viper", "g502", "g pro")),
]


def guess_glyph(name: str, default: str = "mouse") -> str:
    low = name.lower()
    for glyph, words in GLYPH_KEYWORDS:
        if any(w in low for w in words):
            return glyph
    return default


@dataclass
class Candidate:
    key: str                      # 唯一标识，用于去重与「忽略」
    name: str
    driver: str
    params: dict
    glyph: str
    source: str                   # "蓝牙" / "2.4G / USB" / "耳机"
    level: Optional[int] = None
    charging: bool = False
    note: str = ""
    supported: bool = True        # False = 识别不了，只用于展示 VID/PID

    @property
    def readable(self) -> bool:
        return self.supported and self.level is not None

    def device_id(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_") or "device"
        return base[:24]

    def to_config(self, existing_ids: set[str]) -> dict:
        dev_id, n = self.device_id(), 2
        while dev_id in existing_ids:
            dev_id, n = f"{self.device_id()}_{n}", n + 1
        return {
            "id": dev_id,
            "name": self.name,
            "title": self.name,
            "subtitle": f"{self.source} · 自动添加",
            "glyph": self.glyph,
            "enabled": True,
            "driver": self.driver,
            "params": dict(self.params),
        }


def candidate_key(driver: str, params: dict) -> str:
    if driver == "bluetooth":
        return f"bt:{str(params.get('instance_id') or params.get('name', '')).upper()}"
    vid = str(params.get("vid", "")).lower()
    pid = str(params.get("pid", "")).lower()
    return f"{driver}:{int(vid, 16) if vid else 0:04x}:{int(pid, 16) if pid else 0:04x}"


def configured_keys(cfg: dict) -> set[str]:
    return {candidate_key(d.get("driver", ""), d.get("params", {})) for d in cfg.get("devices", [])}


def _probe(c: Candidate) -> Candidate:
    try:
        r = create_driver(c.driver, "probe", c.name, c.params).read_battery()
        c.level, c.charging = r.level, r.is_charging
        c.note = r.status if r.ok else (r.error or "读取失败")
    except Exception as e:
        c.note = f"读取异常: {e}"
    return c


def _scan_bluetooth() -> list[Candidate]:
    out = []
    seen_names = set()
    for d in bt_battery.find_battery_devices():
        name = re.sub(r"\s*(hands-free|免提)\s*(ag|audio)?.*$", "", d.name, flags=re.I).strip() or d.name
        if name in seen_names:
            continue
        seen_names.add(name)
        params = {"instance_id": d.instance_id, "name": name}
        out.append(Candidate(
            key=candidate_key("bluetooth", params), name=name, driver="bluetooth", params=params,
            glyph=guess_glyph(d.name, "headset"), source="蓝牙",
            level=d.battery or None, note="蓝牙电量" if d.battery else d.reason,
        ))
    return out


def _scan_headsets() -> list[Candidate]:
    try:
        devices = hsc.query_devices()
    except Exception:
        return []
    out = []
    for d in devices:
        params = {"vid": str(d.get("id_vendor", "")), "pid": str(d.get("id_product", ""))}
        level, charging, status = hsc.parse_battery(d)
        out.append(Candidate(
            key=candidate_key("headsetcontrol", params), name=d.get("device") or d.get("product") or "耳机",
            driver="headsetcontrol", params=params, glyph="headset", source="耳机",
            level=level, charging=charging, note=status,
        ))
    return out


def _scan_hid(skip: set[str], probe: bool) -> list[Candidate]:
    groups: dict[tuple[int, int], list[hw.HidInterface]] = {}
    for d in hw.enumerate_hid():
        groups.setdefault((d.vid, d.pid), []).append(d)

    out = []
    for (vid, pid), items in groups.items():
        name = hw.pick_device_name(items) if hasattr(hw, "pick_device_name") else (items[0].product or "")
        name = name or f"HID {vid:04X}:{pid:04X}"
        params = {"vid": f"0x{vid:04X}", "pid": f"0x{pid:04X}"}
        driver, default_glyph = VENDOR_DRIVERS.get(vid, ("", ""))
        if not default_glyph:
            usages = {(i.usage_page, i.usage) for i in items}
            default_glyph = "keyboard" if (0x01, 0x06) in usages and (0x01, 0x02) not in usages else "mouse"
        if driver:
            c = Candidate(key=candidate_key(driver, params), name=name, driver=driver, params=params,
                          glyph=guess_glyph(name, default_glyph), source="2.4G / USB")
            if c.key in skip:
                continue
            out.append(_probe(c) if probe else c)
        elif any(i.is_vendor_page for i in items):
            # 带厂商私有接口的外设：先试标准 HID 电量字段，读到了就当作可添加
            c = Candidate(key=candidate_key("hid_universal", params), name=name, driver="hid_universal",
                          params=params, glyph=guess_glyph(name, default_glyph), source="2.4G / USB")
            if c.key in skip:
                continue
            if probe and _probe(c).readable:
                out.append(c)
                continue
            out.append(Candidate(key=f"unknown:{vid:04x}:{pid:04x}", name=name, driver="", params=params,
                                 glyph=guess_glyph(name, default_glyph), source="2.4G / USB",
                                 supported=False, note=f"暂无驱动 · VID 0x{vid:04X} PID 0x{pid:04X}"))
    return out


def discover(cfg: dict, probe: bool = True) -> list[Candidate]:
    """返回尚未加入 config.json 的候选设备（能读电量的排在前面）"""
    skip = configured_keys(cfg)
    found: list[Candidate] = []
    for scan in (_scan_bluetooth, _scan_headsets):
        try:
            found += scan()
        except Exception as e:
            print(f"[discovery] {scan.__name__} 失败: {e}")
    def vid_pid(c: Candidate) -> tuple[int, int]:
        try:
            return int(c.params["vid"], 16), int(c.params["pid"], 16)
        except (KeyError, ValueError):
            return -1, -1

    headset_ids = {vid_pid(c) for c in found if c.driver == "headsetcontrol"}
    try:
        for c in _scan_hid(skip, probe):
            # 已被 HeadsetControl 识别的耳机不重复列出
            if vid_pid(c) in headset_ids:
                continue
            found.append(c)
    except Exception as e:
        print(f"[discovery] HID 扫描失败: {e}")

    found = [c for c in found if c.key not in skip]
    found.sort(key=lambda c: (not c.readable, not c.supported, c.name))
    return found


if __name__ == "__main__":
    import json
    from pathlib import Path
    cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
    for c in discover(cfg):
        lvl = f"{c.level}%" if c.level is not None else "--"
        print(f"[{c.source}] {c.name:30} {lvl:>5}  driver={c.driver or '-':15} {c.note}")
