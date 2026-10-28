# -*- coding: utf-8 -*-
import sys
import time

sys.path.insert(0, 'D:/Codex/battery-viewer')
import hid_win

devices = hid_win.enumerate_hid()

print("=" * 60)
print("1. 探测 Logitech GPW3 (046D:C54D)")
print("=" * 60)
logi_ifaces = [d for d in devices if d.vid == 0x046D and d.pid == 0xC54D]
for iface in logi_ifaces:
    print(f"Iface: UP={hex(iface.usage_page)} Usage={hex(iface.usage)} In={iface.input_len} Out={iface.output_len}")
    if iface.usage_page == 0xFF00 and iface.usage == 0x0002: # 20 字节长报文接口
        try:
            with hid_win.HidDevice(iface.path, write=True) as h:
                print(f"  -> 成功打开句柄 (write_access={h.write_access})")
                
                # 尝试用 Device Index 0x01 (无线鼠标配对槽1)
                # 先发 Ping: 0x11 0x01 0x00 0x00 0x00 0x00 0x5a
                ping_cmd = bytes([0x11, 0x01, 0x00, 0x00, 0x00, 0x00, 0x5A] + [0] * 13)
                h.write_output(ping_cmd)
                resp = h.read_input(timeout_ms=600)
                if resp:
                    print("  -> Ping 回复:", resp.hex(" "))
                else:
                    print("  -> Ping 无回复")

                # 探测 Feature 0x1000 (Battery Level Status)
                get_1000 = bytes([0x11, 0x01, 0x00, 0x00, 0x10, 0x00, 0x00] + [0] * 13)
                h.write_output(get_1000)
                resp1000 = h.read_input(timeout_ms=600)
                if resp1000:
                    print("  -> getFeature(0x1000) 回复:", resp1000.hex(" "))
                    feat_idx = resp1000[4]
                    if feat_idx != 0:
                        print(f"     Feature 0x1000 索引: 0x{feat_idx:02X}")
                        # Function 0: getBatteryLevelStatus
                        h.write_output(bytes([0x11, 0x01, feat_idx, 0x00] + [0] * 16))
                        bat_resp = h.read_input(timeout_ms=600)
                        if bat_resp:
                            print("     [Feature 1000 电量报文]:", bat_resp.hex(" "))
                            print(f"     --> GPW3 电量: {bat_resp[4]}%, 充电状态: {bat_resp[6]}")

                # 探测 Feature 0x1004 (Unified Battery)
                get_1004 = bytes([0x11, 0x01, 0x00, 0x00, 0x10, 0x04, 0x00] + [0] * 13)
                h.write_output(get_1004)
                resp1004 = h.read_input(timeout_ms=600)
                if resp1004:
                    print("  -> getFeature(0x1004) 回复:", resp1004.hex(" "))
                    feat_idx_1004 = resp1004[4]
                    if feat_idx_1004 != 0:
                        print(f"     Feature 0x1004 索引: 0x{feat_idx_1004:02X}")
                        # Function 0: getBatteryCapability
                        h.write_output(bytes([0x11, 0x01, feat_idx_1004, 0x00] + [0] * 16))
                        cap_resp = h.read_input(timeout_ms=600)
                        if cap_resp:
                            print("     Capability 回复:", cap_resp.hex(" "))
                        # Function 1: getBatteryStatus (0x10)
                        h.write_output(bytes([0x11, 0x01, feat_idx_1004, 0x10] + [0] * 16))
                        bat4_resp = h.read_input(timeout_ms=600)
                        if bat4_resp:
                            print("     [Feature 1004 电量报文]:", bat4_resp.hex(" "))
                            level = bat4_resp[4]
                            next_level = bat4_resp[5]
                            status = bat4_resp[6]
                            print(f"     --> GPW3 Unified 电量: {level}%, 状态: {status}")
        except Exception as e:
            print("  -> 出错:", e)

print("\n" + "=" * 60)
print("2. 探测 VK MAG75 Max (374A:A223)")
print("=" * 60)
vk_ifaces = [d for d in devices if d.vid == 0x374A and d.pid == 0xA223]
for iface in vk_ifaces:
    print(f"Iface: UP={hex(iface.usage_page)} Usage={hex(iface.usage)} In={iface.input_len} Out={iface.output_len} Feat={iface.feature_len}")
    if iface.feature_len > 0:
        try:
            with hid_win.HidDevice(iface.path, write=True) as h:
                print(f"  -> 打开 Feature 接口 (FeatLen={iface.feature_len})")
                for r_id in range(0, 16):
                    try:
                        feat = h.get_feature_report(r_id, iface.feature_len)
                        if feat and any(feat):
                            print(f"     Report ID 0x{r_id:02X}: {feat[:20].hex(' ')}...")
                    except Exception:
                        pass
        except Exception as e:
            print("  -> Feature 出错:", e)
    elif iface.input_len > 0 and iface.usage_page >= 0xFF00:
        try:
            with hid_win.HidDevice(iface.path, write=False) as h:
                print(f"  -> 打开 Vendor Input 接口 (InLen={iface.input_len})")
                resp = h.read_input(timeout_ms=300)
                if resp:
                    print("     收到 Input 报文:", resp[:20].hex(" "))
        except Exception as e:
            print("  -> Input 出错:", e)
