# -*- coding: utf-8 -*-
"""
精简回归验证：只测关键风险点，控制在 2 分钟内
每个用例用最小可行尺寸，避免测试本身成为瓶颈
"""
import os, sys, time, tempfile, shutil, traceback
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

TMP = tempfile.mkdtemp(prefix="fiv_v_")
OUT = os.path.join(TMP, "out"); os.makedirs(OUT, exist_ok=True)
R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print("  %s %-36s %s" % ("[PASS]" if cond else "[FAIL]", name, extra), flush=True)


def mk(n, f):
    p = os.path.join(TMP, n)
    try:
        f(p); return p
    except Exception as e:
        print("  [SKIP] %s: %s" % (n, e), flush=True); return None


print("=" * 70, flush=True)
print(" 精简回归验证", flush=True)
print("=" * 70, flush=True)

print("\n造图...", flush=True)
C = {}
# 尺寸极端（用小图，够测边界）
C["1x1"] = mk("a1.png", lambda p: Image.new("RGB", (1, 1), (255, 0, 0)).save(p))
C["1x5000窄"] = mk("a2.png", lambda p: Image.new("RGB", (1, 5000), (0, 255, 0)).save(p))
C["5000x1扁"] = mk("a3.png", lambda p: Image.new("RGB", (5000, 1), (0, 0, 255)).save(p))
C["2x2"] = mk("a4.bmp", lambda p: Image.new("RGB", (2, 2), (128, 128, 128)).save(p))
# 大尺寸（用 JPEG 让 draft 生效，测真实大图）
C["8K图"] = mk("a5.png", lambda p: Image.new("RGB", (7680, 4320), (60, 90, 140)).save(p))
C["1亿JPEG"] = mk("a6.jpg", lambda p: Image.new("RGB", (10000, 10000), (200, 90, 40)).save(p, quality=85))
# 大文件（100MB 级）
C["150MB_BMP"] = mk("a7.bmp", lambda p: Image.new("RGB", (7000, 7000), (100, 100, 100)).save(p))
# 各模式
C["透明RGBA"] = mk("a8.png", lambda p: Image.new("RGBA", (800, 600), (255, 0, 0, 128)).save(p))
C["灰度L"] = mk("a9.png", lambda p: Image.new("L", (800, 600), 128).save(p))
C["调色板P"] = mk("a10.png", lambda p: Image.new("P", (800, 600)).save(p))
C["二值1bit"] = mk("a11.png", lambda p: Image.new("1", (800, 600), 1).save(p))
C["CMYK"] = mk("a12.jpg", lambda p: Image.new("CMYK", (600, 400), (0, 100, 100, 0)).save(p))


def _anim(p):
    fr = [Image.new("RGB", (400, 300), c) for c in [(255,0,0),(0,255,0),(0,0,255),(255,255,0)]]
    fr[0].save(p, save_all=True, append_images=fr[1:], duration=80, loop=0)
C["GIF动图4帧"] = mk("a13.gif", _anim)
C["WebP"] = mk("a14.webp", lambda p: Image.new("RGB", (800, 600), (90, 200, 60)).save(p))
C["TIFF"] = mk("a15.tiff", lambda p: Image.new("RGB", (1000, 800), (70, 70, 70)).save(p, compression="tiff_lzw"))
C["ICO"] = mk("a16.ico", lambda p: Image.new("RGBA", (256, 256), (20, 20, 20, 255)).save(p, sizes=[(16,16),(64,64),(256,256)]))
C["中文名"] = mk("中文测试图.png", lambda p: Image.new("RGB", (600, 400), (200, 200, 100)).save(p))
C["空格名"] = mk("my photo.png", lambda p: Image.new("RGB", (600, 400), (100, 200, 200)).save(p))
# 损坏
C["空文件"] = mk("b1.png", lambda p: open(p, "wb").close())
C["文本改名png"] = mk("b2.png", lambda p: open(p, "wb").write(b"not an image" * 50))
C["截断PNG"] = mk("b3.png", lambda p: open(p, "wb").write(open(C["透明RGBA"], "rb").read()[:400]))
C["截断JPEG"] = mk("b4.jpg", lambda p: open(p, "wb").write(open(C["1亿JPEG"], "rb").read()[:3000]))
C["随机数据"] = mk("b5.bin", lambda p: open(p, "wb").write(bytes(range(256)) * 200))
print("  共 %d 个文件" % len([v for v in C.values() if v]), flush=True)

root = tk.Tk()
# 注意：必须传一个真实文件路径初始化，否则程序会按设计弹出"打开文件"对话框
# （手动启动时的正常行为），在自动化测试里会阻塞事件循环
_placeholder = C["2x2"]
app = m.ImageViewer(root, [_placeholder])
app.save_dir = OUT
root.update_idletasks(); root.update()

BAD = ("空文件", "文本改名png", "截断PNG", "截断JPEG", "随机数据")

print("\n[1] 打开：大小图 / 大小文件", flush=True)
slow = []
for k, p in C.items():
    if not p:
        continue
    sz = os.path.getsize(p) / 1048576.0
    t0 = time.time(); ok = False; err = None
    try:
        ok = app.open(p)
        root.update_idletasks(); root.update()
        if ok:
            app.render(); root.update_idletasks(); root.update()
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    dt = time.time() - t0
    if err:
        ck("打开 " + k, False, "崩溃: %s" % err)
    elif k in BAD:
        ck("安全处理 " + k, True, "%.2fs" % dt)
    else:
        ck("打开 " + k, ok, "%.1fMB %.2fs" % (sz, dt))
        if ok and dt > 3.0:
            slow.append((k, round(dt, 1)))
ck("无慢于3秒的图", not slow, str(slow) if slow else "全部 <3s")

print("\n[2] 三大功能", flush=True)
for k in ["1x1", "透明RGBA", "灰度L", "调色板P", "二值1bit", "CMYK",
          "8K图", "1亿JPEG", "150MB_BMP", "GIF动图4帧", "ICO"]:
    p = C.get(k)
    if not p:
        continue
    try:
        if not app.open(p):
            ck("功能 " + k, False, "无法打开")
            continue
        root.update_idletasks(); root.update()
        oc = os_ = True
        try:
            app.copy_clip()
        except Exception as e:
            oc = False
        try:
            b = len(os.listdir(OUT)); app.save_fixed()
            os_ = len(os.listdir(OUT)) > b
        except Exception:
            os_ = False
        ck("功能 " + k, oc and os_, "复制%s 保存%s" % ("OK" if oc else "X", "OK" if os_ else "X"))
    except Exception as e:
        ck("功能 " + k, False, str(e)[:50])

print("\n[3] 保真：大图显示可缩，输出必须全分辨率", flush=True)
p = C["1亿JPEG"]
if p:
    app.open(p); root.update_idletasks(); root.update()
    d = app.orig.size; full = app._full_image()
    ck("显示降采样", d[0] * d[1] < 10000 * 10000, "显示 %s" % (d,))
    ck("取全分辨率输出", full.size == (10000, 10000), "%s" % (full.size,))

print("\n[4] 连续切换 60 次（用轻量图，避免测试自身过慢）", flush=True)
light = [C[k] for k in ["1x1", "2x2", "透明RGBA", "灰度L", "调色板P", "二值1bit",
                        "GIF动图4帧", "WebP", "TIFF", "ICO", "中文名", "空格名"]
         if C.get(k)]
app.paths = light
crashed = None
t0 = time.time()
try:
    for i in range(60):
        app.open(light[i % len(light)])
        if i % 20 == 0:
            root.update_idletasks(); root.update()
except Exception:
    crashed = traceback.format_exc()
ck("60次切换不崩", crashed is None, "%.1fs" % (time.time() - t0))

print("\n[5] 极限缩放 0.02x~40x（用中等图，测边界不测性能）", flush=True)
p = C["8K图"]
if p:
    app.open(p); root.update_idletasks(); root.update()
    okz = True
    try:
        for _ in range(60):
            app.zoom_by(1.15)
        for _ in range(120):
            app.zoom_by(1 / 1.15)
        app.zoom_reset(); root.update_idletasks(); root.update()
    except Exception:
        okz = False
    ck("缩放不崩", okz)

try:
    root.destroy()
except Exception:
    pass

print("\n" + "=" * 70, flush=True)
ps = sum(1 for _, o in R if o)
print(" 结果: %d/%d 通过" % (ps, len(R)), flush=True)
print("=" * 70, flush=True)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ps == len(R) else 1)