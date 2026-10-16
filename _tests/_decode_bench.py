# -*- coding: utf-8 -*-
"""对比超大图的多种解码策略，找出最快路径"""
import os, sys, time, tempfile, shutil, ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, ".venv-build", "Lib", "site-packages"))

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


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


def mem_mb():
    h = ctypes.windll.kernel32.GetCurrentProcess()
    c = PMC(); c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    return c.WorkingSetSize / 1048576.0


TMP = tempfile.mkdtemp(prefix="fiv_dec_")
print("=" * 78)
print(" 超大图解码策略对比")
print("=" * 78)
print(" 基线内存: %.0f MB" % mem_mb())

# 用 10000x10000 做对比（1 亿像素，够代表性且不至于等太久）
SIZE = 10000
target = (900, 640)  # 窗口显示尺寸

print("\n 生成 %dx%d PNG ..." % (SIZE, SIZE))
p_png = os.path.join(TMP, "t.png")
t0 = time.time()
Image.new("RGB", (SIZE, SIZE), (60, 90, 140)).save(p_png)
print(" 完成 %.1fs, 文件 %.1f MB" % (time.time() - t0,
                                    os.path.getsize(p_png) / 1048576.0))

p_jpg = os.path.join(TMP, "t.jpg")
t0 = time.time()
Image.new("RGB", (SIZE, SIZE), (160, 120, 80)).save(p_jpg, quality=90)
print(" 完成 %.1fs, 文件 %.1f MB" % (time.time() - t0,
                                    os.path.getsize(p_jpg) / 1048576.0))


def bench(label, path, strategy):
    before = mem_mb()
    t0 = time.time()
    try:
        img = strategy(path)
        ok = img is not None
    except Exception as e:
        print("  [ERR] %-40s %s" % (label, e))
        return None
    dt = time.time() - t0
    after = mem_mb()
    print("  %-40s %7.2fs  内存 %5.0f→%5.0f MB  尺寸=%s"
          % (label, dt, before, after, img.size if ok else "-"))
    return dt


print("\n--- PNG %dx%d ---" % (SIZE, SIZE))


def s1(path):
    """当前实现：全解码 -> LANCZOS 缩放"""
    im = Image.open(path); im.load()
    s = min(target[0] / im.size[0], target[1] / im.size[1], 1.0)
    return im.resize((int(im.size[0] * s), int(im.size[1] * s)), Image.LANCZOS)


def s2(path):
    """全解码 -> BILINEAR 缩放（大图换快算法）"""
    im = Image.open(path); im.load()
    s = min(target[0] / im.size[0], target[1] / im.size[1], 1.0)
    return im.resize((int(im.size[0] * s), int(im.size[1] * s)), Image.BILINEAR)


def s3(path):
    """reduce() 快速降采样（PIL 内置，解码层优化）"""
    im = Image.open(path)
    # 计算需要降几分之一
    f = max(1, min(im.size[0] // target[0], im.size[1] // target[1]))
    if f > 1:
        im = im.reduce(f)
    im.load()
    s = min(target[0] / im.size[0], target[1] / im.size[1], 1.0)
    if s < 1.0:
        im = im.resize((int(im.size[0] * s), int(im.size[1] * s)), Image.BILINEAR)
    return im


def s4(path):
    """draft（仅 JPEG 有效，PNG 应无效）"""
    im = Image.open(path)
    im.draft("RGB", (target[0] * 2, target[1] * 2))
    im.load()
    return im


def s5(path):
    """reduce 到接近目标后直接返回，不再二次缩放"""
    im = Image.open(path)
    f = max(1, min(round(im.size[0] / target[0]), round(im.size[1] / target[1])))
    if f > 1:
        im = im.reduce(f)
    im.load()
    return im


r = {}
for label, fn in [("① 当前: 全解码+LANCZOS", s1),
                  ("② 全解码+BILINEAR", s2),
                  ("③ reduce() + BILINEAR", s3),
                  ("④ draft() (PNG已知无效)", s4),
                  ("⑤ reduce() 单次", s5)]:
    r[label] = bench(label, p_png, fn)

print("\n--- JPEG %dx%d ---" % (SIZE, SIZE))
for label, fn in [("① 全解码+LANCZOS", s1),
                  ("② 全解码+BILINEAR", s2),
                  ("③ reduce() + BILINEAR", s3),
                  ("④ draft()", s4),
                  ("⑤ reduce() 单次", s5)]:
    bench(label, p_jpg, fn)

print("\n" + "=" * 78)
print(" 结论")
print("=" * 78)
if r:
    best = min((v, k) for k, v in r.items() if v is not None)
    worst = max((v, k) for k, v in r.items() if v is not None)
    print("  PNG 最快: %.2fs  %s" % (best[0], best[1]))
    print("  PNG 最慢: %.2fs  %s" % (worst[0], worst[1]))
    print("  提速: %.1f 倍" % (worst[0] / best[0] if best[0] > 0 else 0))

shutil.rmtree(TMP, ignore_errors=True)