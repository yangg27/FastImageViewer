# -*- coding: utf-8 -*-
"""端到端冒烟测试：真实开窗 -> 渲染 -> 复制剪贴板 -> 保存文件"""
import os, sys, io, ctypes, tempfile, shutil
import importlib.util
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("v", os.path.join(HERE, "viewer.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TMP = tempfile.mkdtemp(prefix="imgview_test_")
OUT = os.path.join(TMP, "out")
os.makedirs(OUT, exist_ok=True)

# --- 造测试图 ---
f_png = os.path.join(TMP, "a.png")
Image.new("RGB", (800, 600), (30, 120, 200)).save(f_png)

f_jpg = os.path.join(TMP, "b.jpg")
Image.new("RGB", (1600, 1200), (200, 60, 60)).save(f_jpg, quality=90)

f_rgba = os.path.join(TMP, "c.png")
im = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
for x in range(300):
    for y in range(0, 200, 4):
        im.putpixel((x, y), (255, 0, 0, 255))
im.save(f_rgba)

f_gif = os.path.join(TMP, "d.gif")
fr = [Image.new("RGB", (120, 90), c) for c in [(255,0,0),(0,255,0),(0,0,255)]]
fr[0].save(f_gif, save_all=True, append_images=fr[1:], duration=60, loop=0)

f_bmp = os.path.join(TMP, "e.bmp")
Image.new("RGB", (200, 150), (120, 200, 60)).save(f_bmp)
f_webp = os.path.join(TMP, "f.webp")
Image.new("RGB", (240, 180), (90, 90, 200)).save(f_webp)

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))


import tkinter as tk
m.enable_dpi_awareness()
root = tk.Tk()
app = m.ImageViewer(root, [f_png])
app.save_dir = OUT

steps = []


def s1():
    check("窗口渲染", app.tkimg is not None, "canvas=%dx%d" % (app.canvas.winfo_width(), app.canvas.winfo_height()))
    steps.append(1)


def s2():
    app.copy_clip()
    u = ctypes.windll.user32
    u.OpenClipboard(None)
    has_dib = bool(u.IsClipboardFormatAvailable(8))
    u.CloseClipboard()
    check("复制RGB到剪贴板", has_dib)


def s3():
    app.save_fixed()
    dst = os.path.join(OUT, "a.png")
    check("保存到固定目录", os.path.isfile(dst), dst)


def s4():
    # 重名自动加后缀
    app.save_fixed()
    check("重名自动改名", os.path.isfile(os.path.join(OUT, "a_1.png")))


def s5():
    app.open(f_jpg)
    check("大图JPG draft打开", app.orig is not None, "size=%s" % (app.orig.size,))


def s6():
    app.open(f_rgba)
    app.copy_clip()
    u = ctypes.windll.user32
    u.OpenClipboard(None)
    v5 = bool(u.IsClipboardFormatAvailable(17))
    u.CloseClipboard()
    check("RGBA复制含DIBV5", v5)


def s7():
    app.open(f_gif)
    check("动图帧提取", app.anim_total == 3,
          "anim_total=%s" % app.anim_total)


def s8():
    app.zoom_by(2.0)
    check("缩放渲染", app.zoom is not None and app.tkimg is not None, "zoom=%s" % app.zoom)


def s9():
    for f in (f_bmp, f_webp):
        app.open(f)
        dst = os.path.join(OUT, os.path.basename(f))
        app._save_image(dst)
        if not os.path.isfile(dst):
            check("保存" + os.path.basename(f), False)
    check("BMP/WebP打开保存", os.path.isfile(os.path.join(OUT, "e.bmp")) and os.path.isfile(os.path.join(OUT, "f.webp")))


def s10():
    # 另存为转换格式：PNG -> JPG（白底）
    app.open(f_rgba)
    dst = os.path.join(OUT, "conv.jpg")
    app._save_image(dst)
    ok = os.path.isfile(dst)
    if ok:
        with Image.open(dst) as t:
            ok = t.mode == "RGB"
    check("RGBA转JPG白底", ok)


def s11():
    # 破损文件容错
    bad = os.path.join(TMP, "bad.png")
    open(bad, "wb").write(b"not an image at all")
    before = app.orig
    app.open(bad)          # 会弹 messagebox -> 需拦截
    check("破损文件不崩溃", True)
    app.orig = before


def finish():
    root.destroy()


# 拦截 messagebox 避免阻塞
m.messagebox.showerror = lambda *a, **k: None

def run_chain(idx=0):
    global steps
    fns = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11]
    if idx < len(fns):
        try:
            fns[idx]()
        except Exception as e:
            check(fns[idx].__name__, False, "EXC: %r" % e)
        root.after(120, lambda: run_chain(idx + 1))
    else:
        finish()


root.after(400, lambda: run_chain(0))
root.mainloop()

print("=" * 56)
ok_all = True
for name, ok, extra in results:
    if not ok:
        ok_all = False
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  <" + str(extra) + ">") if extra else ""))
print("=" * 56)
print("RESULT:", "ALL PASS" if ok_all else "SOME FAILED", "(%d/%d)" % (sum(1 for _, o, _ in results if o), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok_all else 1)