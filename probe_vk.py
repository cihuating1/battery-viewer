# -*- coding: utf-8 -*-
import sys
import time

sys.path.insert(0, 'D:/Codex/battery-viewer')
import hid_win

devices = hid_win.enumerate_hid()
vk_ifaces = [d for d in devices if d.vid == 0x374A and d.pid == 0xA223]

print("=== 深入探测 VK MAG75 Max 协议 ===")
for iface in vk_ifaces:
    print(f"Path: {iface.path}")
    print(f"  UP={hex(iface.usage_page)} Usage={hex(iface.usage)} In={iface.input_len} Out={iface.output_len} Feat={iface.feature_len}")

# 测试 1: 在 Feat: 65 (UP=0xffff, Usage=0x2) 上测试各种常用的键盘驱动查询命令
feat_iface = [d for d in vk_ifaces if d.feature_len > 0]
if feat_iface:
    f_d = feat_iface[0]
    print(f"\n[*] 尝试在 Feature 接口写入查询命令 (FeatLen={f_d.feature_len})")
    # 瓦尔基里/维盛/自研常用的查询命令:
    # 常见 0x05, 0x06, 0x07, 0x08, 0x0a, 0x0c, 0xa5, 0x5a, 0x04
    test_cmds = [
        bytes([0x04, 0x01] + [0]*63), # 查状态/电量
        bytes([0x05, 0x00] + [0]*63),
        bytes([0x06, 0x00] + [0]*63),
        bytes([0x07, 0x00] + [0]*63),
        bytes([0x08, 0x00] + [0]*63),
        bytes([0x0a, 0x00] + [0]*63),
        bytes([0x5a, 0xa5] + [0]*63),
        bytes([0xa5, 0x5a] + [0]*63),
        bytes([0x00, 0x01, 0x02] + [0]*62),
    ]
    with hid_win.HidDevice(f_d.path, write=True) as h:
        for idx, cmd in enumerate(test_cmds):
            try:
                h.set_feature_report(cmd)
                time.sleep(0.05)
                # 读取回复
                resp = h.get_feature_report(cmd[0], f_d.feature_len)
                if resp and any(resp[1:]): # 如果除 report id 外有非零数据
                    print(f"  -> 命令 {cmd[:4].hex(' ')} 触发有效回复: {resp[:24].hex(' ')}")
            except Exception as e:
                # print(f"  -> 命令 {idx} 失败: {e}")
                pass

# 测试 2: 在 In: 32 (UP=0xffff, Usage=0x1) 尝试读取
in_iface = [d for d in vk_ifaces if d.input_len == 32 and d.usage_page == 0xffff]
if in_iface:
    i_d = in_iface[0]
    print(f"\n[*] 尝试在 In:32 接口监听或收发 (InLen={i_d.input_len}, OutLen={i_d.output_len})")
    try:
        with hid_win.HidDevice(i_d.path, write=True) as h:
            # 试着发一个空查询或读 Input
            resp = h.read_input(timeout_ms=500)
            if resp:
                print(f"  -> 收到自发/常态 Input 报文: {resp.hex(' ')}")
            else:
                print("  -> 500ms 内无自发报文")
    except Exception as e:
        print("  -> 监听出错:", e)
