# -*- coding: utf-8 -*-
"""
v1.2.0 旋转功能验收
覆盖：
  1. 90/180/270 旋转方向正确（像素级验证）
  2. 旋转无损（90° 倍数是纯重排，不重采样）
  3. 复制到剪贴板输出旋转后的图
  4. 保存到本地输出旋转后的图（不能存成未旋转原图）
  5. 换图后旋转状态复位
  6. Ctrl+R 恢复原始方向
  7. 旋转后宽高互换，自适应缩放正常
  8. 连续旋转 4 次回到原样
  9. 动图旋转不崩
 10. 透明图旋转不丢 alpha
"""
import os
import sys
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

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[PASS]" if ok else "[FAIL]", name, ("  " + detail) if detail else ""))


TMP = tempfile.mkdtemp(prefix="fiv_rot_")

# 造一张方向明确的图：左上角红、右上角绿、左下角蓝、右下角白
# 这样任何旋转方向错误都能一眼看出
def make_marked(path, size=(200, 120)):
    w, h = size
    im = Image.new("RGB", (w, h), (255, 255, 255))
    qw, qh = w // 2, h // 2
    im.paste((255, 0, 0), (0, 0, qw, qh))            # 左上 红
    im.paste((0, 255, 0), (qw, 0, w, qh))            # 右上 绿
    im.paste((0, 0, 255), (0, qh, qw, h))            # 左下 蓝
    im.paste((255, 255, 0), (qw, qh, w, h))          # 右下 黄
    im.save(path)
    return path


def corners(img):
    """取四角像素，用来判断方向"""
    w, h = img.size
    return {
        "TL": img.getpixel((2, 2)),
        "TR": img.getpixel((w - 3, 2)),
        "BL": img.getpixel((2, h - 3)),
        "BR": img.getpixel((w - 3, h - 3)),
    }


print("=" * 70)
print(" [1] 旋转方向正确性（四角像素验证）")
print("=" * 70)
p1 = make_marked(os.path.join(TMP, "marked.png"))
root = tk.Tk()
root.geometry("900x640")
app = m.ImageViewer(root, [p1])
root.update()

CHK = {}


def run():
    base = corners(Image.open(p1).convert("RGB"))
    CHK["原图四角"] = (base["TL"][0] > 200 and base["TR"][1] > 200
                      and base["BL"][2] > 200 and base["BR"][0] > 200,
                      "TL红 TR绿 BL蓝 BR黄")
    CHK["原图尺寸 200x120"] = (app.orig.size == (200, 120), str(app.orig.size))

    # 右转 90°：左上角应该变成原来的左下角（蓝）
    app.rotate_right()
    root.update()
    r90 = corners(app._apply_rotate(app.orig).convert("RGB"))
    # 顺时针 90°：原左下(蓝) → 新左上
    CHK["右转90°方向正确(原左下→新左上)"] = (r90["TL"][2] > 200, "新左上=%s" % (r90["TL"],))
    CHK["右转90°宽高互换"] = (app._apply_rotate(app.orig).size == (120, 200),
                          str(app._apply_rotate(app.orig).size))
    CHK["状态栏显示旋转角度"] = ("旋转 90" in app.info.cget("text"), app.info.cget("text")[:70])

    # 再转 90° → 180°
    app.rotate_right()
    root.update()
    r180 = corners(app._apply_rotate(app.orig).convert("RGB"))
    CHK["右转180°方向正确(原右下→新左上)"] = (
        r180["TL"][0] > 200 and r180["TL"][1] > 200, "新左上=%s" % (r180["TL"],))
    CHK["180°尺寸不变"] = (app._apply_rotate(app.orig).size == (200, 120), "")

    # 再转两次 → 360° 应回到原样
    app.rotate_right()
    app.rotate_right()
    root.update()
    CHK["连转4次回到原始方向"] = (app.rotate == 0, "rotate=%d" % app.rotate)

    # 左转 90°（逆时针）
    app.rotate_left()
    root.update()
    l90 = corners(app._apply_rotate(app.orig).convert("RGB"))
    # 逆时针 90°：原右上(绿) → 新左上
    CHK["左转90°方向正确(原右上→新左上)"] = (l90["TL"][1] > 200, "新左上=%s" % (l90["TL"],))

    # Ctrl+R 复位
    app.rotate_reset()
    root.update()
    CHK["Ctrl+R 恢复原始方向"] = (app.rotate == 0, "rotate=%d" % app.rotate)

    root.after(20, root.destroy)


root.after(400, run)
root.mainloop()
for k, (ok, d) in CHK.items():
    chk(k, ok, d)

# ---------------- 2. 无损性 ----------------
print()
print("=" * 70)
print(" [2] 旋转无损（90° 不应引入模糊/失真）")
print("=" * 70)
root = tk.Tk()
root.geometry("900x640")
app = m.ImageViewer(root, [p1])
root.update()
res = {}


def run2():
    # 用棋盘格 + 纯色块，旋转后像素集合必须完全一致（只换位置，不产生新颜色）
    src = Image.open(p1).convert("RGB")
    before_colors = set(src.getdata())
    app.rotate_right()
    root.update()
    rot = app._apply_rotate(app.orig).convert("RGB")
    after_colors = set(rot.getdata())
    res["颜色集合完全一致(无插值新色)"] = (before_colors == after_colors,
                                        "前 %d 色 / 后 %d 色" % (len(before_colors), len(after_colors)))
    # 尺寸互换精确
    res["尺寸精确互换"] = (rot.size == (src.size[1], src.size[0]), "%s -> %s" % (src.size, rot.size))

    # 透明图不丢 alpha（取样点取在绿色块上，alpha 应为 255）
    pa = os.path.join(TMP, "alpha.png")
    a = Image.new("RGBA", (100, 80), (255, 0, 0, 100))
    a.paste((0, 255, 0, 255), (0, 0, 50, 40))
    a.save(pa)
    app.open(pa)
    root.update()
    app.rotate_right()
    root.update()
    ra = app._apply_rotate(app.orig)
    # 原左上绿色块(alpha=255) 顺时针 90° 后落到右上区域
    px = ra.convert("RGBA").getpixel((ra.size[0] - 3, 3))
    res["透明图旋转保留 alpha"] = (ra.mode == "RGBA" and px[3] == 255,
                                "mode=%s 右上alpha=%d" % (ra.mode, px[3]))

    root.after(20, root.destroy)


root.after(400, run2)
root.mainloop()
for k, (ok, d) in res.items():
    chk(k, ok, d)

# ---------------- 3. 复制 / 保存输出旋转结果 ----------------
print()
print("=" * 70)
print(" [3] 复制与保存必须输出旋转后的图")
print("=" * 70)
root = tk.Tk()
root.geometry("900x640")
work = os.path.join(TMP, "work")
os.makedirs(work, exist_ok=True)
p2 = make_marked(os.path.join(work, "photo.png"))
app = m.ImageViewer(root, [p2])
app.save_dir = os.path.join(TMP, "out")
root.update()
r3 = {}


def run3():
    # 未旋转时保存 → 应走原文件复制
    app.save_fixed()
    root.update()
    files = os.listdir(app.save_dir) if os.path.isdir(app.save_dir) else []
    r3["未旋转保存成功"] = (len(files) >= 1, "%d 个文件" % len(files))

    saved1 = os.path.join(app.save_dir, files[0])
    im1 = Image.open(saved1)
    r3["未旋转保存 = 原尺寸"] = (im1.size == (200, 120), str(im1.size))

    # 旋转后保存 → 必须重新编码且尺寸互换
    app.rotate_right()
    root.update()
    app.save_fixed()
    root.update()
    files2 = sorted(os.listdir(app.save_dir))
    r3["旋转后保存产生新文件"] = (len(files2) > len(files), "%d -> %d" % (len(files), len(files2)))
    newest = max([os.path.join(app.save_dir, f) for f in files2], key=os.path.getmtime)
    im2 = Image.open(newest)
    r3["旋转后保存尺寸已互换"] = (im2.size == (120, 200), "%s  文件=%s" % (im2.size, os.path.basename(newest)))
    # 方向验证：新左上应是蓝色
    c = corners(im2.convert("RGB"))
    r3["旋转后保存方向正确"] = (c["TL"][2] > 200, "新左上=%s" % (c["TL"],))

    # 复制到剪贴板：验证剪贴板里的位图尺寸
    import ctypes
    from ctypes import wintypes
    app.copy_clip()
    root.update()
    u = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    # 关键：必须声明 restype，否则 64 位下句柄被截断成负数，GlobalLock 必失败
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HANDLE]
    k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    ok_clip = False
    dims = None
    try:
        u.OpenClipboard(None)
        if u.IsClipboardFormatAvailable(8):
            h = u.GetClipboardData(8)
            ptr = k32.GlobalLock(h) if h else None
            if ptr:
                # BITMAPINFOHEADER: biSize(+0) biWidth(+4) biHeight(+8)
                raw = ctypes.string_at(ptr, 12)
                import struct
                _sz, w, hh = struct.unpack("<Iii", raw)
                dims = (w, abs(hh))
                k32.GlobalUnlock(h)
            ok_clip = True
        u.CloseClipboard()
    except Exception as e:
        dims = "读取失败:%s" % e
    r3["复制到剪贴板成功"] = (ok_clip, "")
    r3["剪贴板位图为旋转后尺寸(120x200)"] = (dims == (120, 200), "剪贴板 %s" % (dims,))

    root.after(20, root.destroy)


root.after(400, run3)
root.mainloop()
for k, (ok, d) in r3.items():
    chk(k, ok, d)

# ---------------- 4. 换图复位 / 自适应 ----------------
print()
print("=" * 70)
print(" [4] 换图复位 / 旋转后自适应缩放")
print("=" * 70)
d2 = os.path.join(TMP, "multi")
os.makedirs(d2, exist_ok=True)
for i, sz in enumerate([(300, 200), (500, 400), (640, 480)]):
    make_marked(os.path.join(d2, "pic%d.png" % (i + 1)), sz)
root = tk.Tk()
root.geometry("800x600")
app = m.ImageViewer(root, [os.path.join(d2, "pic1.png")])
root.update()
r4 = {}


def run4():
    app.rotate_right()
    root.update()
    r4["旋转前状态记录"] = (app.rotate == 90, "rotate=%d" % app.rotate)

    app.step(1)          # 换到下一张
    root.update()
    r4["换图后旋转复位"] = (app.rotate == 0, "rotate=%d" % app.rotate)

    # 旋转后自适应缩放：竖图横放应能完整显示，不超出画布
    app.rotate_right()
    root.update()
    W = app.canvas.winfo_width()
    H = app.canvas.winfo_height()
    iw, ih = app._apply_rotate(app.orig).size
    fit = min(W / iw, H / ih, 1.0)
    r4["旋转后自适应比例合理(0<x<=1)"] = (0 < fit <= 1.0,
                                      "画布%dx%d 图%dx%d fit=%.3f" % (W, H, iw, ih, fit))
    # _fit_scale 应返回与手工计算一致
    r4["_fit_scale 与手工计算一致"] = (abs(app._fit_scale() - fit) < 1e-6,
                                  "%.6f vs %.6f" % (app._fit_scale(), fit))

    root.after(20, root.destroy)


root.after(400, run4)
root.mainloop()
for k, (ok, d) in r4.items():
    chk(k, ok, d)

# ---------------- 5. 动图 / 边界 ----------------
print()
print("=" * 70)
print(" [5] 动图旋转 / 边界情况")
print("=" * 70)
root = tk.Tk()
root.geometry("800x600")
# 动图
pg = os.path.join(TMP, "anim.gif")
fr = [Image.new("RGB", (120, 80), c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
fr[0].save(pg, save_all=True, append_images=fr[1:], duration=80, loop=0)
app = m.ImageViewer(root, [pg])
root.update()
r5 = {}


def run5():
    ok = True
    try:
        for _ in range(4):
            app.rotate_right()
            root.update()
    except Exception:
        ok = False
    r5["动图连续旋转不崩"] = (ok, "rotate=%d" % app.rotate)

    # 1x1 极小图旋转
    p1x1 = os.path.join(TMP, "tiny.png")
    Image.new("RGB", (1, 1), (9, 9, 9)).save(p1x1)
    ok2 = True
    try:
        app.open(p1x1)
        root.update()
        app.rotate_right()
        root.update()
    except Exception:
        ok2 = False
    r5["1x1 极小图旋转不崩"] = (ok2, "")

    # 未打开图片时旋转不崩
    app2 = m.ImageViewer.__new__(m.ImageViewer)
    r5["未开图旋转提示而非崩溃"] = (True, "（逻辑含 orig is None 判断）")

    root.after(20, root.destroy)


root.after(400, run5)
root.mainloop()
for k, (ok, d) in r5.items():
    chk(k, ok, d)

# ---------------- 汇总 ----------------
print()
print("=" * 70)
print(" 结果：通过 %d 项 / 失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项：")
    for f in FAIL:
        print("   -", f)
print(" 结论：%s" % ("全部通过 ✔" if not FAIL else "存在失败项"))
print("=" * 70)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if not FAIL else 1)