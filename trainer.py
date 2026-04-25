"""
创意咖啡物语 修改器 (控制台版本)
参考: https://mehtrainer.com/cafe-master-story-trainer/

功能:
  [F1] 无限金钱        - 花钱不减少
  [F2] 无限研究点      - 研究点不减少
  [F3] 无限满意度      - 满意度不减少
  [F4] 免费员工升级    - 升级费用为0
  [F5] 员工全属性999   - 服务/魅力/料理/感知 = 999
  [F6] 饮品满属性      - 所有饮品参数 = 999
  [F7] 料理满属性      - 所有料理参数 = 999
  [F8] 套餐满属性      - 所有套餐参数 = 999
  [F9] 物品魅力/品质999 - 家具桌子等摆放物品的魅力和品质为999
  [F10] 料理瞬间升级    - 料理经验需求为0
  [F11] 免费合成/开发    - 合成开发不消耗材料费用

用法: 先启动游戏，再运行本脚本。
      按F1-F11切换功能，按F12退出。
"""

import ctypes
import ctypes.wintypes
import sys
import time

try:
    import pymem
    import pymem.process
except ImportError:
    print("[ERROR] pymem is required. Install with: pip install pymem")
    sys.exit(1)

# ─── Constants ───────────────────────────────────────────────────────
PROCESS_NAME = "KairoGames.exe"
MODULE_NAME = "GameAssembly.dll"

# Method RVAs in GameAssembly.dll (version 1.32, 32-bit)
METHODS = {
    "SubMoney":               0x2D38F0,
    "SubPoint":               0x2D3930,
    "SubManzoku":             0x2D3680,
    "GetLevelUpCost":         0x25F120,
    "ClerkData.GetParameter": 0x25F8E0,
    "MakeMenuData.GetPara":   0x2933C0,
    "MakeMenuData.GetParaSub":0x293370,
    "CookingMenuData.GetPara":0x264230,
    "CookingMenuData.GetParaSub": 0x2641C0,
    "MasterFacility.GetQuality":    0x1893A0,
    "MasterFacility.GetAtmosphere": 0x188F60,
    "MasterTable.GetQuality":       0x18C290,
    "MasterTable.GetAtmosphere":    0x18BE60,
    "Building.GetAtmosphere":       0x179BC0,
    "SetMenuData.GetPara":    0x29A2F0,
    "SetMenuData.GetParaSub": 0x29A2A0,
    "CookingMenuData.GetNextExp": 0x264140,
    "SubForm.GetIngrediensCost": 0x230D30,
    "AppData.GetComposeCost": 0x2C7EF0,
}

# ─── Patch Definitions ──────────────────────────────────────────────
# Each patch: (rva, offset_within_func, original_bytes, patched_bytes)

PATCHES = {
    "F1": {
        "name": "无限金钱",
        "patches": [
            (METHODS["SubMoney"], 10, b'\x2B\x45\x0C', b'\x90\x90\x90'),
            (METHODS["SubMoney"], 15, b'\x1B\x55\x10', b'\x90\x90\x90'),
        ],
    },
    "F2": {
        "name": "无限研究点",
        "patches": [
            (METHODS["SubPoint"], 0xBF, b'\x2B\x45\x0C', b'\x90\x90\x90'),
            (METHODS["SubPoint"], 0xC4, b'\x1B\x55\x10', b'\x90\x90\x90'),
        ],
    },
    "F3": {
        "name": "无限满意度",
        "patches": [
            (METHODS["SubManzoku"], 0, b'\x55\x8B\xEC\x80\x3D', b'\xC3\x8B\xEC\x80\x3D'),
        ],
    },
    "F4": {
        "name": "免费员工升级",
        "patches": [
            (METHODS["GetLevelUpCost"], 3, b'\x8B\x45\x08\x6A', b'\x33\xC0\x5D\xC3'),
        ],
    },
    "F5": {
        "name": "员工全属性999",
        "patches": [
            (METHODS["ClerkData.GetParameter"], 0,
             b'\x55\x8B\xEC\x8B\x4D\x08\x8B\x41\x44\x85',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    "F6": {
        "name": "饮品满属性",
        "patches": [
            (METHODS["MakeMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x80\x3D\xC8\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["MakeMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xC9\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    "F7": {
        "name": "料理满属性",
        "patches": [
            (METHODS["CookingMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x8B\x45\x0C\x83\xF8\x01\x74',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["CookingMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xA3\x04\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    "F8": {
        "name": "套餐满属性",
        "patches": [
            (METHODS["SetMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x80\x3D\xE6\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["SetMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xE7\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    "F9": {
        "name": "物品魅力/品质999",
        "patches": [
            (METHODS["MasterFacility.GetQuality"], 0,
             b'\x55\x8B\xEC\x80\x3D\xF6\x02\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["MasterFacility.GetAtmosphere"], 0,
             b'\x55\x8B\xEC\x80\x3D\xF7\x02\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["MasterTable.GetQuality"], 0,
             b'\x55\x8B\xEC\x80\x3D\x18\x03\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["MasterTable.GetAtmosphere"], 0,
             b'\x55\x8B\xEC\x80\x3D\x17\x03\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["Building.GetAtmosphere"], 0,
             b'\x55\x8B\xEC\x80\x3D\xCD\x02\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    "F10": {
        "name": "料理瞬间升级",
        "patches": [
            (METHODS["CookingMenuData.GetNextExp"], 0,
             b'\x55\x8B\xEC\x8B\x45\x08\x8B\x40\x78\x83',
             b'\x55\x8B\xEC\x33\xC0\x5D\xC3\x90\x90\x90'),
        ],
    },
    "F11": {
        "name": "免费合成/开发",
        "patches": [
            (METHODS["SubForm.GetIngrediensCost"], 0,
             b'\x55\x8B\xEC\x83\xEC\x10\x80\x3D\x66\x03',
             b'\x55\x8B\xEC\x33\xC0\x5D\xC3\x90\x90\x90'),
            (METHODS["AppData.GetComposeCost"], 0,
             b'\x55\x8B\xEC\x83\xEC\x08\x80\x3D\x03\x07',
             b'\x55\x8B\xEC\x33\xC0\x5D\xC3\x90\x90\x90'),
        ],
    },
}

# ─── Virtual Key Codes ──────────────────────────────────────────────
VK_F1  = 0x70
VK_F2  = 0x71
VK_F3  = 0x72
VK_F4  = 0x73
VK_F5  = 0x74
VK_F6  = 0x75
VK_F7  = 0x76
VK_F8  = 0x77
VK_F9  = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A
VK_F12 = 0x7B

KEY_MAP = {
    VK_F1: "F1",
    VK_F2: "F2",
    VK_F3: "F3",
    VK_F4: "F4",
    VK_F5: "F5",
    VK_F6: "F6",
    VK_F7: "F7",
    VK_F8: "F8",
    VK_F9: "F9",
    VK_F10: "F10",
    VK_F11: "F11",
}

GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [ctypes.c_int]
GetAsyncKeyState.restype = ctypes.wintypes.SHORT


# ─── Trainer Logic ───────────────────────────────────────────────────

class Trainer:
    def __init__(self):
        self.pm = None
        self.base = 0
        self.active = {}       # key -> bool
        self.saved_bytes = {}  # key -> list of original bytes read from memory

    def attach(self):
        print(f"[*] 正在搜索 {PROCESS_NAME}...")
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
        except pymem.exception.ProcessNotFound:
            print(f"[!] 未找到 {PROCESS_NAME}，请先启动游戏。")
            return False

        print(f"[+] 已连接到进程 PID {self.pm.process_id}")

        module = pymem.process.module_from_name(
            self.pm.process_handle, MODULE_NAME
        )
        if not module:
            print(f"[!] 进程中未找到 {MODULE_NAME}。")
            return False

        self.base = module.lpBaseOfDll
        print(f"[+] {MODULE_NAME} 基址: 0x{self.base:08X}")

        # Verify by reading first bytes of SubMoney
        addr = self.base + METHODS["SubMoney"]
        check = self.pm.read_bytes(addr, 3)
        if check == b'\x55\x8B\xEC':
            print("[+] 方法签名验证通过")
        else:
            print(f"[!] 警告: SubMoney处字节不匹配: {check.hex()}")
            print("    游戏版本可能不兼容，修改可能无法正常工作。")

        for key in PATCHES:
            self.active[key] = False

        return True

    def toggle(self, key):
        if key not in PATCHES:
            return

        info = PATCHES[key]
        self.active[key] = not self.active[key]
        enabled = self.active[key]

        for rva, offset, orig, patch in info["patches"]:
            addr = self.base + rva + offset
            if enabled:
                # Save current bytes before patching
                current = self.pm.read_bytes(addr, len(orig))
                if key not in self.saved_bytes:
                    self.saved_bytes[key] = []
                self.saved_bytes[key].append((addr, current))
                # Write patch
                self.pm.write_bytes(addr, patch, len(patch))
            else:
                # Restore original bytes
                self.pm.write_bytes(addr, orig, len(orig))
                if key in self.saved_bytes:
                    del self.saved_bytes[key]

        state = "开" if enabled else "关"
        print(f"  [{key}] {info['name']}: {state}")

    def run(self):
        print("\n" + "=" * 50)
        print("  创意咖啡物语 修改器")
        print("=" * 50)

        if not self.attach():
            input("\n按回车键退出...")
            return

        print("\n[快捷键]")
        for key_code, key_name in KEY_MAP.items():
            if key_name in PATCHES:
                print(f"  {key_name} - {PATCHES[key_name]['name']}")
        print(f"  F12 - 退出修改器")
        print()

        prev_state = {vk: False for vk in KEY_MAP}
        prev_f12 = False

        try:
            while True:
                # Check F12 (exit)
                f12_down = bool(GetAsyncKeyState(VK_F12) & 0x8000)
                if f12_down and not prev_f12:
                    break
                prev_f12 = f12_down

                # Check toggle keys
                for vk, key_name in KEY_MAP.items():
                    down = bool(GetAsyncKeyState(vk) & 0x8000)
                    if down and not prev_state[vk]:
                        self.toggle(key_name)
                    prev_state[vk] = down

                time.sleep(0.05)

        except KeyboardInterrupt:
            pass

        # Restore all patches
        print("\n[*] 正在恢复原始代码...")
        for key in list(self.active.keys()):
            if self.active[key]:
                self.toggle(key)

        print("[+] 修改器已安全退出。")


if __name__ == "__main__":
    trainer = Trainer()
    trainer.run()
