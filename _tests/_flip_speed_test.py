# -*- coding: utf-8 -*-
"""
翻页体感实测：模拟普通电脑翻看日常照片（本次反馈聚焦场景）
用真实手机/单反尺寸照片，测：
  1. 预取命中率
  2. 连按箭头的平均 / 最慢响应
  3. 长按（快速连按 20 次）是否卡顿
  4. 预取是否占用 UI 线程（按键是否立即返回）
"""
import os
import sys
import time
import shutil
import tempfile
import importlib.util
import tkinter as tk
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("v", os.path.join(HERE, "viewer.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.messagebox.showerror = lambda *a, **k: None

TMP = tempfile.mkdtemp(prefix="fiv_speed_")
D = os.path.join(TMP, "photos")
os.makedirs(D, exist_ok=True)

# 造日常照片：手机 1200 万像素 + 单反 2400 万像素 + 常见截图/网图尺寸
SPECS = [
    ("IMG_0001.jpg", (4032, 3024)),   # 手机 1200 万
    ("IMG_0002.jpg", (4032, 3024)),
    ("IMG_0003.jpg", (4032, 3024)),
    ("IMG_0004.jpg", (4032, 3024)),
    ("IMG_0005.jpg", (4032, 3024)),
    ("DSC_0010.jpg", (6000, 4000)),   # 单反 2400 万
    ("DSC_0011.jpg", (6000, 4000)),
    ("DSC_0012.jpg", (6000, 4000)),
    ("screenshot.png", (1920, 1080)),  # 截图
    ("web_save.png", (1280, 720)),     # 网图
    ("small_avatar.png", (256, 256)),  # 头像
]
print("造 %d 张日常照片（手机/单反/截图尺寸）..." % len(SPECS))
for name, size in SPECS:
    p = os.path.join(D, name)
    im = Image.new("RGB", size, (80, 120, 160))
    # 加点噪声，避免 JPEG 压得太小导致测试失真
    px = im.load()
    for y in range(0, size[1], 37):
        for x in range(0, size[0], 37):
            px[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256)
    if name.lower().endswith(".jpg"):
        im.save(p, quality=88)
    else:
        im.save(p)
    print("  %-18s %-12s %6.2f MB" % (name, "%dx%d" % size, os.path.getsize(p) / 1048576))

root = tk.Tk()
root.geometry("1200x800")
first = os.path.join(D, "IMG_0001.jpg")
app = m.ImageViewer(root, [first])
root.update()

res = {}


def run():
    # ---- 1. 预取机制有效性 ----
    print("\n[1] 预取：切图后是否提前备好邻居")
    app.open(first)
    root.update()
    # 等待后台预取完成（最多 3 秒）
    t0 = time.time()
    while time.time() - t0 < 3.0:
        root.update()
        if len(app._prefetch) >= 1:
            break
        time.sleep(0.03)
    res["预取生效"] = (len(app._prefetch) >= 1, "缓存 %d 张，用时 %.0f ms"
                       % (len(app._prefetch), (time.time() - t0) * 1000))

    # ---- 2. 连按箭头响应 ----
    print("\n[2] 连续翻页 20 次（模拟快速浏览相册）")
    times = []
    for i in range(20):
        t = time.perf_counter()
        app.step(1)
        dt = (time.perf_counter() - t) * 1000
        times.append(dt)
        root.update()
    times.sort()
    avg = sum(times) / len(times)
    res["翻页均值 <50ms"] = (avg < 50, "均值 %.1f ms" % avg)
    res["翻页最慢 <200ms"] = (times[-1] < 200, "最慢 %.1f ms" % times[-1])
    res["翻页 P90 <120ms"] = (times[int(len(times) * 0.9)] < 120,
                             "P90 %.1f ms" % times[int(len(times) * 0.9)])
    print("  明细前 8 次: %s" % " ".join("%.0f" % x for x in times[:8]))
    print("  均值 %.1f ms | P90 %.1f ms | 最慢 %.1f ms" % (avg, times[int(len(times)*0.9)], times[-1]))

    # ---- 3. 回退翻页 ----
    print("\n[3] 反向翻页 20 次")
    t2 = []
    for i in range(20):
        t = time.perf_counter()
        app.step(-1)
        t2.append((time.perf_counter() - t) * 1000)
        root.update()
    avg2 = sum(t2) / len(t2)
    res["反向翻页均值 <50ms"] = (avg2 < 50, "均值 %.1f ms" % avg2)
    print("  反向均值 %.1f ms | 最慢 %.1f ms" % (avg2, max(t2)))

    # ---- 4. 内存占用（预取后） ----
    print("\n[4] 预取后内存")
    try:
        import ctypes
        from ctypes import wintypes

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
        pid = os.getpid()
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        c = PMC(); c.cb = ctypes.sizeof(c)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        ctypes.windll.kernel32.CloseHandle(h)
        mb = c.WorkingSetSize / 1048576
        res["内存合理(<250MB含预取)"] = (mb < 250, "%.0f MB" % mb)
        print("  当前进程内存 %.0f MB（含 2 张预取图）" % mb)
    except Exception as e:
        print("  内存读取失败:", e)

    root.after(50, root.destroy)


root.after(300, run)
root.mainloop()

print("\n" + "=" * 70)
ok_all = all(v[0] for v in res.values())
for k, (ok, detail) in res.items():
    print("  %s %s   %s" % ("[PASS]" if ok else "[FAIL]", k, detail))
print("  结论：%s" % ("全部达标 ✔" if ok_all else "存在不达标项"))
print("=" * 70)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok_all else 1)