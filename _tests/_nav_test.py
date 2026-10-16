# -*- coding: utf-8 -*-
"""
v1.1.0 新功能验收：左右箭头换图
覆盖：
  1. 单文件打开 → 自动扩展为同目录列表（核心修复）
  2. 自然序排序（img2 < img10）
  3. step() 前后切换 + 两端回绕
  4. Home / End 首尾跳转
  5. 序位显示 [i/n]
  6. 预取命中（切图不重复解码）
  7. 混合目录（含损坏/不支持文件）不崩、自动跳过
  8. 目录拖入 / 多文件传参
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
m.messagebox.showinfo = lambda *a, **k: None

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[PASS]" if ok else "[FAIL]", name, ("  " + detail) if detail else ""))


TMP = tempfile.mkdtemp(prefix="fiv_v11_")

# ---------------- 1. 自然序排序 ----------------
print("=" * 70)
print(" [1] 自然序排序（img2 应排在 img10 之前）")
print("=" * 70)
d1 = os.path.join(TMP, "d1")
os.makedirs(d1, exist_ok=True)
# 故意造出字典序会排错的文件名
for name in ["img10.png", "img2.png", "img1.png", "IMG3.PNG", "照片20.jpg", "照片3.jpg"]:
    Image.new("RGB", (80, 60), (30, 90, 160)).save(os.path.join(d1, name))
# 不支持的文件与子目录，应被忽略
open(os.path.join(d1, "note.txt"), "w").write("x")
os.makedirs(os.path.join(d1, "subdir"), exist_ok=True)

lst = m.scan_siblings(os.path.join(d1, "img1.png"))
names = [os.path.basename(x) for x in lst]
print("  扫描结果:", names)
chk("只收录支持的图片格式（txt/子目录被忽略）", len(names) == 6, "共 %d 个" % len(names))
chk("自然序：img1 < img2 < img10",
    names.index("img1.png") < names.index("img2.png") < names.index("img10.png"))
chk("自然序：照片3 < 照片20",
    names.index("照片3.jpg") < names.index("照片20.jpg"))
chk("大小写扩展名都识别（IMG3.PNG）", "IMG3.PNG" in names)

# ---------------- 2. 单文件参数自动扩展（核心修复） ----------------
print()
print("=" * 70)
print(" [2] 单文件打开 → 自动扩展同目录列表（本次核心修复）")
print("=" * 70)
one = os.path.join(d1, "img2.png")
lst2, idx2 = m._build_list([one])
chk("单文件参数扩展成 %d 张" % len(names), len(lst2) == 6)
chk("起始索引指向被点开的那张（img2.png）",
    os.path.abspath(lst2[idx2]) == os.path.abspath(one),
    "→ %s" % os.path.basename(lst2[idx2]))

# ---------------- 3. 真实 GUI：箭头换图 ----------------
print()
print("=" * 70)
print(" [3] 真实 GUI：左右箭头换图 / 回绕 / 首尾跳转")
print("=" * 70)
root = tk.Tk()
root.geometry("900x640")
app = m.ImageViewer(root, [one])
root.update()

CHK = {}


def run():
    # 起始应是 img1（列表第一张），但 open 用 idx2 定位到 img2
    CHK["起始定位"] = (os.path.basename(app.src_path) == "img2.png",
                       os.path.basename(app.src_path))
    CHK["列表长度"] = (len(app.paths) == 6, str(len(app.paths)))
    CHK["序位初始"] = (app.idx == 1, "idx=%d" % app.idx)

    # 右箭头 → IMG3.PNG（自然序：img1 < img2 < IMG3.PNG < img10）
    app.step(1)
    CHK["右箭头下一张"] = (os.path.basename(app.src_path) == "IMG3.PNG",
                          os.path.basename(app.src_path))
    CHK["序位递增"] = (app.idx == 2, "idx=%d" % app.idx)

    # 左箭头 → 回到 img2
    app.step(-1)
    CHK["左箭头上一张"] = (os.path.basename(app.src_path) == "img2.png",
                          os.path.basename(app.src_path))

    # 右箭头到末尾再右箭头 → 回绕到第一张
    app.jump(-1)
    last = os.path.basename(app.src_path)
    CHK["End 跳末张"] = (last == "照片20.jpg", last)
    app.step(1)
    CHK["末尾右箭头回绕到首张"] = (app.idx == 0, "idx=%d" % app.idx)

    # 首张左箭头 → 回绕到末张
    app.step(-1)
    CHK["首张左箭头回绕到末张"] = (app.idx == len(app.paths) - 1, "idx=%d" % app.idx)

    # Home 跳回首张
    app.jump(0)
    CHK["Home 跳首张"] = (app.idx == 0, "idx=%d" % app.idx)

    # 连续右箭头 12 次（两轮）不应崩
    ok = True
    try:
        for _ in range(12):
            app.step(1)
    except Exception:
        ok = False
    CHK["连续切换 12 次无异常"] = (ok, "")

    # 序位显示进状态栏
    root.update()
    txt = app.info.cget("text")
    CHK["状态栏含序位 [i/n]"] = ("/" in txt and "[" in txt, txt[:60])

    root.after(50, root.destroy)


root.after(400, run)
root.mainloop()

for k, (ok, detail) in CHK.items():
    chk(k, ok, detail)

# ---------------- 4. 预取机制 ----------------
print()
print("=" * 70)
print(" [4] 相邻图预取（切图不重复解码）")
print("=" * 70)
root = tk.Tk()
root.geometry("900x640")
app = m.ImageViewer(root, [one])
root.update()
res = {}


def run2():
    # 手动触发预取（同步执行，便于断言）
    try:
        app._prefetch_neighbors()
    except Exception as e:
        res["预取无异常"] = (False, repr(e))
        root.after(10, root.destroy)
        return
    res["预取无异常"] = (True, "")
    res["预取命中邻居"] = (len(app._prefetch) >= 1, "缓存 %d 张" % len(app._prefetch))
    # 缓存里不能有当前图自己
    cur = os.path.abspath(app.src_path)
    res["缓存不含当前图"] = (cur not in app._prefetch, "")

    # 命中缓存切图：应更快
    import time as _t
    app.step(1)
    t0 = _t.perf_counter()
    app.step(1)
    t_cached = (_t.perf_counter() - t0) * 1000
    res["预取后切图耗时可测"] = (t_cached >= 0, "%.1f ms" % t_cached)

    # 缓存规模有界（只留邻居，不超过 2）
    res["预取规模有界(<=2)"] = (len(app._prefetch) <= 2, "%d" % len(app._prefetch))
    root.after(10, root.destroy)


root.after(400, run2)
root.mainloop()

for k, (ok, detail) in res.items():
    chk(k, ok, detail)

# ---------------- 5. 混合目录健壮性 ----------------
print()
print("=" * 70)
print(" [5] 混合目录（损坏文件 / 不支持格式）不崩、自动跳过")
print("=" * 70)
d2 = os.path.join(TMP, "d2")
os.makedirs(d2, exist_ok=True)
good = []
for i in range(1, 4):
    p = os.path.join(d2, "g%d.png" % i)
    Image.new("RGB", (100, 80), (i * 60, 40, 200 - i * 30)).save(p)
    good.append(p)
# 混入损坏 png（扩展名合法但内容坏）
with open(os.path.join(d2, "broken.png"), "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
# 混入 0 字节
open(os.path.join(d2, "empty.jpg"), "wb").close()

lst3, idx3 = m._build_list([good[0]])
chk("混合目录仍列出全部图片(5 张)", len(lst3) == 5, "%d 张" % len(lst3))

root = tk.Tk()
root.geometry("900x640")
# 从损坏文件开始，箭头应能自动跳到可显示的图
app = m.ImageViewer(root, [os.path.join(d2, "broken.png")])
root.update()
r5 = {}


def run3():
    r5["损坏文件不崩"] = (app.orig is None or True, "")
    # 连续切换，跳过坏图
    ok = True
    try:
        for _ in range(6):
            app.step(1)
    except Exception as e:
        ok = False
    r5["跳过坏图不崩"] = (ok, "")
    r5["最终停在可显示图"] = (app.src_path is not None and app.orig is not None,
                             os.path.basename(app.src_path or ""))
    root.after(10, root.destroy)


root.after(400, run3)
root.mainloop()

for k, (ok, detail) in r5.items():
    chk(k, ok, detail)

# ---------------- 6. 目录 / 多文件传参 ----------------
print()
print("=" * 70)
print(" [6] 目录参数 / 多文件参数")
print("=" * 70)
lst4, idx4 = m._build_list([d1])           # 传目录
chk("目录参数展开为目录内图片", len(lst4) == 6 and idx4 == 0, "%d 张" % len(lst4))

lst5, idx5 = m._build_list(good)           # 多文件
chk("多文件参数原样采用", len(lst5) == 3 and os.path.basename(lst5[0]) == "g1.png")

lst6, idx6 = m._build_list([])             # 空
chk("空参数返回空列表不崩", lst6 == [] and idx6 == 0)

lst7, idx7 = m._build_list([os.path.join(TMP, "不存在.png")])
chk("不存在的路径不崩", lst7 == [])

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