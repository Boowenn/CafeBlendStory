"""
创意咖啡物语 修改器 (GUI版本)
参考: https://mehtrainer.com/cafe-master-story-trainer/

功能:
  [F1] 无限金钱        - 花钱不减少
  [F2] 无限研究点      - 研究点不减少
  [F3] 无限满意度      - 顾客满意度不减少
  [F4] 免费员工升级    - 升级费用为0
  [F5] 员工全属性999   - 服务/魅力/料理/感知全部999
  [F6] 饮品满属性      - 所有饮品属性999
  [F7] 料理满属性      - 所有料理属性999
  [F8] 套餐满属性      - 所有套餐属性999
  [F9] 料理瞬间升级    - 料理经验需求为0
  [F10] 退出
"""

import ctypes
import ctypes.wintypes
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

try:
    import pymem
    import pymem.process
except ImportError:
    print("[ERROR] pymem required: pip install pymem")
    sys.exit(1)

# ─── Game Constants ──────────────────────────────────────────────────
PROCESS_NAME = "KairoGames.exe"
MODULE_NAME = "GameAssembly.dll"

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
    "SetMenuData.GetPara":    0x29A2F0,
    "SetMenuData.GetParaSub": 0x29A2A0,
    "CookingMenuData.GetNextExp": 0x264140,
}

CHEATS = [
    {
        "key": "F1",
        "vk": 0x70,
        "name": "无限金钱",
        "desc": "花钱时金额不会减少",
        "patches": [
            (METHODS["SubMoney"], 10, b'\x2B\x45\x0C', b'\x90\x90\x90'),
            (METHODS["SubMoney"], 15, b'\x1B\x55\x10', b'\x90\x90\x90'),
        ],
    },
    {
        "key": "F2",
        "vk": 0x71,
        "name": "无限研究点",
        "desc": "研究点数不会减少",
        "patches": [
            (METHODS["SubPoint"], 0, b'\x55\x8B\xEC\x83\xEC', b'\xC3\x8B\xEC\x83\xEC'),
        ],
    },
    {
        "key": "F3",
        "vk": 0x72,
        "name": "无限满意度",
        "desc": "顾客满意度不会减少",
        "patches": [
            (METHODS["SubManzoku"], 0, b'\x55\x8B\xEC\x80\x3D', b'\xC3\x8B\xEC\x80\x3D'),
        ],
    },
    {
        "key": "F4",
        "vk": 0x73,
        "name": "免费员工升级",
        "desc": "员工升级费用为0",
        "patches": [
            (METHODS["GetLevelUpCost"], 3, b'\x8B\x45\x08\x6A', b'\x33\xC0\x5D\xC3'),
        ],
    },
    {
        "key": "F5",
        "vk": 0x74,
        "name": "员工全属性999",
        "desc": "服务/魅力/料理/感知全部为999",
        "patches": [
            (METHODS["ClerkData.GetParameter"], 0,
             b'\x55\x8B\xEC\x8B\x4D\x08\x8B\x41\x44\x85',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    {
        "key": "F6",
        "vk": 0x75,
        "name": "饮品满属性",
        "desc": "所有饮品参数为999",
        "patches": [
            (METHODS["MakeMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x80\x3D\xC8\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["MakeMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xC9\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    {
        "key": "F7",
        "vk": 0x76,
        "name": "料理满属性",
        "desc": "所有料理参数为999",
        "patches": [
            (METHODS["CookingMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x8B\x45\x0C\x83\xF8\x01\x74',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["CookingMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xA3\x04\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    {
        "key": "F8",
        "vk": 0x77,
        "name": "套餐满属性",
        "desc": "所有套餐参数为999",
        "patches": [
            (METHODS["SetMenuData.GetPara"], 0,
             b'\x55\x8B\xEC\x80\x3D\xE6\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
            (METHODS["SetMenuData.GetParaSub"], 0,
             b'\x55\x8B\xEC\x80\x3D\xE7\x05\xCF\x10\x00',
             b'\x55\x8B\xEC\xB8\xE7\x03\x00\x00\x5D\xC3'),
        ],
    },
    {
        "key": "F9",
        "vk": 0x78,
        "name": "料理瞬间升级",
        "desc": "料理升级所需经验为0",
        "patches": [
            (METHODS["CookingMenuData.GetNextExp"], 0,
             b'\x55\x8B\xEC\x8B\x45\x08\x8B\x40\x78',
             b'\x55\x8B\xEC\x33\xC0\x5D\xC3\x90\x90'),
        ],
    },
]

GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [ctypes.c_int]
GetAsyncKeyState.restype = ctypes.wintypes.SHORT
VK_F10 = 0x79


class TrainerApp:
    def __init__(self):
        self.pm = None
        self.base = 0
        self.attached = False
        self.states = {c["key"]: False for c in CHEATS}
        self.running = True

        self.root = tk.Tk()
        self.root.title("创意咖啡物语 修改器")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")
        self.root.attributes("-topmost", True)

        # Set icon
        import os
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trainer.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        self._build_ui()
        self._start_hotkey_thread()

    def _build_ui(self):
        # Title
        title = tk.Label(
            self.root, text="创意咖啡物语 修改器",
            font=("Microsoft YaHei", 14, "bold"), fg="#e94560", bg="#1a1a2e"
        )
        title.pack(pady=(10, 2))

        # Status
        self.status_var = tk.StringVar(value="未连接游戏")
        status = tk.Label(
            self.root, textvariable=self.status_var,
            font=("Microsoft YaHei", 9), fg="#aaaaaa", bg="#1a1a2e"
        )
        status.pack(pady=(0, 8))

        # Attach button
        self.attach_btn = tk.Button(
            self.root, text="连接游戏", command=self.attach,
            font=("Microsoft YaHei", 10), bg="#16213e", fg="#e94560",
            activebackground="#0f3460", activeforeground="#ffffff",
            relief="flat", padx=20, pady=4
        )
        self.attach_btn.pack(pady=(0, 10))

        # Cheat buttons
        self.buttons = {}
        for cheat in CHEATS:
            frame = tk.Frame(self.root, bg="#1a1a2e")
            frame.pack(fill="x", padx=15, pady=2)

            key_label = tk.Label(
                frame, text=f"[{cheat['key']}]",
                font=("Consolas", 10, "bold"), fg="#0f3460", bg="#1a1a2e",
                width=5
            )
            key_label.pack(side="left")

            btn = tk.Button(
                frame, text=f"{cheat['name']}",
                font=("Microsoft YaHei", 10), bg="#16213e", fg="#888888",
                activebackground="#0f3460", activeforeground="#ffffff",
                relief="flat", anchor="w", padx=10, width=16,
                state="disabled",
                command=lambda k=cheat["key"]: self.toggle(k)
            )
            btn.pack(side="left", fill="x", expand=True)

            state_label = tk.Label(
                frame, text="关", font=("Microsoft YaHei", 9, "bold"),
                fg="#666666", bg="#1a1a2e", width=4
            )
            state_label.pack(side="right")

            self.buttons[cheat["key"]] = (btn, state_label)

        # Footer
        footer = tk.Label(
            self.root, text="F10 = 退出  |  游戏版本 v1.32",
            font=("Microsoft YaHei", 8), fg="#444444", bg="#1a1a2e"
        )
        footer.pack(pady=(10, 8))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def attach(self):
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
        except pymem.exception.ProcessNotFound:
            messagebox.showerror("错误", f"未找到 {PROCESS_NAME}\n请先启动游戏。")
            return
        except Exception as e:
            messagebox.showerror("错误", f"连接失败:\n{e}\n\n请尝试以管理员身份运行。")
            return

        module = pymem.process.module_from_name(self.pm.process_handle, MODULE_NAME)
        if not module:
            messagebox.showerror("错误", f"进程中未找到 {MODULE_NAME}。")
            return

        self.base = module.lpBaseOfDll

        # Verify game version
        addr = self.base + METHODS["SubMoney"]
        try:
            check = self.pm.read_bytes(addr, 3)
        except Exception:
            messagebox.showerror("错误", "无法读取游戏内存。\n请尝试以管理员身份运行。")
            return

        if check != b'\x55\x8B\xEC':
            messagebox.showwarning(
                "警告",
                f"SubMoney处字节不匹配: {check.hex()}\n"
                "游戏版本可能不兼容 (需要 v1.32)。\n"
                "修改可能导致游戏崩溃！"
            )

        self.attached = True
        self.status_var.set(f"已连接 (PID {self.pm.process_id})")
        self.attach_btn.configure(state="disabled", text="已连接")

        for key, (btn, _) in self.buttons.items():
            btn.configure(state="normal", fg="#e0e0e0")

        messagebox.showinfo("成功", "已成功连接到游戏！\n使用F1-F9切换功能，F10退出。")

    def toggle(self, key):
        if not self.attached:
            return

        cheat = next(c for c in CHEATS if c["key"] == key)
        new_state = not self.states[key]

        try:
            for rva, offset, orig, patch in cheat["patches"]:
                addr = self.base + rva + offset
                data = patch if new_state else orig
                self.pm.write_bytes(addr, data, len(data))
        except Exception as e:
            messagebox.showerror("错误", f"写入内存失败:\n{e}")
            return

        self.states[key] = new_state
        btn, state_label = self.buttons[key]

        if new_state:
            state_label.configure(text="开", fg="#00ff88")
            btn.configure(bg="#0f3460")
        else:
            state_label.configure(text="关", fg="#666666")
            btn.configure(bg="#16213e")

    def _start_hotkey_thread(self):
        def monitor():
            prev = {c["vk"]: False for c in CHEATS}
            prev[VK_F10] = False
            while self.running:
                # F10 = exit
                f10 = bool(GetAsyncKeyState(VK_F10) & 0x8000)
                if f10 and not prev[VK_F10]:
                    self.root.after(0, self.on_close)
                prev[VK_F10] = f10

                if self.attached:
                    for cheat in CHEATS:
                        vk = cheat["vk"]
                        down = bool(GetAsyncKeyState(vk) & 0x8000)
                        if down and not prev[vk]:
                            self.root.after(0, self.toggle, cheat["key"])
                        prev[vk] = down

                time.sleep(0.05)

        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    def on_close(self):
        self.running = False
        # Restore all patches
        if self.attached:
            for cheat in CHEATS:
                if self.states.get(cheat["key"]):
                    for rva, offset, orig, patch in cheat["patches"]:
                        try:
                            addr = self.base + rva + offset
                            self.pm.write_bytes(addr, orig, len(orig))
                        except Exception:
                            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TrainerApp()
    app.run()
