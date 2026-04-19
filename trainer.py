#!/usr/bin/env python3
"""Cafe Blend Story trainer for offline single-player use.

This tool focuses on the values that are practical to change quickly from the
outside: money and research points. It also includes a generic integer scanner
for experimenting with other values in the running process.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import subprocess
import sys
import threading
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass, field
from tkinter import messagebox, ttk


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

WRITABLE_PAGE_FLAGS = {
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}

SCAN_CHUNK_SIZE = 4 * 1024 * 1024
FREEZE_INTERVAL_MS = 250
TARGET_PROCESS = "KairoGames.exe"


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL

WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
WriteProcessMemory.restype = wintypes.BOOL

VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
VirtualQueryEx.restype = ctypes.c_size_t


def last_error_message() -> str:
    return ctypes.FormatError(ctypes.get_last_error()).strip()


def pack_int32(value: int) -> bytes:
    return struct.pack("<i", int(value))


def unpack_int32(data: bytes) -> int:
    return struct.unpack("<i", data)[0]


def find_processes_by_name(name: str) -> list[tuple[int, str]]:
    command = [
        "tasklist",
        "/FO",
        "CSV",
        "/NH",
        "/FI",
        f"IMAGENAME eq {name}",
    ]
    output = subprocess.check_output(command, text=True, encoding="utf-8", errors="ignore")
    results: list[tuple[int, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("INFO:"):
            continue
        parts = [part.strip().strip('"') for part in line.split('","')]
        if len(parts) < 2:
            continue
        image_name = parts[0].strip('"')
        try:
            pid = int(parts[1].strip('"'))
        except ValueError:
            continue
        results.append((pid, image_name))
    return results


@dataclass
class ScanResult:
    label: str
    addresses: list[int] = field(default_factory=list)
    last_value: int | None = None

    def clear(self) -> None:
        self.addresses.clear()
        self.last_value = None

    @property
    def count(self) -> int:
        return len(self.addresses)


class ProcessMemory:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.handle = OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE,
            False,
            pid,
        )
        if not self.handle:
            raise OSError(f"OpenProcess failed: {last_error_message()}")

    def close(self) -> None:
        if self.handle:
            CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "ProcessMemory":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def iter_writable_regions(self) -> list[tuple[int, int]]:
        regions: list[tuple[int, int]] = []
        address = 0
        max_address = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
        mbi = MEMORY_BASIC_INFORMATION()

        while address < max_address:
            result = VirtualQueryEx(
                self.handle,
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if not result:
                break

            base_address = int(mbi.BaseAddress or 0)
            region_size = int(mbi.RegionSize or 0)
            protection = int(mbi.Protect or 0)
            base_protection = protection & 0xFF

            if (
                mbi.State == MEM_COMMIT
                and region_size > 0
                and not (protection & PAGE_GUARD)
                and base_protection != PAGE_NOACCESS
                and base_protection in WRITABLE_PAGE_FLAGS
            ):
                regions.append((base_address, region_size))

            next_address = base_address + region_size
            if next_address <= address:
                break
            address = next_address

        return regions

    def read_bytes(self, address: int, size: int) -> bytes | None:
        if size <= 0:
            return b""
        buffer = (ctypes.c_ubyte * size)()
        bytes_read = ctypes.c_size_t()
        success = ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read),
        )
        if not success or bytes_read.value == 0:
            return None
        return bytes(buffer[: bytes_read.value])

    def read_int32(self, address: int) -> int | None:
        data = self.read_bytes(address, 4)
        if data is None or len(data) != 4:
            return None
        return unpack_int32(data)

    def write_int32(self, address: int, value: int) -> bool:
        packed = pack_int32(value)
        written = ctypes.c_size_t()
        source = ctypes.create_string_buffer(packed)
        success = WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            source,
            len(packed),
            ctypes.byref(written),
        )
        return bool(success and written.value == len(packed))

    def scan_int32(self, value: int) -> list[int]:
        target = pack_int32(value)
        matches: list[int] = []

        for region_base, region_size in self.iter_writable_regions():
            offset = 0
            while offset < region_size:
                read_size = min(SCAN_CHUNK_SIZE, region_size - offset)
                read_length = min(read_size + 3, region_size - offset)
                data = self.read_bytes(region_base + offset, read_length)
                if data:
                    search_limit = max(0, len(data) - 3)
                    pos = data.find(target)
                    while pos != -1 and pos < search_limit:
                        matches.append(region_base + offset + pos)
                        pos = data.find(target, pos + 1)
                offset += read_size

        return matches

    def filter_int32(self, addresses: list[int], value: int) -> list[int]:
        matches: list[int] = []
        for address in addresses:
            current = self.read_int32(address)
            if current == value:
                matches.append(address)
        return matches

    def write_many_int32(self, addresses: list[int], value: int) -> int:
        success_count = 0
        for address in addresses:
            if self.write_int32(address, value):
                success_count += 1
        return success_count


class ValueHackFrame(ttk.LabelFrame):
    def __init__(self, master: tk.Misc, label: str) -> None:
        super().__init__(master, text=label)
        self.label = label
        self.current_value = tk.StringVar()
        self.target_value = tk.StringVar()
        self.freeze_enabled = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="No scan yet.")
        self.matches_text = tk.StringVar(value="Candidates: 0")
        self.scan = ScanResult(label=label)
        self.buttons: list[ttk.Button] = []

        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.columnconfigure(3, weight=1)

        ttk.Label(self, text="Observed in-game value").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(self, textvariable=self.current_value, width=18).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._button("New Scan", self.on_new_scan, 0, 2)
        self._button("Refine", self.on_refine, 0, 3)

        ttk.Label(self, text="Value to write / lock").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(self, textvariable=self.target_value, width=18).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self._button("Set Value", self.on_set_value, 1, 2)
        ttk.Checkbutton(self, text="Freeze", variable=self.freeze_enabled).grid(row=1, column=3, sticky="w", padx=6, pady=6)

        ttk.Label(self, textvariable=self.matches_text).grid(row=2, column=0, sticky="w", padx=6, pady=(0, 6))
        ttk.Label(self, textvariable=self.status_text).grid(row=2, column=1, columnspan=3, sticky="w", padx=6, pady=(0, 6))

    def _button(self, text: str, command, row: int, column: int) -> None:
        button = ttk.Button(self, text=text, command=command)
        button.grid(row=row, column=column, sticky="ew", padx=6, pady=6)
        self.buttons.append(button)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.buttons:
            button.config(state=state)

    def update_status(self, message: str) -> None:
        self.status_text.set(message)
        self.matches_text.set(f"Candidates: {self.scan.count}")

    def parse_current(self) -> int:
        return int(self.current_value.get().strip())

    def parse_target(self) -> int:
        return int(self.target_value.get().strip())

    def on_new_scan(self) -> None:
        app: TrainerApp = self.winfo_toplevel().app
        app.start_new_scan(self)

    def on_refine(self) -> None:
        app: TrainerApp = self.winfo_toplevel().app
        app.refine_scan(self)

    def on_set_value(self) -> None:
        app: TrainerApp = self.winfo_toplevel().app
        app.write_value(self)


class TrainerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Cafe Blend Story Trainer")
        self.root.geometry("860x520")
        self.root.minsize(760, 460)
        self.root.app = self

        self.process_name = tk.StringVar(value=TARGET_PROCESS)
        self.attach_status = tk.StringVar(value="Not attached.")
        self.global_status = tk.StringVar(
            value="Offline single-player only. Start the game, then attach and scan."
        )
        self.process_memory: ProcessMemory | None = None
        self.busy = False

        self._build()
        self._schedule_freeze_tick()

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Process").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(top, textvariable=self.process_name).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="Attach", command=self.attach_to_process).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(top, text="Detach", command=self.detach).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(top, textvariable=self.attach_status).grid(row=0, column=4, sticky="w")

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        quick_tab = ttk.Frame(notebook, padding=10)
        quick_tab.columnconfigure(0, weight=1)
        notebook.add(quick_tab, text="Quick Trainer")

        self.money_frame = ValueHackFrame(quick_tab, "Money")
        self.money_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.research_frame = ValueHackFrame(quick_tab, "Research Points")
        self.research_frame.grid(row=1, column=0, sticky="ew")

        generic_tab = ttk.Frame(notebook, padding=10)
        generic_tab.columnconfigure(0, weight=1)
        notebook.add(generic_tab, text="Generic Integer Scan")
        self.generic_frame = ValueHackFrame(generic_tab, "Generic Integer Value")
        self.generic_frame.grid(row=0, column=0, sticky="ew")

        notes_tab = ttk.Frame(notebook, padding=10)
        notes_tab.columnconfigure(0, weight=1)
        notes_tab.rowconfigure(0, weight=1)
        notebook.add(notes_tab, text="Notes")
        notes = tk.Text(notes_tab, wrap="word", height=20)
        notes.grid(row=0, column=0, sticky="nsew")
        notes.insert(
            "1.0",
            "\n".join(
                [
                    "Recommended flow:",
                    "1. Start Cafe Blend Story and enter the save you want to modify.",
                    "2. Attach to KairoGames.exe.",
                    "3. Enter the visible number from the UI and press New Scan.",
                    "4. Change that number in-game, then type the new number and press Refine.",
                    "5. Repeat until the candidate count is small, then Set Value or enable Freeze.",
                    "",
                    "What this version is built for:",
                    "- Money",
                    "- Research Points",
                    "- Any other 32-bit integer value you can identify manually",
                    "",
                    "What looks possible from the game metadata but is not one-click yet:",
                    "- Staff level-up and staff manager values",
                    "- Facility stats and facility quality",
                    "- Satisfaction / popularity related totals",
                    "- Unlock flags and some shop/item states",
                    "",
                    "Important:",
                    "- This trainer is for offline single-player use only.",
                    "- After restarting the game, rescan values because addresses can move.",
                    "- The generic scanner assumes 32-bit signed integers.",
                ]
            ),
        )
        notes.config(state="disabled")

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.global_status).grid(row=0, column=0, sticky="w")

    def set_busy(self, busy: bool, status: str | None = None) -> None:
        self.busy = busy
        for frame in (self.money_frame, self.research_frame, self.generic_frame):
            frame.set_busy(busy)
        if status:
            self.global_status.set(status)

    def require_process(self) -> ProcessMemory:
        if self.process_memory is None:
            raise RuntimeError("Attach to the running game first.")
        return self.process_memory

    def attach_to_process(self) -> None:
        if self.busy:
            return
        name = self.process_name.get().strip() or TARGET_PROCESS
        try:
            matches = find_processes_by_name(name)
        except Exception as exc:
            messagebox.showerror("Attach Failed", str(exc))
            return

        if not matches:
            messagebox.showwarning("Process Not Found", f"No running process named {name} was found.")
            return

        pid, image_name = matches[0]
        self.detach()
        try:
            self.process_memory = ProcessMemory(pid)
        except Exception as exc:
            messagebox.showerror("Attach Failed", str(exc))
            self.process_memory = None
            return

        self.attach_status.set(f"Attached to {image_name} (PID {pid})")
        self.global_status.set("Attached. You can scan values now.")

    def detach(self) -> None:
        if self.process_memory is not None:
            self.process_memory.close()
            self.process_memory = None
        self.attach_status.set("Not attached.")
        self.global_status.set("Detached.")

    def _run_memory_task(self, status: str, task, on_success) -> None:
        if self.busy:
            return

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:  # pragma: no cover - UI path
                self.root.after(0, lambda: self._finish_task_error(exc))
                return
            self.root.after(0, lambda: on_success(result))

        self.set_busy(True, status)
        threading.Thread(target=worker, daemon=True).start()

    def _finish_task_error(self, exc: Exception) -> None:
        self.set_busy(False, "Ready.")
        messagebox.showerror("Operation Failed", str(exc))

    def start_new_scan(self, frame: ValueHackFrame) -> None:
        value = self._parse_value(frame.current_value, "observed value")
        if value is None:
            return
        frame.freeze_enabled.set(False)
        memory = self.require_process()

        def task() -> list[int]:
            return memory.scan_int32(value)

        def on_success(addresses: list[int]) -> None:
            frame.scan.addresses = addresses
            frame.scan.last_value = value
            frame.update_status(f"Initial scan complete for {frame.label.lower()}.")
            self.set_busy(False, "Scan complete.")

        self._run_memory_task(f"Scanning {frame.label.lower()}...", task, on_success)

    def refine_scan(self, frame: ValueHackFrame) -> None:
        value = self._parse_value(frame.current_value, "observed value")
        if value is None:
            return
        if not frame.scan.addresses:
            messagebox.showinfo("No Scan Yet", "Run a new scan first.")
            return
        memory = self.require_process()

        def task() -> list[int]:
            return memory.filter_int32(frame.scan.addresses, value)

        def on_success(addresses: list[int]) -> None:
            frame.scan.addresses = addresses
            frame.scan.last_value = value
            frame.update_status(f"Refine complete for {frame.label.lower()}.")
            self.set_busy(False, "Refine complete.")

        self._run_memory_task(f"Refining {frame.label.lower()}...", task, on_success)

    def write_value(self, frame: ValueHackFrame) -> None:
        value = self._parse_value(frame.target_value, "target value")
        if value is None:
            return
        if not frame.scan.addresses:
            messagebox.showinfo("No Candidates", "Scan and refine a value before writing.")
            return
        memory = self.require_process()

        def task() -> int:
            return memory.write_many_int32(frame.scan.addresses, value)

        def on_success(success_count: int) -> None:
            frame.update_status(
                f"Wrote {value} to {success_count} candidate address(es) for {frame.label.lower()}."
            )
            self.set_busy(False, "Write complete.")

        self._run_memory_task(f"Writing {frame.label.lower()}...", task, on_success)

    def _parse_value(self, variable: tk.StringVar, field_name: str) -> int | None:
        raw = variable.get().strip()
        try:
            return int(raw)
        except ValueError:
            messagebox.showwarning("Invalid Value", f"Enter a valid integer for {field_name}.")
            return None

    def _schedule_freeze_tick(self) -> None:
        self.root.after(FREEZE_INTERVAL_MS, self._freeze_tick)

    def _freeze_tick(self) -> None:
        try:
            if not self.busy and self.process_memory is not None:
                for frame in (self.money_frame, self.research_frame, self.generic_frame):
                    if not frame.freeze_enabled.get() or not frame.scan.addresses:
                        continue
                    try:
                        value = frame.parse_target()
                    except ValueError:
                        continue
                    self.process_memory.write_many_int32(frame.scan.addresses, value)
        finally:
            self._schedule_freeze_tick()


def run_self_test() -> int:
    print("Running self-test against the current Python process...")
    probe = ctypes.c_int(13579)
    with ProcessMemory(os.getpid()) as memory:
        initial_matches = memory.scan_int32(probe.value)
        if not initial_matches:
            raise RuntimeError("Initial scan found no matching values.")

        probe.value = 24680
        refined = memory.filter_int32(initial_matches, probe.value)
        if not refined:
            raise RuntimeError("Refine step found no matching values.")

        written = memory.write_many_int32(refined, 777777)
        if written == 0:
            raise RuntimeError("Write step failed for all candidates.")

        if probe.value != 777777:
            raise RuntimeError("Probe value did not change after writing memory.")

    print("Self-test passed.")
    return 0


def run_gui() -> int:
    root = tk.Tk()
    app = TrainerApp(root)
    try:
        root.mainloop()
    finally:
        app.detach()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cafe Blend Story trainer")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a local memory scanner self-test instead of opening the GUI.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.self_test:
        return run_self_test()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
