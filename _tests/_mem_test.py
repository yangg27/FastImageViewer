# -*- coding: utf-8 -*-
"""测量超大图打开时的真实内存峰值"""
import os, sys, time, tempfile, ctypes, shutil
from ctypes import wintypes
import importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, ".venv-build", "Lib", "site-packages"))

spec = importlib.util.spec_from_file_location("v", os.path.join(HERE, "viewer.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m._load_pil()
m.messagebox.showerror = lambda *a, **k: None
from PIL import Image
import tkinter as tk


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def mem():
    """当前进程 工作集/峰值 (MB)"""
    h = ctypes.windll.kernel32.GetCurrentProcess()
    c = PMC(); c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    return c.WorkingSetSize / 1048576.0, c.PeakWorkingSetSize / 1048576.0


TMP = tempfile.mkdtemp(prefix="fiv_mem_")
print("=" * 72)
print(" 超大图内存实测")
print("=" * 72)

root = tk.Tk()
app = m.ImageViewer(root, [])
root.update_idletasks(); root.update()
base, _ = mem()
print("  基线内存: %.0f MB\n" % base)

tests = [
    ("PNG 15000x15000 (2.25亿像素)", "huge.png",
     lambda p: Image.new("RGB", (15000, 15000), (60, 90, 140)).save(p)),
    ("PNG 10000x10000 (1亿像素)", "big.png",
     lambda p: Image.new("RGB", (10000, 10000), (60, 90, 140)).save(p)),
    ("JPEG 12000x12000 (1.44亿像素)", "huge.jpg",
     lambda p: Image.new("RGB", (12000, 12000), (160, 120, 80)).save(p, quality=90)),
    ("BMP 8000x8000 (6400万像素)", "big.bmp",
     lambda p: Image.new("RGB", (8000, 8000), (100, 100, 100)).save(p)),
    ("TIFF 8000x8000 未压缩", "big.tiff",
     lambda p: Image.new("RGB", (8000, 8000), (100, 100, 100)).save(p, compression="raw")),
]

for name, fn_name, maker in tests:
    p = os.path.join(TMP, fn_name)
    try:
        maker(p)
    except Exception as e:
        print("  [SKIP] %s 造图失败: %s" % (name, e))
        continue
    sz = os.path.getsize(p) / 1048576.0
    before, _ = mem()
    t0 = time.time()
    try:
        ok = app.open(p)
        root.update_idletasks(); root.update()
        app.render()
        root.update_idletasks(); root.update()
    except Exception as e:
        print("  [FAIL] %s  %s" % (name, e))
        continue
    dt = time.time() - t0
    after, peak = mem()
    print("  %s %-32s" % ("[OK]  " if ok else "[FAIL]", name))
    print("        文件 %.1f MB | 打开 %.1fs | 内存 %.0f→%.0f MB (峰值 %.0f MB)"
          % (sz, dt, before, after, peak))
    os.remove(p)

try:
    root.destroy()
except Exception:
    pass
shutil.rmtree(TMP, ignore_errors=True)