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
MIN_POINTER_VALUE = 0x10000
MAX_POINTER_VALUE = 0xFFF00000
GAME_ASSEMBLY_NAME = "GameAssembly.dll"
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MAX_MODULE_NAME32 = 255
MAX_PATH = 260
IL2CPP_CLASS_STATIC_FIELDS_OFFSET = 0x5C
IL2CPP_ARRAY_MAX_LENGTH_OFFSET = 0x0C
IL2CPP_ARRAY_ITEMS_OFFSET = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


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


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_char * MAX_PATH),
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

CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
CreateToolhelp32Snapshot.restype = wintypes.HANDLE

Module32First = kernel32.Module32First
Module32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
Module32First.restype = wintypes.BOOL

Module32Next = kernel32.Module32Next
Module32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
Module32Next.restype = wintypes.BOOL


def last_error_message() -> str:
    return ctypes.FormatError(ctypes.get_last_error()).strip()


def pack_int32(value: int) -> bytes:
    return struct.pack("<i", int(value))


def unpack_int32(data: bytes) -> int:
    return struct.unpack("<i", data)[0]


def unpack_int32_from(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def unpack_uint32_from(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def is_pointer_like(value: int) -> bool:
    return value == 0 or MIN_POINTER_VALUE <= value <= MAX_POINTER_VALUE


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


@dataclass(frozen=True)
class IntRange:
    offset: int
    minimum: int
    maximum: int


@dataclass(frozen=True)
class ExperimentalPatchSpec:
    name: str
    scan_size: int
    min_cluster_size: int
    patches: tuple[tuple[int, int], ...]
    typeinfo_offset: int | None = None
    int_ranges: tuple[IntRange, ...] = ()
    pointer_offsets: tuple[int, ...] = ()
    bool_offsets: tuple[int, ...] = ()


@dataclass
class ExperimentalPatchReport:
    name: str
    candidates: int
    patched_objects: int
    note: str = ""


EXPERIMENTAL_UNLOCK_SPECS: tuple[ExperimentalPatchSpec, ...] = (
    ExperimentalPatchSpec(
        name="Food",
        scan_size=0x68,
        min_cluster_size=16,
        patches=((0x60, 1),),
        typeinfo_offset=13274580,
        int_ranges=(
            IntRange(0x3C, 0, 999),
            IntRange(0x40, 0, 500000),
            IntRange(0x54, 0, 10),
            IntRange(0x60, 0, 1),
            IntRange(0x64, 0, 999),
        ),
    ),
    ExperimentalPatchSpec(
        name="ToppingData",
        scan_size=0x58,
        min_cluster_size=16,
        patches=((0x50, 1),),
        typeinfo_offset=13303484,
        int_ranges=(
            IntRange(0x40, 0, 999),
            IntRange(0x44, 0, 500000),
            IntRange(0x48, 0, 10),
            IntRange(0x50, 0, 1),
            IntRange(0x54, 0, 9999),
        ),
    ),
    ExperimentalPatchSpec(
        name="MenuData",
        scan_size=0x88,
        min_cluster_size=12,
        patches=((0x78, 1),),
        typeinfo_offset=13287368,
        int_ranges=(
            IntRange(0x68, 0, 500000),
            IntRange(0x78, 0, 1),
            IntRange(0x7C, 0, 999),
        ),
        bool_offsets=(0x74,),
        pointer_offsets=(0x80, 0x84),
    ),
    ExperimentalPatchSpec(
        name="CookingMenuData",
        scan_size=0x88,
        min_cluster_size=6,
        patches=((0x5C, 1),),
        typeinfo_offset=13269468,
        int_ranges=(
            IntRange(0x44, 0, 500000),
            IntRange(0x58, 0, 10000),
            IntRange(0x5C, 0, 1),
            IntRange(0x68, 0, 20),
            IntRange(0x6C, 0, 500000),
            IntRange(0x70, 0, 999),
            IntRange(0x78, 0, 9),
            IntRange(0x7C, 0, 5000000),
        ),
        pointer_offsets=(0x60, 0x64, 0x74),
    ),
)


EXPERIMENTAL_MAX_SPECS: tuple[ExperimentalPatchSpec, ...] = (
    ExperimentalPatchSpec(
        name="Food",
        scan_size=0x68,
        min_cluster_size=16,
        patches=((0x3C, 99), (0x54, 10), (0x60, 1)),
        typeinfo_offset=13274580,
        int_ranges=(
            IntRange(0x3C, 0, 999),
            IntRange(0x40, 0, 500000),
            IntRange(0x54, 0, 10),
            IntRange(0x60, 0, 1),
            IntRange(0x64, 0, 999),
        ),
    ),
    ExperimentalPatchSpec(
        name="ToppingData",
        scan_size=0x58,
        min_cluster_size=16,
        patches=((0x40, 99), (0x48, 10), (0x50, 1)),
        typeinfo_offset=13303484,
        int_ranges=(
            IntRange(0x40, 0, 999),
            IntRange(0x44, 0, 500000),
            IntRange(0x48, 0, 10),
            IntRange(0x50, 0, 1),
            IntRange(0x54, 0, 9999),
        ),
    ),
    ExperimentalPatchSpec(
        name="CookingMenuData",
        scan_size=0x88,
        min_cluster_size=6,
        patches=((0x5C, 1), (0x68, 9), (0x78, 9), (0x7C, 999999)),
        typeinfo_offset=13269468,
        int_ranges=(
            IntRange(0x44, 0, 500000),
            IntRange(0x58, 0, 10000),
            IntRange(0x5C, 0, 1),
            IntRange(0x68, 0, 20),
            IntRange(0x6C, 0, 500000),
            IntRange(0x70, 0, 999),
            IntRange(0x78, 0, 9),
            IntRange(0x7C, 0, 5000000),
        ),
        pointer_offsets=(0x60, 0x64, 0x74),
    ),
)


class ProcessMemory:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.module_bases: dict[str, int] = {}
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

    def read_uint32(self, address: int) -> int | None:
        data = self.read_bytes(address, 4)
        if data is None or len(data) != 4:
            return None
        return unpack_uint32_from(data, 0)

    def get_module_base(self, module_name: str) -> int | None:
        key = module_name.lower()
        if key in self.module_bases:
            return self.module_bases[key]

        snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        if snapshot in (0, INVALID_HANDLE_VALUE):
            return None

        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        try:
            if not Module32First(snapshot, ctypes.byref(entry)):
                return None
            while True:
                current_name = entry.szModule.decode("utf-8", errors="ignore").lower()
                if current_name == key:
                    base_address = ctypes.addressof(entry.modBaseAddr.contents)
                    self.module_bases[key] = base_address
                    return base_address
                if not Module32Next(snapshot, ctypes.byref(entry)):
                    break
        finally:
            CloseHandle(snapshot)

        return None

    def iter_writable_chunks(self, overlap: int = 0):
        overlap = max(0, overlap)
        for region_base, region_size in self.iter_writable_regions():
            offset = 0
            while offset < region_size:
                read_size = min(SCAN_CHUNK_SIZE, region_size - offset)
                read_length = min(read_size + overlap, region_size - offset)
                data = self.read_bytes(region_base + offset, read_length)
                if data:
                    yield region_base + offset, data
                offset += read_size

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

        for chunk_base, data in self.iter_writable_chunks(3):
            search_limit = max(0, len(data) - 3)
            pos = data.find(target)
            while pos != -1 and pos < search_limit:
                matches.append(chunk_base + pos)
                pos = data.find(target, pos + 1)

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

    def apply_experimental_patches(
        self, specs: tuple[ExperimentalPatchSpec, ...]
    ) -> list[ExperimentalPatchReport]:
        if not specs:
            return []

        reports: list[ExperimentalPatchReport] = []
        heuristic_specs: list[ExperimentalPatchSpec] = []
        heuristic_reports: dict[str, ExperimentalPatchReport] = {}

        for spec in specs:
            if spec.typeinfo_offset is None:
                heuristic_specs.append(spec)
                continue

            addresses, note = self._resolve_static_array_addresses(spec)
            if not addresses:
                reports.append(
                    ExperimentalPatchReport(
                        name=spec.name,
                        candidates=0,
                        patched_objects=0,
                        note=note,
                    )
                )
                continue

            patched_objects = 0
            for address in addresses:
                object_ok = True
                for field_offset, value in spec.patches:
                    if not self.write_int32(address + field_offset, value):
                        object_ok = False
                if object_ok:
                    patched_objects += 1

            note = ""
            if patched_objects != len(addresses):
                note = "Some writes failed."
            reports.append(
                ExperimentalPatchReport(
                    name=spec.name,
                    candidates=len(addresses),
                    patched_objects=patched_objects,
                    note=note,
                )
            )

        if heuristic_specs:
            clusters = self._scan_experimental_clusters(tuple(heuristic_specs))
            for spec in heuristic_specs:
                addresses = clusters.get(spec.name, [])
                if not addresses:
                    heuristic_reports[spec.name] = ExperimentalPatchReport(
                        name=spec.name,
                        candidates=0,
                        patched_objects=0,
                        note="No stable metadata cluster matched.",
                    )
                    continue

                patched_objects = 0
                for address in addresses:
                    object_ok = True
                    for field_offset, value in spec.patches:
                        if not self.write_int32(address + field_offset, value):
                            object_ok = False
                    if object_ok:
                        patched_objects += 1

                note = ""
                if patched_objects != len(addresses):
                    note = "Some writes failed."
                heuristic_reports[spec.name] = ExperimentalPatchReport(
                    name=spec.name,
                    candidates=len(addresses),
                    patched_objects=patched_objects,
                    note=note,
                )

            reports.extend(heuristic_reports[spec.name] for spec in heuristic_specs)

        return reports

    def _resolve_static_array_addresses(
        self, spec: ExperimentalPatchSpec
    ) -> tuple[list[int], str]:
        if spec.typeinfo_offset is None:
            return [], "No direct type info offset is configured."

        module_base = self.get_module_base(GAME_ASSEMBLY_NAME)
        if module_base is None:
            return [], "GameAssembly.dll was not found in the target process."

        typeinfo_slot = module_base + spec.typeinfo_offset
        class_pointer = self.read_uint32(typeinfo_slot)
        if class_pointer is None:
            return [], "The type info slot could not be read."
        if class_pointer & 0xFF000000 == 0x20000000:
            return [], "The type is not initialized in the current in-game screen yet."
        if not is_pointer_like(class_pointer):
            return [], "The type info pointer is not ready."

        static_owner = self.read_uint32(class_pointer + 0x2C) or class_pointer
        static_fields_pointer = self.read_uint32(static_owner + IL2CPP_CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields_pointer:
            return [], "Static fields are not initialized yet."

        data_array_pointer = self.read_uint32(static_fields_pointer)
        if not data_array_pointer:
            return [], "The runtime data array pointer is null."

        array_length = self.read_uint32(data_array_pointer + IL2CPP_ARRAY_MAX_LENGTH_OFFSET)
        if array_length is None or array_length == 0:
            return [], "The runtime data array is empty."
        if array_length > 4096:
            return [], f"Unexpected runtime array length: {array_length}."

        pointer_bytes = self.read_bytes(
            data_array_pointer + IL2CPP_ARRAY_ITEMS_OFFSET,
            array_length * 4,
        )
        if pointer_bytes is None or len(pointer_bytes) < array_length * 4:
            return [], "The runtime data array could not be read completely."

        addresses: list[int] = []
        for index in range(array_length):
            address = unpack_uint32_from(pointer_bytes, index * 4)
            if not is_pointer_like(address) or address == 0:
                continue
            data = self.read_bytes(address, spec.scan_size)
            if data is None or len(data) < spec.scan_size:
                continue
            if not self._looks_like_base_data_object(data, 0):
                continue
            if not self._matches_experimental_spec(data, 0, spec):
                continue
            addresses.append(address)

        if not addresses:
            return [], "The runtime array was found, but no object instances matched the expected layout."

        return addresses, ""

    def _scan_experimental_clusters(
        self, specs: tuple[ExperimentalPatchSpec, ...]
    ) -> dict[str, list[int]]:
        max_scan_size = max(spec.scan_size for spec in specs)
        clustered: dict[str, dict[int, list[int]]] = {spec.name: {} for spec in specs}

        for chunk_base, data in self.iter_writable_chunks(max_scan_size - 4):
            if len(data) < 0x24:
                continue
            limit = len(data) - 0x24 + 1
            for pos in range(0, limit, 4):
                if not self._looks_like_base_data_object(data, pos):
                    continue
                klass = unpack_uint32_from(data, pos)
                for spec in specs:
                    if pos + spec.scan_size > len(data):
                        continue
                    if not self._matches_experimental_spec(data, pos, spec):
                        continue
                    clustered[spec.name].setdefault(klass, []).append(chunk_base + pos)

        selected: dict[str, list[int]] = {}
        for spec in specs:
            best: list[int] = []
            for addresses in clustered[spec.name].values():
                unique_addresses = sorted(set(addresses))
                if len(unique_addresses) > len(best):
                    best = unique_addresses
            selected[spec.name] = best if len(best) >= spec.min_cluster_size else []

        return selected

    @staticmethod
    def _looks_like_base_data_object(data: bytes, pos: int) -> bool:
        if pos + 0x24 > len(data):
            return False
        if not is_pointer_like(unpack_uint32_from(data, pos)):
            return False
        if not is_pointer_like(unpack_uint32_from(data, pos + 0x4)):
            return False
        if not 0 <= unpack_int32_from(data, pos + 0x8) <= 4096:
            return False
        if not -1 <= unpack_int32_from(data, pos + 0xC) <= 8192:
            return False
        if not is_pointer_like(unpack_uint32_from(data, pos + 0x10)):
            return False
        if not 0 <= unpack_int32_from(data, pos + 0x18) <= 0x0FFFFFFF:
            return False
        if data[pos + 0x20] not in (0, 1):
            return False
        if data[pos + 0x21] not in (0, 1):
            return False
        return True

    @staticmethod
    def _matches_experimental_spec(data: bytes, pos: int, spec: ExperimentalPatchSpec) -> bool:
        for int_range in spec.int_ranges:
            value = unpack_int32_from(data, pos + int_range.offset)
            if not int_range.minimum <= value <= int_range.maximum:
                return False
        for pointer_offset in spec.pointer_offsets:
            if not is_pointer_like(unpack_uint32_from(data, pos + pointer_offset)):
                return False
        for bool_offset in spec.bool_offsets:
            if data[pos + bool_offset] not in (0, 1):
                return False
        return True


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
        self.root.geometry("900x640")
        self.root.minsize(760, 520)
        self.root.app = self

        self.process_name = tk.StringVar(value=TARGET_PROCESS)
        self.attach_status = tk.StringVar(value="Not attached.")
        self.global_status = tk.StringVar(
            value="Offline single-player only. Start the game, then attach and scan."
        )
        self.experimental_status = tk.StringVar(
            value="Experimental one-click patches use IL2CPP runtime tables. Back up your save first."
        )
        self.process_memory: ProcessMemory | None = None
        self.busy = False
        self.experimental_buttons: list[ttk.Button] = []

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

        experimental_box = ttk.LabelFrame(quick_tab, text="Experimental Metadata Patches")
        experimental_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        experimental_box.columnconfigure(0, weight=1)
        experimental_box.columnconfigure(1, weight=1)

        ttk.Label(
            experimental_box,
            text=(
                "These buttons resolve IL2CPP runtime data tables directly. "
                "They are much faster than a deep memory scan, but some tables only initialize after you open the related in-game screen once."
            ),
            wraplength=780,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 4))
        self._experimental_button(
            experimental_box,
            "Unlock Recipes / Menus",
            self.run_experimental_unlocks,
            1,
            0,
        )
        self._experimental_button(
            experimental_box,
            "Max Rank / Stock",
            self.run_experimental_max,
            1,
            1,
        )
        ttk.Label(
            experimental_box,
            textvariable=self.experimental_status,
            wraplength=780,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 6))

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
                    "- Experimental one-click recipe/menu unlocks for some metadata tables",
                    "",
                    "What the experimental buttons now try to cover:",
                    "- MenuData and CookingMenuData unlock states",
                    "- Food and ToppingData unlocks after those tables initialize in-game",
                    "- Rank / stock boosts for food, toppings, and cooking items",
                    "",
                    "What still needs deeper reverse engineering before it is dependable:",
                    "- Shop item states",
                    "- Staff level-up and staff manager values",
                    "- Facility stats and facility quality",
                    "- Satisfaction / popularity related totals",
                    "",
                    "Important:",
                    "- This trainer is for offline single-player use only.",
                    "- After restarting the game, rescan values because addresses can move.",
                    "- The generic scanner assumes 32-bit signed integers.",
                    "- Experimental buttons depend on runtime table initialization. Make a backup save before using them.",
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
        state = "disabled" if busy else "normal"
        for button in self.experimental_buttons:
            button.config(state=state)
        if status:
            self.global_status.set(status)

    def _experimental_button(self, master: tk.Misc, text: str, command, row: int, column: int) -> None:
        button = ttk.Button(master, text=text, command=command)
        button.grid(row=row, column=column, sticky="ew", padx=6, pady=6)
        self.experimental_buttons.append(button)

    def require_process(self) -> ProcessMemory:
        if self.process_memory is None:
            raise RuntimeError("Attach to the running game first.")
        return self.process_memory

    def get_process_or_warn(self) -> ProcessMemory | None:
        try:
            return self.require_process()
        except RuntimeError as exc:
            messagebox.showwarning("Attach First", str(exc))
            return None

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
        memory = self.get_process_or_warn()
        if memory is None:
            return

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
        memory = self.get_process_or_warn()
        if memory is None:
            return

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
        memory = self.get_process_or_warn()
        if memory is None:
            return

        def task() -> int:
            return memory.write_many_int32(frame.scan.addresses, value)

        def on_success(success_count: int) -> None:
            frame.update_status(
                f"Wrote {value} to {success_count} candidate address(es) for {frame.label.lower()}."
            )
            self.set_busy(False, "Write complete.")

        self._run_memory_task(f"Writing {frame.label.lower()}...", task, on_success)

    def run_experimental_unlocks(self) -> None:
        self._run_experimental_preset("Experimental unlocks", EXPERIMENTAL_UNLOCK_SPECS)

    def run_experimental_max(self) -> None:
        self._run_experimental_preset("Experimental max patch", EXPERIMENTAL_MAX_SPECS)

    def _run_experimental_preset(
        self, label: str, specs: tuple[ExperimentalPatchSpec, ...]
    ) -> None:
        memory = self.get_process_or_warn()
        if memory is None:
            return

        def task() -> list[ExperimentalPatchReport]:
            return memory.apply_experimental_patches(specs)

        def on_success(reports: list[ExperimentalPatchReport]) -> None:
            summary = self._format_experimental_summary(label, reports)
            self.experimental_status.set(summary)
            self.set_busy(False, f"{label} complete.")
            if any(report.patched_objects for report in reports):
                messagebox.showinfo("Experimental Patch Complete", summary)
            else:
                messagebox.showwarning("No Matches", summary)

        self._run_memory_task(f"{label}...", task, on_success)

    def _format_experimental_summary(
        self, label: str, reports: list[ExperimentalPatchReport]
    ) -> str:
        updated = [
            f"{report.name} {report.patched_objects}/{report.candidates}"
            for report in reports
            if report.patched_objects
        ]
        missing = [
            f"{report.name} ({report.note})" if report.note else report.name
            for report in reports
            if report.candidates == 0
        ]
        partial = [
            report.name
            for report in reports
            if report.candidates and report.patched_objects != report.candidates
        ]

        parts: list[str] = []
        if updated:
            parts.append("updated: " + ", ".join(updated))
        if partial:
            parts.append("partial: " + ", ".join(partial))
        if missing:
            parts.append("not found: " + ", ".join(missing))
        if not parts:
            parts.append("no matching metadata clusters found; try opening a loaded save first.")
        return f"{label}: " + " | ".join(parts)

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
    arena = ctypes.create_string_buffer(0x800)
    fake_spec = ExperimentalPatchSpec(
        name="SelfTestFood",
        scan_size=0x68,
        min_cluster_size=6,
        patches=((0x3C, 99), (0x54, 10), (0x60, 1)),
        int_ranges=(
            IntRange(0x3C, 1, 16),
            IntRange(0x40, 100, 100),
            IntRange(0x54, 0, 7),
            IntRange(0x60, 0, 0),
            IntRange(0x64, 0, 0),
        ),
    )

    for index in range(8):
        base = index * 0x80
        struct.pack_into("<I", arena, base + 0x0, 0x40102030)
        struct.pack_into("<I", arena, base + 0x4, 0)
        struct.pack_into("<i", arena, base + 0x8, index)
        struct.pack_into("<i", arena, base + 0xC, index)
        struct.pack_into("<I", arena, base + 0x10, 0x40103040)
        struct.pack_into("<I", arena, base + 0x14, 0)
        struct.pack_into("<i", arena, base + 0x18, 1)
        struct.pack_into("<i", arena, base + 0x1C, 0)
        struct.pack_into("<B", arena, base + 0x20, 0)
        struct.pack_into("<B", arena, base + 0x21, 0)
        struct.pack_into("<i", arena, base + 0x3C, index + 1)
        struct.pack_into("<i", arena, base + 0x40, 100)
        struct.pack_into("<i", arena, base + 0x54, index)
        struct.pack_into("<i", arena, base + 0x60, 0)
        struct.pack_into("<i", arena, base + 0x64, 0)

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

        reports = memory.apply_experimental_patches((fake_spec,))
        if not reports or reports[0].patched_objects < 6:
            raise RuntimeError("Experimental patch scan did not find the fake object cluster.")

    for index in range(8):
        base = index * 0x80
        if unpack_int32_from(arena, base + 0x3C) != 99:
            raise RuntimeError("Experimental patch did not update fake stock values.")
        if unpack_int32_from(arena, base + 0x54) != 10:
            raise RuntimeError("Experimental patch did not update fake rank values.")
        if unpack_int32_from(arena, base + 0x60) != 1:
            raise RuntimeError("Experimental patch did not update fake state values.")

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
