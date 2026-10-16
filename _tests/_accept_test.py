# -*- coding: utf-8 -*-
"""最终验收：速度 + 三大功能 + 双击唤起"""
import os, sys, time, ctypes, tempfile, subprocess, shutil, winreg
from ctypes import wintypes
from PIL import Image

user32 = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EXE = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "FastImageViewer", "FastImageViewer.exe")


def find_window(needle="极速看图"):
    r = []
    def cb(h, l):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, b, n + 1)
        if needle in b.value:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r.append((h, b.value, pid.value))
            return False
        return True
    user32.EnumWindows(Proc(cb), 0)
    return r[0] if r else None


def kill():
    subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"], capture_output=True)
    time.sleep(0.7)


def mem_kb(pid):
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
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    c = PMC(); c.cb = ctypes.sizeof(c)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    ctypes.windll.kernel32.CloseHandle(h)
    return (c.WorkingSetSize // 1024) if ok else None


print("=" * 68)
print(" 极速看图 FastImageViewer  最终验收")
print("=" * 68)
print(" 程序: %s" % EXE)
print(" 存在: %s   大小: %.1f MB" % (
    os.path.isfile(EXE), os.path.getsize(EXE) / 1048576 if os.path.isfile(EXE) else 0))
print()

TMP = tempfile.mkdtemp(prefix="fiv_accept_")

# ---------- 1. 启动速度 ----------
print("=" * 68)
print(" [1] 启动速度（4000x3000 大图）")
print("=" * 68)
big = os.path.join(TMP, "big.png")
Image.new("RGB", (4000, 3000), (50, 100, 170)).save(big)
runs, mems = [], []
for i in range(5):
    kill()
    t0 = time.perf_counter()
    p = subprocess.Popen([EXE, big])
    w = None
    while time.perf_counter() - t0 < 20:
        w = find_window()
        if w:
            break
        time.sleep(0.004)
    dt = (time.perf_counter() - t0) * 1000
    if w:
        runs.append(dt)
        m = mem_kb(w[2])
        if m:
            mems.append(m)
        print("  第%d次: %6.0f ms   内存 %s MB" % (i + 1, dt, "%.0f" % (m / 1024) if m else "n/a"))
    else:
        print("  第%d次: 超时" % (i + 1))
if runs:
    print("  ─────────────────────────────────────")
    print("  启动均值 %.0f ms   最快 %.0f ms   最慢 %.0f ms"
          % (sum(runs) / len(runs), min(runs), max(runs)))
    if mems:
        print("  常驻内存 %.0f MB" % (sum(mems) / len(mems) / 1024))
kill()

# ---------- 2. 三大功能 ----------
print()
print("=" * 68)
print(" [2] 三大功能实测")
print("=" * 68)
import importlib.util
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("v", os.path.join(HERE, "viewer.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.messagebox.showerror = lambda *a, **k: None
import tkinter as tk
root = tk.Tk()
f = os.path.join(TMP, "func.png")
Image.new("RGBA", (400, 300), (200, 60, 60, 200)).save(f)
app = m.ImageViewer(root, [f])
SAVE = os.path.join(TMP, "saved")
app.save_dir = SAVE
res = []


def t_open():
    res.append(("打开图片", app.orig is not None and app.tkimg is not None))


def t_copy():
    app.copy_clip()
    u = ctypes.windll.user32
    u.OpenClipboard(None)
    ok = bool(u.IsClipboardFormatAvailable(8)) and bool(u.IsClipboardFormatAvailable(17))
    u.CloseClipboard()
    res.append(("复制到剪贴板(含透明通道)", ok))


def t_save():
    app.save_fixed()
    dst = os.path.join(SAVE, "func.png")
    res.append(("保存到本地(固定目录)", os.path.isfile(dst)))


def t_save_dup():
    app.save_fixed()
    res.append(("重名不覆盖", os.path.isfile(os.path.join(SAVE, "func_1.png"))))


def fin():
    root.destroy()


root.after(300, lambda: (t_open(), root.after(100, lambda: (
    t_copy(), root.after(100, lambda: (t_save(), root.after(100, lambda: (
        t_save_dup(), root.after(100, fin))))))))) 
root.mainloop()
for name, ok in res:
    print("  %s %s" % ("[PASS]" if ok else "[FAIL]", name))

# ---------- 3. 双击唤起 ----------
print()
print("=" * 68)
print(" [3] 双击图片自动唤起（走系统关联）")
print("=" * 68)
shlwapi = ctypes.windll.shlwapi
shlwapi.AssocQueryStringW.restype = ctypes.c_long
b = ctypes.create_unicode_buffer(2048); n = wintypes.DWORD(2048)
shlwapi.AssocQueryStringW(0, 2, ".png", "open", b, ctypes.byref(n))
cur = b.value
print("  .png 当前默认程序: %s" % (os.path.basename(cur) if cur else "(空)"))
print("  是否极速看图: %s" % ("是 ✔" if "FastImageViewer" in cur else "否（需手动设置）"))

for ext in ["webp", "tiff", "ico", "bmp"]:
    b = ctypes.create_unicode_buffer(2048); n = wintypes.DWORD(2048)
    shlwapi.AssocQueryStringW(0, 2, "." + ext, "open", b, ctypes.byref(n))
    v = b.value
    print("  .%-5s %s %s" % (ext, "✔" if "FastImageViewer" in v else "×",
                            os.path.basename(v) if v else "(空)"))

kill()
dbl = os.path.join(TMP, "dbl.webp")
Image.new("RGB", (900, 700), (90, 170, 60)).save(dbl)
t0 = time.perf_counter()
ctypes.windll.shell32.ShellExecuteW(None, "open", dbl, None, None, 1)
w = None
while time.perf_counter() - t0 < 15:
    w = find_window()
    if w:
        break
    time.sleep(0.02)
if w:
    print("  → 双击 .webp 唤起成功，耗时 %.0f ms" % ((time.perf_counter() - t0) * 1000))
else:
    print("  → 双击 .webp 未唤起（该格式可能需手动设默认）")
kill()

# ---------- 汇总 ----------
print()
print("=" * 68)
allpass = all(o for _, o in res) and bool(runs)
print(" 验收结果: %s" % ("全部通过 ✔" if allpass else "存在失败项"))
print("=" * 68)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if allpass else 1)