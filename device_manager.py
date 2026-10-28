# -*- coding: utf-8 -*-
"""设备管理与快捷添加工具
用法:
    python device_manager.py list                   列出已配置设备的电量状态
    python device_manager.py scan                   扫描本机未纳管的 HID/USB 设备
    python device_manager.py add <id> <name> <driver> <vid> <pid> [glyph]   快速添加新设备到配置
                                                    glyph: mouse / keyboard / headset / controller（托盘与卡片图标）
    python device_manager.py new-driver <name>      创建新驱动模板代码
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

import hid_win as hw
from drivers import create_driver, DRIVER_REGISTRY

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"poll_interval_sec": 30, "devices": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def cmd_list() -> None:
    cfg = load_config()
    devices = cfg.get("devices", [])
    print(f"=== 已配置设备列表 ({len(devices)} 台) ===")
    for dev in devices:
        if not dev.get("enabled", True):
            print(f"[-] {dev['name']} ({dev['id']}): 已禁用")
            continue
        try:
            drv = create_driver(dev["driver"], dev["id"], dev["name"], dev.get("params", {}))
            res = drv.read_battery()
            if res.ok:
                charge_mark = " [充电中]" if res.is_charging else ""
                print(f"[+] {res.name}: {res.level}% [{res.status}]{charge_mark} | {res.detail}")
            else:
                print(f"[x] {res.name}: 读取失败 -> {res.error}")
        except Exception as e:
            print(f"[!] {dev['name']}: 驱动加载异常 -> {e}")


def cmd_scan() -> None:
    cfg = load_config()
    known_vids = {int(str(d["params"]["vid"]), 16) for d in cfg.get("devices", []) if "vid" in d.get("params", {})}
    print("=== 扫描本机已连接的所有 HID/USB 设备 ===")
    seen = set()
    found = []
    for d in hw.enumerate_hid():
        key = (d.vid, d.pid)
        if key in seen:
            continue
        seen.add(key)
        mfg = d.manufacturer or ""
        prod = d.product or ""
        is_known = d.vid in known_vids
        status_tag = "[已纳管]" if is_known else "[新外设候选]"
        found.append((status_tag, d.vid, d.pid, mfg, prod))

    for tag, vid, pid, mfg, prod in found:
        print(f"{tag:12} VID: 0x{vid:04X} | PID: 0x{pid:04X} | 厂商: {mfg:15} | 产品: {prod}")
    print("\n提示: 想要添加新设备，可运行: python device_manager.py add <id> <名称> <驱动> 0xVID 0xPID")


def cmd_add(device_id: str, name: str, driver: str, vid: str, pid: str, glyph: str = "mouse") -> None:
    cfg = load_config()
    for d in cfg.setdefault("devices", []):
        if d["id"] == device_id:
            print(f"错误: 设备 ID '{device_id}' 已存在！")
            return

    new_dev = {
        "id": device_id,
        "name": name,
        "short_name": name,
        "glyph": glyph,
        "enabled": True,
        "driver": driver,
        "params": {
            "vid": vid,
            "pid": pid
        }
    }
    cfg["devices"].append(new_dev)
    save_config(cfg)
    print(f"成功添加新设备: {name} ({device_id}) -> 配置文件已更新！电量岛会在下次刷新时自动加载。")


def cmd_new_driver(driver_name: str) -> None:
    drv_dir = Path(__file__).parent / "drivers"
    target = drv_dir / f"{driver_name}.py"
    if target.exists():
        print(f"驱动文件 {target} 已存在！")
        return
    template = f'''# -*- coding: utf-8 -*-
"""自定义外设驱动: {driver_name}"""

from __future__ import annotations
from typing import Dict, Any
from .base import BaseDriver, BatteryReading
import hid_win as hw

class {driver_name.capitalize()}Driver(BaseDriver):
    def read_battery(self) -> BatteryReading:
        # TODO: 在此处编写针对 0x{{self.params.get('vid')}} 设备的读取协议
        return BatteryReading(
            device_id=self.device_id,
            name=self.name,
            level=100,
            status="正常",
            detail="驱动运行正常"
        )
'''
    with open(target, "w", encoding="utf-8") as f:
        f.write(template)
    print(f"已创建新驱动模板: {target}")
    print(f"驱动会被自动注册，config.json 里写 \"driver\": \"{driver_name}\" 即可使用。")


def main() -> None:
    if len(sys.argv) < 2:
        cmd_list()
        return

    action = sys.argv[1].lower()
    if action == "list":
        cmd_list()
    elif action == "scan":
        cmd_scan()
    elif action == "add":
        if len(sys.argv) < 7:
            print("用法: python device_manager.py add <id> <name> <driver> <vid> <pid> [glyph]")
            print("例如: python device_manager.py add atk_mouse 'ATK 烈空 X1' atk_proto 0x248A 0x8266")
            return
        cmd_add(*sys.argv[2:8])
    elif action == "new-driver":
        if len(sys.argv) < 3:
            print("用法: python device_manager.py new-driver <driver_name>")
            return
        cmd_new_driver(sys.argv[2])
    else:
        print(f"未知指令: {action}")


if __name__ == "__main__":
    main()
