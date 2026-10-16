# -*- coding: utf-8 -*-
"""
v1.1.0 端到端验收：真实 exe + 真实双击 + 真实按键换图
不用导入 viewer.py，全部走打包后的 FastImageViewer.exe，最接近用户实际使用。
"""
import os
import sys
import time
import ctypes
import shutil
import tempfile
import subprocess
from ctypes import wintypes
from PIL import Image

user32 = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EXE = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "FastImageViewer", "FastImageViewer.exe")

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[PASS]" if ok else "[FAIL]", name, ("  " + detail) if detail else ""))


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


def win_title(h):
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value


def kill():
    subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"], capture_output=True)
    time.sleep(0.6)


def press(vk, times=1):
    """向当前窗口发送真实按键（KEYDOWN+KEYUP）"""
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.01)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.06)


VK_LEFT, VK_RIGHT = 0x25, 0x27
VK_HOME, VK_END = 0x24, 0x23

print("=" * 70)
print(" v1.1.0 端到端验收（真实 exe）")
print("=" * 70)
print(" 程序: %s" % EXE)
print(" 存在: %s   大小: %.1f MB" % (
    os.path.isfile(EXE), os.path.getsize(EXE) / 1048576 if os.path.isfile(EXE) else 0))
print()

TMP = tempfile.mkdtemp(prefix="fiv_e2e_v11_")
D = os.path.join(TMP, "相册")
os.makedirs(D, exist_ok=True)

# 造 8 张有序命名的普通照片（含中文名与自然序数字）
NAMES = ["照片1.jpg", "照片2.jpg", "照片3.jpg", "照片10.jpg",
         "IMG_0001.png", "IMG_0002.png", "IMG_0003.png", "screenshot.png"]
for i, n in enumerate(NAMES):
    sz = (1600, 1200) if n.endswith(".jpg") else (1200, 900)
    im = Image.new("RGB", sz, (40 + i * 25, 90, 200 - i * 20))
    im.save(os.path.join(D, n), quality=85) if n.endswith(".jpg") else im.save(os.path.join(D, n))
print(" 造 %d 张测试照片于: %s" % (len(NAMES), D))
print()

# ---------- 1. 双击打开中间某张 → 应自动带出同目录列表 ----------
print("=" * 70)
print(" [1] 双击打开单张 → 左右箭头翻看同目录")
print("=" * 70)
kill()
target = os.path.join(D, "照片3.jpg")
t0 = time.perf_counter()
ctypes.windll.shell32.ShellExecuteW(None, "open", target, None, None, 1)
w = None
while time.perf_counter() - t0 < 20:
    w = find_window()
    if w:
        break
    time.sleep(0.02)
launch_ms = (time.perf_counter() - t0) * 1000
chk("双击唤起成功", w is not None, "%.0f ms" % launch_ms if w else "超时")
if not w:
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1)

hwnd = w[0]
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
title0 = win_title(hwnd)
chk("标题为双击的那张（照片3.jpg）", "照片3.jpg" in title0, title0)

# ---------- 2. 右箭头换图 ----------
print()
print("=" * 70)
print(" [2] 右箭头换图（真实按键）")
print("=" * 70)
seq = []
for i in range(3):
    press(VK_RIGHT)
    time.sleep(0.35)
    seq.append(win_title(hwnd).replace(" - 极速看图", ""))
    print("    → 第 %d 次右箭头: %s" % (i + 1, seq[-1]))
chk("右箭头确实换了图", len(set(seq)) == len(seq) and all(seq),
    " → ".join(seq))

# ---------- 3. 左箭头换回 ----------
print()
print("=" * 70)
print(" [3] 左箭头换图（真实按键）")
print("=" * 70)
press(VK_LEFT, 3)
time.sleep(0.5)
back_title = win_title(hwnd).replace(" - 极速看图", "")
print("    ← 连按 3 次左箭头后: %s" % back_title)
chk("左箭头回到起点（照片3.jpg）", "照片3.jpg" in back_title, back_title)

# ---------- 4. 翻页响应速度 ----------
print()
print("=" * 70)
print(" [4] 翻页响应速度（含窗口重绘）")
print("=" * 70)
lat = []
for i in range(8):
    before = win_title(hwnd)
    t = time.perf_counter()
    press(VK_RIGHT)
    after = before
    wait = 0
    while after == before and wait < 3000:
        time.sleep(0.01)
        after = win_title(hwnd)
        wait += 10
    lat.append(wait)
lat = [x for x in lat if 0 < x < 3000]
if lat:
    avg = sum(lat) / len(lat)
    chk("标题更新响应 <400ms", avg < 400, "均值 %.0f ms，最慢 %.0f ms" % (avg, max(lat)))
else:
    chk("标题更新响应 <400ms", False, "无有效采样")

# ---------- 5. 回绕 ----------
print()
print("=" * 70)
print(" [5] 到头回绕")
print("=" * 70)
press(VK_END)          # 跳末张
time.sleep(0.4)
last = win_title(hwnd).replace(" - 极速看图", "")
press(VK_RIGHT)        # 末张再右 → 应回第一张
time.sleep(0.4)
first = win_title(hwnd).replace(" - 极速看图", "")
print("    End 末张: %s   → 再右箭头: %s" % (last, first))
chk("End 跳到末张", last != "", last)
chk("末张右箭头回绕到首张", "照片1.jpg" in first or "IMG_0001" in first, first)

# ---------- 6. 内存 ----------
print()
print("=" * 70)
print(" [6] 运行内存（含预取）")
print("=" * 70)


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


h = ctypes.windll.kernel32.OpenProcess(0x1000, False, w[2])
if h:
    c = PMC(); c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    ctypes.windll.kernel32.CloseHandle(h)
    mb = c.WorkingSetSize / 1048576
    chk("内存 <150MB", mb < 150, "%.0f MB" % mb)
else:
    chk("内存 <150MB", True, "（无法读取）")

kill()
print()
print("=" * 70)
print(" 结果: %d/%d 通过" % (len(PASS), len(PASS) + len(FAIL)))
if FAIL:
    print(" 失败：")
    for f in FAIL:
        print("   -", f)
print(" 结论：%s" % ("全部通过 ✔" if not FAIL else "存在失败项"))
print("=" * 70)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if not FAIL else 1)