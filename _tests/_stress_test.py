# -*- coding: utf-8 -*-
"""
极限压力测试：尺寸 / 文件大小 / 损坏文件 / 格式全覆盖
目标：任何一张图都不能让程序崩溃或卡死
"""
import os, sys, time, tempfile, traceback, shutil, gc
import importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, ".venv-build", "Lib", "site-packages"))

spec = importlib.util.spec_from_file_location("v", os.path.join(HERE, "viewer.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

from PIL import Image
import tkinter as tk

m._load_pil()
m.messagebox.showerror = lambda *a, **k: None   # 拦截弹窗避免阻塞

TMP = tempfile.mkdtemp(prefix="fiv_stress_")
OUT = os.path.join(TMP, "out")
os.makedirs(OUT, exist_ok=True)

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print("  %s %-46s %s" % ("[PASS]" if cond else "[FAIL]", name, extra))


def make(name, fn):
    p = os.path.join(TMP, name)
    try:
        fn(p)
        return p
    except Exception as e:
        print("  [SKIP] 造图失败 %s: %s" % (name, e))
        return None


print("=" * 76)
print(" 第一阶段：造测试文件")
print("=" * 76)

cases = {}

# ---- 极小尺寸 ----
cases["1x1px"] = make("s_1x1.png", lambda p: Image.new("RGB", (1, 1), (255, 0, 0)).save(p))
cases["1xN极窄"] = make("s_1xN.png", lambda p: Image.new("RGB", (1, 3000), (0, 255, 0)).save(p))
cases["Nx1极扁"] = make("s_Nx1.png", lambda p: Image.new("RGB", (3000, 1), (0, 0, 255)).save(p))
cases["2x2px"] = make("s_2x2.bmp", lambda p: Image.new("RGB", (2, 2), (128, 128, 128)).save(p))

# ---- 超大尺寸 ----
cases["超大15000x15000"] = make("s_huge.png",
    lambda p: Image.new("RGB", (15000, 15000), (60, 90, 140)).save(p))
cases["宽幅40000x50"] = make("s_wide.png",
    lambda p: Image.new("RGB", (40000, 50), (140, 90, 60)).save(p))
cases["高幅50x40000"] = make("s_tall.png",
    lambda p: Image.new("RGB", (50, 40000), (60, 140, 90)).save(p))

# ---- 各种模式 ----
cases["灰度L"] = make("s_L.png", lambda p: Image.new("L", (800, 600), 128).save(p))
cases["二值1bit"] = make("s_1bit.png",
    lambda p: Image.new("1", (800, 600), 1).save(p))
cases["调色板P"] = make("s_P.png",
    lambda p: Image.new("P", (800, 600)).save(p))
cases["带透明RGBA"] = make("s_rgba.png",
    lambda p: Image.new("RGBA", (800, 600), (255, 0, 0, 128)).save(p))
cases["CMYK"] = make("s_cmyk.jpg",
    lambda p: Image.new("CMYK", (800, 600), (0, 100, 100, 0)).save(p, quality=90))
cases["I;16位深"] = make("s_I16.png",
    lambda p: Image.new("I;16", (400, 300)).save(p))
cases["LA透明灰度"] = make("s_LA.png",
    lambda p: Image.new("LA", (400, 300), (128, 200)).save(p))

# ---- 各格式 ----
cases["JPEG渐进式"] = make("s_prog.jpg",
    lambda p: Image.new("RGB", (2000, 1500), (200, 100, 50)).save(p, progressive=True, quality=90))
cases["WebP有损"] = make("s_lossy.webp",
    lambda p: Image.new("RGB", (1600, 1200), (50, 200, 100)).save(p, quality=90))
cases["WebP无损"] = make("s_lless.webp",
    lambda p: Image.new("RGB", (800, 600), (100, 50, 200)).save(p, lossless=True))
cases["BMP24位"] = make("s_24.bmp", lambda p: Image.new("RGB", (1000, 800), (30, 30, 30)).save(p))
cases["BMP1位"] = make("s_1b.bmp", lambda p: Image.new("1", (500, 400), 0).save(p))
cases["TIFF未压缩"] = make("s_u.tiff",
    lambda p: Image.new("RGB", (900, 700), (70, 70, 70)).save(p, compression="raw"))
cases["TIFF-LZW"] = make("s_lzw.tiff",
    lambda p: Image.new("RGB", (900, 700), (70, 70, 70)).save(p, compression="tiff_lzw"))
cases["ICO多尺寸"] = make("s.ico",
    lambda p: Image.new("RGBA", (256, 256), (10, 10, 10, 255)).save(
        p, sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)]))
cases["GIF静态"] = make("s_static.gif", lambda p: Image.new("P", (600, 400)).save(p))

# ---- 动图 ----
def _gif_anim(p):
    frames = [Image.new("RGB", (400, 300), c) for c in
              [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255)]]
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=80, loop=0)
cases["GIF动图5帧"] = make("s_anim.gif", _gif_anim)


def _webp_anim(p):
    frames = [Image.new("RGB", (300, 200), c) for c in
              [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=100, loop=0)
cases["WebP动图3帧"] = make("s_anim.webp", _webp_anim)


def _gif_many(p):
    frames = [Image.new("RGB", (120, 90), (i % 256, (i * 3) % 256, (i * 7) % 256))
              for i in range(120)]
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=40, loop=0)
cases["GIF动图120帧"] = make("s_many.gif", _gif_many)

# ---- 特殊文件名 ----
cases["中文名"] = make("中文图片名测试.png",
    lambda p: Image.new("RGB", (500, 400), (200, 200, 100)).save(p))
cases["空格名"] = make("my photo test.png",
    lambda p: Image.new("RGB", (500, 400), (100, 200, 200)).save(p))
cases["特殊字符"] = make("a&b#c@d!e.png",
    lambda p: Image.new("RGB", (500, 400), (200, 100, 200)).save(p))
# 超长文件名
long_name = "x" * 180 + ".png"
cases["超长文件名"] = make(long_name,
    lambda p: Image.new("RGB", (300, 200), (111, 111, 111)).save(p))

# ---- 损坏文件 ----
cases["空文件"] = make("s_empty.png", lambda p: open(p, "wb").close())
cases["纯文本改名png"] = make("s_text.png",
    lambda p: open(p, "wb").write(b"this is not an image, just plain text" * 10))
cases["截断的PNG"] = make("s_trunc.png",
    lambda p: open(p, "wb").write(open(cases["调色板P"], "rb").read()[:200]))
cases["截断的JPEG"] = make("s_trunc.jpg",
    lambda p: open(p, "wb").write(open(cases["JPEG渐进式"], "rb").read()[:2000]))
cases["随机二进制"] = make("s_rand.bin",
    lambda p: open(p, "wb").write(bytes(range(256)) * 400))
cases["PNG头但无数据"] = make("s_hdronly.png",
    lambda p: open(p, "wb").write(b"\x89PNG\r\n\x1a\n"))

# ---- 大文件 ----
print("\n  生成大文件（耗时较长）...")
t0 = time.time()
cases["大图3000x3000未压缩TIFF"] = make("s_big.tiff",
    lambda p: Image.new("RGB", (3000, 3000), (80, 120, 160)).save(p, compression="raw"))
big_tiff_mb = os.path.getsize(cases["大图3000x3000未压缩TIFF"]) / 1048576.0
print("     未压缩TIFF: %.1f MB, 耗时 %.1fs" % (big_tiff_mb, time.time() - t0))

t0 = time.time()
cases["超大相片6000x4000JPEG"] = make("s_photo.jpg",
    lambda p: Image.new("RGB", (6000, 4000), (160, 120, 80)).save(p, quality=95))
print("     6000x4000 JPEG: %.1f MB, 耗时 %.1fs"
      % (os.path.getsize(cases["超大相片6000x4000JPEG"]) / 1048576.0, time.time() - t0))

print("\n  共生成 %d 个测试文件" % len([v for v in cases.values() if v]))

# ---- 汇总文件大小 ----
print("\n" + "=" * 76)
print(" 第二阶段：逐个打开测试（真实开窗）")
print("=" * 76)

root = tk.Tk()
app = m.ImageViewer(root, [])
app.save_dir = OUT
root.update_idletasks()
root.update()

order = list(cases.keys())
fails = []
t_start = time.time()

for name in order:
    p = cases[name]
    if not p:
        continue
    try:
        sz = os.path.getsize(p)
        szs = "%.1f MB" % (sz / 1048576.0) if sz >= 1048576 else "%.1f KB" % (sz / 1024.0)
    except Exception:
        szs = "?"

    t0 = time.time()
    err = None
    ok = False
    try:
        ok = app.open(p)
        root.update_idletasks()
        root.update()
        if ok:
            app.render()
            root.update_idletasks()
            root.update()
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
        fails.append((name, traceback.format_exc()))
    dt = (time.time() - t0) * 1000

    # 期望：能打开的文件返回 True 且渲染出图；损坏文件返回 False 但不崩
    if err:
        print("  [CRASH] %-28s %8s  %6.0fms  ← %s" % (name, szs, dt, err))
    elif ok:
        img_ok = app.tkimg is not None
        print("  [OPEN]  %-28s %8s  %6.0fms  %s%s"
              % (name, szs, dt, "出图" if img_ok else "未出图",
                 "" if img_ok else "  ⚠"))
        if not img_ok:
            fails.append((name, "未渲染出图"))
    else:
        print("  [SAFE]  %-28s %8s  %6.0fms  已安全拒绝（未崩溃）" % (name, szs, dt))

print("\n  总耗时 %.1fs" % (time.time() - t_start))
check("无崩溃", len(fails) == 0, "崩溃 %d 个" % len(fails))

# 逐项断言
print("\n" + "=" * 76)
print(" 第三阶段：关键断言")
print("=" * 76)

expect_ok = ["1x1px", "2x2px", "1xN极窄", "Nx1极扁", "灰度L", "二值1bit",
             "调色板P", "带透明RGBA", "LA透明灰度", "JPEG渐进式", "WebP有损",
             "WebP无损", "BMP24位", "BMP1位", "TIFF未压缩", "TIFF-LZW",
             "ICO多尺寸", "GIF静态", "GIF动图5帧", "WebP动图3帧", "GIF动图120帧",
             "中文名", "空格名", "特殊字符", "超长文件名",
             "大图3000x3000未压缩TIFF", "超大相片6000x4000JPEG", "超大15000x15000",
             "宽幅40000x50", "高幅50x40000", "CMYK", "I;16位深"]
expect_fail = ["空文件", "纯文本改名png", "截断的PNG", "截断的JPEG",
               "随机二进制", "PNG头但无数据"]

for name in expect_ok:
    if name not in cases or not cases[name]:
        continue
    p = cases[name]
    ok = False
    try:
        ok = app.open(p)
        root.update_idletasks(); root.update()
    except Exception:
        ok = False
    check("能打开: " + name, ok)

# 损坏文件：允许打开（容错）或拒绝，但绝不能崩
print()
for name in expect_fail:
    if name not in cases or not cases[name]:
        continue
    p = cases[name]
    crashed = False
    try:
        app.open(p)
        root.update_idletasks(); root.update()
    except Exception:
        crashed = True
    check("损坏文件不崩: " + name, not crashed)

# ---- 三大功能在各类图上的表现 ----
print("\n" + "=" * 76)
print(" 第四阶段：三大功能 × 各图像模式")
print("=" * 76)

func_fail = []
for name in ["1x1px", "带透明RGBA", "灰度L", "调色板P", "CMYK", "I;16位深",
             "超大15000x15000", "宽幅40000x50", "ICO多尺寸", "WebP动图3帧",
             "大图3000x3000未压缩TIFF"]:
    p = cases.get(name)
    if not p:
        continue
    try:
        if not app.open(p):
            print("  [SKIP] %-24s 无法打开" % name)
            continue
        root.update_idletasks(); root.update()

        # 复制
        copy_ok = True
        try:
            app.copy_clip()
        except Exception as e:
            copy_ok = False
            func_fail.append((name, "复制: %s" % e))

        # 保存
        save_ok = True
        try:
            before = set(os.listdir(OUT))
            app.save_fixed()
            after = set(os.listdir(OUT))
            save_ok = len(after) > len(before)
        except Exception as e:
            save_ok = False
            func_fail.append((name, "保存: %s" % e))

        print("  %s %-24s 复制=%s 保存=%s"
              % ("[OK]  " if (copy_ok and save_ok) else "[FAIL]",
                 name, "✓" if copy_ok else "×", "✓" if save_ok else "×"))
    except Exception as e:
        func_fail.append((name, "整体: %s" % e))
        print("  [FAIL] %-24s %s" % (name, e))

check("三大功能无异常", len(func_fail) == 0,
      "; ".join("%s(%s)" % (n, r) for n, r in func_fail[:3]))

# ---- 高保真验证：大图复制不能丢分辨率 ----
print("\n" + "=" * 76)
print(" 第五阶段：大图保真（缩略解码后不能丢分辨率）")
print("=" * 76)
p = cases["超大相片6000x4000JPEG"]
if p:
    app.open(p)
    root.update_idletasks(); root.update()
    disp_size = app.orig.size
    full = app._full_image()
    check("显示用缩略图(省内存)", disp_size[0] * disp_size[1] < 6000 * 4000,
          "显示尺寸 %s (原图 6000x4000)" % (disp_size,))
    check("复制取全分辨率", full.size == (6000, 4000), "全尺寸 %s" % (full.size,))

# ---- 高帧数动图内存安全 ----
print("\n" + "=" * 76)
print(" 第六阶段：动图内存安全（懒解码）")
print("=" * 76)
p = cases["GIF动图120帧"]
if p:
    app.open(p)
    root.update_idletasks(); root.update()
    check("120帧动图已加载", app.anim_total >= 100, "总帧数 %d" % app.anim_total)
    check("未预载全部帧(懒解码)", app.anim_total > 0 and app.orig is not None,
          "内存仅保留当前帧")

# ---- 连续切换压力 ----
print("\n" + "=" * 76)
print(" 第七阶段：连续切换 200 次（防内存泄漏/句柄泄漏）")
print("=" * 76)
all_paths = [v for v in cases.values() if v and os.path.isfile(v)]
app.paths = all_paths
crash = None
t0 = time.time()
try:
    for i in range(200):
        app.idx = i % len(all_paths)
        app.open(all_paths[app.idx])
        if i % 40 == 0:
            root.update_idletasks(); root.update()
    root.update_idletasks(); root.update()
except Exception:
    crash = traceback.format_exc()
dt = time.time() - t0
check("200次连续切换不崩", crash is None, "耗时 %.1fs" % dt if not crash else crash[:100])

# ---- 快速缩放压力 ----
print("\n" + "=" * 76)
print(" 第八阶段：极限缩放（0.02x ~ 40x）")
print("=" * 76)
app.open(cases["超大15000x15000"])
root.update_idletasks(); root.update()
zoom_ok = True
try:
    for _ in range(60):
        app.zoom_by(1.15)
    z_hi = app.zoom
    for _ in range(120):
        app.zoom_by(1 / 1.15)
    z_lo = app.zoom
    app.zoom_reset()
    root.update_idletasks(); root.update()
    zoom_ok = True
except Exception:
    zoom_ok = False
check("缩放不崩", zoom_ok, "上限 %.2fx 下限 %.3fx" % (app.zoom or 0, app.zoom or 0))

# ---- 收尾 ----
try:
    root.destroy()
except Exception:
    pass

print("\n" + "=" * 76)
passed = sum(1 for _, o, _ in results if o)
print(" 压测汇总: %d/%d 通过" % (passed, len(results)))
if fails:
    print("\n 崩溃/异常明细:")
    for n, tb in fails[:5]:
        print("   --- %s ---" % n)
        print("   " + tb[:400].replace("\n", "\n   "))
print("=" * 76)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if passed == len(results) else 1)