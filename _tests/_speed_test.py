# -*- coding: utf-8 -*-
"""测量 exe 从启动到窗口出现的耗时（按标题全量扫描，兼容 onefile 子进程）"""
import os, sys, time, subprocess, ctypes, tempfile
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
user32 = ctypes.windll.user32
psapi = ctypes.windll.psapi

EnumWindows = user32.EnumWindows
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetWindowThreadProcessId = user32.GetWindowThreadProcessId


def find_any_window(needle="极速看图"):
    """在全部可见窗口里按标题找，不看 PID"""
    found = []

    def cb(hwnd, lparam):
        if not IsWindowVisible(hwnd):
            return True
        n = GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value:
            pid = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((hwnd, buf.value, pid.value))
            return False
        return True

    EnumWindows(Proc(cb), 0)
    return found[0] if found else None


def proc_mem_kb(pid):
    """取进程峰值工作集(KB)"""
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    PROCESS_QUERY_LIMITED = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    c = PROCESS_MEMORY_COUNTERS()
    c.cb = ctypes.sizeof(c)
    ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    ctypes.windll.kernel32.CloseHandle(h)
    if not ok:
        return None
    return c.WorkingSetSize // 1024, c.PeakWorkingSetSize // 1024


TMP = tempfile.mkdtemp(prefix="imgview_speed_")
img = os.path.join(TMP, "t.png")
try:
    from PIL import Image
    Image.new("RGB", (4000, 3000), (40, 90, 160)).save(img)
except Exception:
    pass

CAND = {
    "onefile (单文件 exe)": os.path.join(HERE, "dist", "FastImageViewer.exe"),
    "onedir  (解压目录版)": os.path.join(HERE, "dist", "FIVDebug", "FIVDebug.exe"),
}

for label, exe in CAND.items():
    if not os.path.isfile(exe):
        print("%s : 不存在" % label)
        continue
    runs = []
    mems = []
    for i in range(3):
        t0 = time.perf_counter()
        p = subprocess.Popen([exe, img])
        win = None
        while time.perf_counter() - t0 < 20:
            win = find_any_window()
            if win:
                break
            time.sleep(0.004)
        dt = (time.perf_counter() - t0) * 1000
        if win:
            runs.append(dt)
            m = proc_mem_kb(win[2])
            if m:
                mems.append(m[0])
            print("  %s 第%d次: %.0f ms  (子进程PID %d)" % (label, i + 1, dt, win[2]))
        else:
            print("  %s 第%d次: 20s 内未出现窗口" % (label, i + 1))
        time.sleep(0.5)
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True)
        except Exception:
            pass
        time.sleep(0.7)
    if runs:
        print("  => %s 均值 %.0f ms / 最快 %.0f ms / 常驻内存 %s MB"
              % (label, sum(runs) / len(runs), min(runs),
                 ("%.0f" % (sum(mems) / len(mems) / 1024)) if mems else "n/a"))
    print()

import shutil
shutil.rmtree(TMP, ignore_errors=True)