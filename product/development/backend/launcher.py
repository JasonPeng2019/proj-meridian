"""Local entry point; the application server is supplied by A03 in B02."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import importlib.util
import os
import sys


def limit_windows_process():
    """Fail before loading data/listening unless kernel resource limits are applied."""
    if os.name != "nt":
        raise RuntimeError("This bounded preview launcher currently supports Windows only.")

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO)] + [
            (name, ctypes.c_size_t) for name in (
                "ProcessMemoryLimit", "JobMemoryLimit", "PeakProcessMemoryUsed", "PeakJobMemoryUsed",
            )
        ]

    class CPU(ctypes.Structure):
        _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    # ACTIVE_PROCESS | PROCESS_MEMORY | JOB_MEMORY; no child breakaway allowed.
    limits.BasicLimitInformation.LimitFlags = 0x8 | 0x100 | 0x200
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.ProcessMemoryLimit = limits.JobMemoryLimit = 512 * 1024 * 1024
    cpu = CPU(5, 1000)  # ENABLE | HARD_CAP; 10% of system CPU.
    for kind, value in ((9, limits), (15, cpu)):
        if not kernel.SetInformationJobObject(job, kind, ctypes.byref(value), ctypes.sizeof(value)):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(job)
            raise error
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    actual_limits, actual_cpu = Extended(), CPU()
    for kind, value in ((9, actual_limits), (15, actual_cpu)):
        if not kernel.QueryInformationJobObject(job, kind, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
    if (actual_limits.BasicLimitInformation.ActiveProcessLimit != 1
            or actual_limits.JobMemoryLimit != 512 * 1024 * 1024
            or actual_cpu.ControlFlags != 5 or actual_cpu.CpuRate != 1000):
        raise RuntimeError("Resource limits were not confirmed; refusing to listen.")
    return kernel, job  # Retain ownership until this process exits.


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Meridian locally.")
    parser.add_argument(
        "--debug", action=argparse.BooleanOptionalAction, default=None,
        help="Show engineering Debug (default hidden; overrides MERIDIAN_DEBUG).",
    )
    args = parser.parse_args()
    if args.debug is not None:
        os.environ["MERIDIAN_DEBUG"] = "1" if args.debug else "0"

    if importlib.util.find_spec("backend.app.main") is None:
        print(
            "Meridian server is not implemented yet. "
            "A03 supplies backend/app/main.py in B02.",
            file=sys.stderr,
        )
        return 1

    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000)
    return 0
