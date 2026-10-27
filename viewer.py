# -*- coding: utf-8 -*-
"""
FastImageViewer - 极简极速图片查看器
只做三件事：打开图片 / 复制到剪贴板 / 保存到本地
设计目标：启动快、打开快、占用小、无常驻后台
健壮性目标：大图小图、大文件小文件、损坏文件，一律不崩
"""
import os
import re
import sys
import io
import json
import queue
import shutil
import ctypes
import threading
from ctypes import wintypes

import tkinter as tk
from tkinter import filedialog, messagebox

# ---------- 极速启动：延迟导入 ----------
Image = None
ImageTk = None
ImageOps = None
ImageFile = None
pytesseract = None


def _load_pil():
    global Image, ImageTk, ImageOps, ImageFile
    if Image is None:
        from PIL import Image as _I, ImageTk as _IT, ImageOps as _IO, ImageFile as _IF
        _I.MAX_IMAGE_PIXELS = None          # 超大图不做"解压炸弹"拒绝
        _IF.LOAD_TRUNCATED_IMAGES = True    # 截断/半损坏文件尽量出图，而不是直接失败
        Image, ImageTk, ImageOps, ImageFile = _I, _IT, _IO, _IF


def _load_tesseract():
    """延迟加载 pytesseract 并指定项目内便携版 Tesseract-OCR 路径"""
    global pytesseract
    if pytesseract is None:
        import pytesseract as _pt
        pytesseract = _pt
    # PyInstaller onedir: sys._MEIPASS = _internal/；开发模式: __file__ 所在目录
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    tess_exe = os.path.join(base, "tesseract", "tesseract.exe")
    tessdata = os.path.join(base, "tesseract", "tessdata")
    if os.path.isfile(tess_exe):
        pytesseract.pytesseract.tesseract_cmd = tess_exe
        os.environ["TESSDATA_PREFIX"] = tessdata
    return pytesseract


APP_NAME = "FastImageViewer"
VERSION = "1.3.0"
SUPPORTED = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
             ".tiff", ".tif", ".ico")
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "error.log")
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "ImageViewer")

# 单图像素上限保护：超过则先在解码前预警，避免吃光内存
HUGE_PIXELS = 300_000_000       # 3 亿像素
ANIM_MAX_FRAMES = 5000          # 动图帧数上限（防异常文件死循环）

# 相邻图预取上限：日常照片（手机 1200 万像素 / 单反 2400 万像素）都在范围内，
# 只有超大图才跳过——预取是为了让普通图翻页跟手，不为极端图浪费内存。
PREFETCH_MAX_BYTES = 30 * 1024 * 1024     # 单文件 30 MB
PREFETCH_MAX_PIXELS = 80_000_000          # 8000 万像素


def log_error(text):
    """windowed 模式无控制台，异常写日志便于排障"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        import datetime
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.datetime.now().isoformat(" ", "seconds"), text))
    except Exception:
        pass


def _short(exc, limit=300):
    """异常信息截断，避免超长弹窗"""
    try:
        s = "%s: %s" % (type(exc).__name__, exc)
    except Exception:
        s = "未知错误"
    s = s.replace("\r", " ").strip()
    return s[:limit]


# ---------- 配置 ----------
def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- 同目录图片列表（左右键换图的依据） ----------
def scan_siblings(path):
    """
    扫描 path 所在目录里的所有可显示图片，按文件名自然序返回。
    自然序 = 带数字感知：img2 < img10（而非字典序 img10 < img2）。
    任何异常都退化返回 [path]，绝不抛异常。
    """
    try:
        if not path:
            return []
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            return [path]
        low = tuple(e.lower() for e in SUPPORTED)

        def is_img(name):
            try:
                return os.path.isfile(os.path.join(folder, name)) and name.lower().endswith(low)
            except Exception:
                return False

        if os.path.isdir(path):          # 目录交给调用方处理
            return []
        names = [n for n in os.listdir(folder) if is_img(n)]
        if not names:
            return [path]

        def natural_key(s):
            # 把数字段切成整数参与比较，避免 img10 排在 img2 前面
            parts = re.split(r"(\d+)", s.lower())
            return [int(p) if p.isdigit() else p for p in parts]

        names.sort(key=natural_key)
        return [os.path.join(folder, n) for n in names]
    except Exception:
        return [path] if path else []


def scan_folder(folder):
    """与 scan_siblings 同逻辑，但输入是目录本身（拖入文件夹时用）"""
    try:
        if not folder or not os.path.isdir(folder):
            return []
        low = tuple(e.lower() for e in SUPPORTED)
        names = [n for n in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, n)) and n.lower().endswith(low)]
        if not names:
            return []

        def natural_key(s):
            parts = re.split(r"(\d+)", s.lower())
            return [int(p) if p.isdigit() else p for p in parts]

        names.sort(key=natural_key)
        return [os.path.join(folder, n) for n in names]
    except Exception:
        return []


def _build_list(paths):
    """
    把命令行/拖入的参数整理成待浏览列表：
      - 多个文件参数 → 直接采用（多选打开的原生顺序）
      - 单个文件     → 扩展为该文件所在目录的全部图片（这样箭头才有图可换）
      - 单个目录     → 展开为目录内全部图片
    返回 (列表, 起始索引)
    """
    files, folders = [], []
    for p in (paths or []):
        try:
            if p and os.path.isdir(p):
                folders.append(p)
            elif p and os.path.isfile(p):
                files.append(p)
        except Exception:
            continue

    if len(files) >= 2:
        start = os.path.abspath(files[0])
        lst = list(files)
        try:
            idx = next(i for i, x in enumerate(lst) if os.path.abspath(x) == start)
        except StopIteration:
            idx = 0
        return lst, idx

    if len(files) == 1:
        lst = scan_siblings(files[0])
        start = os.path.abspath(files[0])
        try:
            idx = next(i for i, x in enumerate(lst) if os.path.abspath(x) == start)
        except StopIteration:
            lst, idx = [files[0]], 0
        return lst, idx

    if folders:
        lst = scan_folder(folders[0])
        if lst:
            return lst, 0

    return [], 0


# ---------- Windows 剪贴板（CF_DIB，零依赖） ----------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalLock.restype = wintypes.LPVOID
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.CloseClipboard.restype = wintypes.BOOL

CF_DIB = 8
CF_DIBV5 = 17
GMEM_MOVEABLE = 0x0002


def _flatten_to_rgb(img):
    """把任意带透明通道的模式压平成白底 RGB"""
    if img.mode in ("RGBA", "LA", "P", "PA"):
        try:
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            return bg
        except Exception:
            return img.convert("RGB")
    if img.mode == "RGB":
        return img
    return img.convert("RGB")


def copy_image_to_clipboard(pil_img):
    """把 PIL 图像放进 Windows 剪贴板（DIB + DIBV5，兼容绝大多数软件）"""
    _load_pil()
    has_alpha = pil_img.mode in ("RGBA", "LA", "P", "PA")
    try:
        rgb = pil_img if has_alpha else _flatten_to_rgb(pil_img)
        if has_alpha:
            rgb = _flatten_to_rgb(pil_img)
    except Exception:
        rgb = pil_img.convert("RGB")
        has_alpha = False

    buf = io.BytesIO()
    rgb.save(buf, "BMP")
    dib = buf.getvalue()[14:]  # 去掉 14 字节 BMP 文件头 -> DIB
    buf.close()

    payloads = [(CF_DIB, dib)]

    # 带透明通道时额外提供 DIBV5（部分软件优先取它，保留 alpha）
    if has_alpha:
        try:
            buf2 = io.BytesIO()
            rgba = pil_img.convert("RGBA")
            rgba.save(buf2, "BMP")
            raw = buf2.getvalue()
            buf2.close()
            bih = raw[14:54]                             # BITMAPINFOHEADER(40)
            pixel_off = int.from_bytes(raw[10:14], "little")
            pixels = raw[pixel_off:]
            v5 = bytearray()
            v5 += (124).to_bytes(4, "little")            # bV5Size
            v5 += bih[4:16]                              # 宽高平面位深压缩
            v5 += (0).to_bytes(4, "little")              # bV5SizeImage
            v5 += (0).to_bytes(4, "little")              # 分辨率 x
            v5 += (0).to_bytes(4, "little")              # 分辨率 y
            v5 += (0).to_bytes(4, "little")              # 已用颜色
            v5 += (0).to_bytes(4, "little")              # 重要颜色
            v5 += b"\x00\x00\xff\x00"                    # 红掩码
            v5 += b"\x00\xff\x00\x00"                    # 绿掩码
            v5 += b"\xff\x00\x00\x00"                    # 蓝掩码
            v5 += b"\x00\x00\x00\xff"                    # alpha 掩码
            v5 += b"\x00" * 4                            # CSType
            v5 += b"\x00" * 36                           # 端点
            v5 += b"\x00" * 12                           # gamma
            v5 += (0).to_bytes(4, "little")              # intent
            v5 += (0).to_bytes(4, "little")              # profile data
            v5 += (0).to_bytes(4, "little")              # profile size
            v5 += (0).to_bytes(4, "little")              # reserved
            payloads.append((CF_DIBV5, bytes(v5) + pixels))
        except Exception:
            pass

    if not _user32.OpenClipboard(None):
        raise RuntimeError("剪贴板被其他程序占用，请稍后重试")
    try:
        _user32.EmptyClipboard()
        ok = False
        for fmt, data in payloads:
            h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                continue
            p = _kernel32.GlobalLock(h)
            if not p:
                _kernel32.GlobalFree(h)
                continue
            ctypes.memmove(p, data, len(data))
            _kernel32.GlobalUnlock(h)
            if _user32.SetClipboardData(fmt, h):
                ok = True   # 所有权已移交系统，不可再 GlobalFree
            else:
                _kernel32.GlobalFree(h)
        if not ok:
            raise RuntimeError("写入剪贴板失败")
    finally:
        _user32.CloseClipboard()


def unique_path(folder, filename):
    """目录下重名自动加 _1 / _2 后缀（最多尝试 9999 次）"""
    base, ext = os.path.splitext(filename)
    target = os.path.join(folder, filename)
    n = 1
    while os.path.exists(target):
        target = os.path.join(folder, "%s_%d%s" % (base, n, ext))
        n += 1
        if n > 9999:
            break
    return target


# ---------- 主界面 ----------
class ImageViewer:
    WHEEL_STEP = 1.15
    ZOOM_MIN = 0.02                 # 最小倍率（缩到 2%）
    ZOOM_MAX_FACTOR = 40.0          # 倍率上限
    ZOOM_MAX_PIXELS = 120_000_000   # 放大后输出像素上限（防止 resize 吃光内存）

    def __init__(self, root, paths):
        self.root = root
        self.paths = []
        self.idx = 0
        self.orig = None            # 当前显示用的图像
        self.src_path = None        # 当前文件路径
        self._orig_size = (0, 0)    # 原图尺寸（用于提示降采样）
        self._downscaled = False    # 显示图是否已降采样（复制/另存会重新读全分辨率）
        self._anim_source = None    # 动图源对象（懒解码，不预载全部帧）
        self.anim_total = 0
        self.anim_idx = 0
        self.anim_job = None
        self.tkimg = None
        self.zoom = None            # None = 自适应窗口；否则为倍率
        self.rotate = 0             # 顺时针旋转角度：0 / 90 / 180 / 270
        self._render_job = None
        self._last_size = None
        self._alive = True
        self._prefetch = {}         # 相邻图预解码缓存 {绝对路径: PIL图像}
        self._prefetch_job = None   # 预取定时任务句柄
        self._prefetch_inflight = set()   # 正在后台解码中的键
        self._prefetch_busy = False       # 是否有预取线程在跑
        self._prefetch_q = queue.Queue()  # 后台→UI 的线程安全投递通道
        self._prefetch_poll_job = None    # UI 侧轮询句柄

        cfg = load_config()
        self.save_dir = cfg.get("save_dir") or DEFAULT_SAVE_DIR
        self.bg = cfg.get("bg", "#2b2b2b")

        # OCR 状态
        self.ocr_results = []
        self.ocr_panel = None
        self.ocr_listbox = None
        self.ocr_thread = None

        # 待浏览列表：单个文件也会扩展成"同目录全部图片"，左右箭头才有意义
        self.paths, self.idx = _build_list(paths)

        self._build_ui()
        self._bind_keys()

        # 先把空窗口推到屏幕（用户体感"秒开"），再加载图片
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

        if self.paths:
            start = self.idx
            self.root.after(1, lambda: self.open(self.paths[start]))
        else:
            self.root.title("极速看图 - 拖入或 Ctrl+O 打开")
            self.root.after(50, self.pick_file)

    # ---- UI ----
    def _build_ui(self):
        r = self.root
        r.title("极速看图")
        r.configure(bg=self.bg)
        r.geometry("960x680")
        r.minsize(240, 180)
        r.protocol("WM_DELETE_WINDOW", self._on_close)

        bar = tk.Frame(r, bg="#333333", height=30)
        bar.pack(side="top", fill="x")

        def mkbtn(text, cmd):
            b = tk.Button(bar, text=text, command=cmd, bd=0, relief="flat",
                          bg="#3c3c3c", fg="#e8e8e8", activebackground="#505050",
                          activeforeground="#ffffff", padx=12, pady=3,
                          cursor="hand2")
            b.pack(side="left", padx=(6, 0), pady=4)
            return b

        mkbtn("打开", self.pick_file)
        mkbtn("复制到剪贴板", self.copy_clip)
        mkbtn("保存到本地", self.save_fixed)
        mkbtn("另存为…", self.save_as)
        mkbtn("↺", self.rotate_left)
        mkbtn("↻", self.rotate_right)
        mkbtn("识别文字", self.start_ocr)

        self.info = tk.Label(bar, text="", bg="#333333", fg="#9a9a9a",
                             anchor="e", padx=10)
        self.info.pack(side="right", fill="x", expand=True)

        # 内容区：canvas（左）+ OCR 面板（右，隐藏）
        self._content = tk.Frame(r, bg=self.bg)
        self._content.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(self._content, bg=self.bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        # ---- OCR 结果侧栏（默认隐藏） ----
        self._build_ocr_panel()

        self.toast = tk.Label(r, text="", bg="#000000", fg="#ffffff",
                              padx=14, pady=6)

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())
        self._bind_drop(r)

    def _bind_drop(self, widget):
        """拖入文件/文件夹即可看图（Windows 原生 DnD）"""
        try:
            import tkinter.dnd  # noqa: F401  仅确认模块存在
        except Exception:
            pass
        try:
            widget.drop_target_register  # 部分精简版 tk 无此方法
        except Exception:
            return
        try:
            DND_FILES = 1
            for w in (self.root, self.canvas):
                try:
                    w.drop_target_register("DND_Files")
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_drop(self, event):
        """处理拖放：拆出真实路径，扩展到同目录列表后显示"""
        try:
            raw = getattr(event, "data", "") or ""
            paths = self.root.tk.splitlist(raw)
        except Exception:
            return
        if not paths:
            return
        try:
            lst, idx = _build_list(list(paths))
            if not lst:
                lst, idx = [paths[0]], 0
            self.paths = lst
            self.idx = idx
            self._prefetch.clear()
            self.open(self.paths[self.idx])
        except Exception as e:
            self._error("拖入的文件无法打开", None, e)

    def _bind_keys(self):
        r = self.root
        r.bind("<Escape>", lambda e: self._on_close())
        r.bind("<Control-o>", lambda e: self.pick_file())
        r.bind("<Control-c>", lambda e: self.copy_clip())
        r.bind("<Control-s>", lambda e: self.save_fixed())
        r.bind("<Control-Shift-S>", lambda e: self.save_as())
        # 左右箭头：上一张 / 下一张（核心操作）
        r.bind("<Left>", lambda e: self.step(-1))
        r.bind("<Right>", lambda e: self.step(1))
        # 兼容键：PageUp/PageDown、A/D、上下箭头
        r.bind("<Prior>", lambda e: self.step(-1))
        r.bind("<Next>", lambda e: self.step(1))
        r.bind("<Up>", lambda e: self.step(-1))
        r.bind("<Down>", lambda e: self.step(1))
        r.bind("<a>", lambda e: self.step(-1))
        r.bind("<A>", lambda e: self.step(-1))
        r.bind("<d>", lambda e: self.step(1))
        r.bind("<D>", lambda e: self.step(1))
        # 首尾跳转
        r.bind("<Home>", lambda e: self.jump(0))
        r.bind("<End>", lambda e: self.jump(-1))
        r.bind("<plus>", lambda e: self.zoom_by(self.WHEEL_STEP))
        r.bind("<equal>", lambda e: self.zoom_by(self.WHEEL_STEP))
        r.bind("<minus>", lambda e: self.zoom_by(1 / self.WHEEL_STEP))
        r.bind("<0>", lambda e: self.zoom_reset())
        r.bind("<space>", lambda e: self.step(1))
        # 旋转：R 右转 90°，Shift+R / L 左转 90°
        r.bind("<r>", lambda e: self.rotate_right())
        r.bind("<R>", lambda e: self.rotate_left())
        r.bind("<l>", lambda e: self.rotate_left())
        r.bind("<L>", lambda e: self.rotate_left())
        r.bind("<Control-r>", lambda e: self.rotate_reset())
        r.bind("<Control-t>", lambda e: self.start_ocr())
        r.focus_set()

    def jump(self, idx):
        """跳到指定索引（-1 表示最后一张）"""
        n = len(self.paths)
        if n == 0:
            return
        self.idx = (n - 1) if idx == -1 else max(0, min(idx, n - 1))
        if not self.open(self.paths[self.idx]):
            self.toast_msg("无法打开：%s" % os.path.basename(self.paths[self.idx]), err=True)

    def _on_close(self):
        self._alive = False
        self._stop_anim()
        self._cancel_prefetch_job()
        try:
            self._prefetch.clear()
            self._prefetch_inflight.clear()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _safe_after(self, ms, fn):
        """窗口已销毁时不再排程，避免 TclError"""
        if not self._alive:
            return None
        try:
            return self.root.after(ms, fn)
        except Exception:
            return None

    def toast_msg(self, text, err=False):
        if not self._alive:
            return
        try:
            self.toast.configure(text=text, bg="#8b1a1a" if err else "#1a5c1a")
            self.toast.place(relx=0.5, rely=0.94, anchor="center")
            self._safe_after(1800, lambda: self._hide_toast())
        except Exception:
            pass

    def _hide_toast(self):
        try:
            self.toast.place_forget()
        except Exception:
            pass

    # ---- OCR 文字识别 ----
    def _build_ocr_panel(self):
        """构建 OCR 结果侧栏（默认隐藏），仿微信读图文字列表风格"""
        panel = tk.Frame(self._content, bg="#1e1e1e", width=300, bd=0)
        # 顶栏
        topbar = tk.Frame(panel, bg="#2d2d2d", height=36)
        topbar.pack(side="top", fill="x")
        tk.Label(topbar, text="识别结果", bg="#2d2d2d", fg="#cccccc",
                 font=("Microsoft YaHei UI", 10), anchor="w", padx=10).pack(
                     side="left", fill="y")
        def _close():
            panel.pack_forget()
            self.ocr_results = []
        tk.Button(topbar, text="✕", command=_close, bd=0, relief="flat",
                  bg="#2d2d2d", fg="#888888", activebackground="#444444",
                  activeforeground="#ffffff", font=("", 10), cursor="hand2").pack(
                      side="right", padx=8, pady=6)

        # 列表区（含滚动条）
        list_frame = tk.Frame(panel, bg="#1e1e1e")
        list_frame.pack(side="top", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, bg="#333333", troughcolor="#1e1e1e",
                                 activebackground="#555555", bd=0)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(list_frame, bg="#1e1e1e", fg="#d4d4d4",
                        selectbackground="#264f78", selectforeground="#ffffff",
                        activestyle="none", bd=0, highlightthickness=0,
                        font=("Microsoft YaHei UI", 10),
                        yscrollcommand=scrollbar.set)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=lb.yview)

        # 底栏按钮
        btns = tk.Frame(panel, bg="#252525", height=36)
        btns.pack(side="bottom", fill="x")
        tk.Button(btns, text="复制选中", command=self._copy_ocr_line,
                  bd=0, relief="flat", bg="#2d2d2d", fg="#cccccc",
                  activebackground="#3c3c3c", activeforeground="#ffffff",
                  font=("Microsoft YaHei UI", 9), cursor="hand2",
                  padx=10, pady=4).pack(side="left", padx=8, pady=5)
        tk.Button(btns, text="复制全部", command=self._copy_ocr_all,
                  bd=0, relief="flat", bg="#2d2d2d", fg="#cccccc",
                  activebackground="#3c3c3c", activeforeground="#ffffff",
                  font=("Microsoft YaHei UI", 9), cursor="hand2",
                  padx=10, pady=4).pack(side="right", padx=8, pady=5)
        # 行数标签
        self._ocr_count_label = tk.Label(btns, text="", bg="#252525", fg="#888888",
                                         font=("Microsoft YaHei UI", 8))
        self._ocr_count_label.pack(side="right", padx=4)

        self.ocr_panel = panel
        self.ocr_listbox = lb

    def start_ocr(self):
        """触发文字识别（Ctrl+T / 按钮）"""
        if self.orig is None:
            self.toast_msg("还没有打开图片", err=True)
            return
        # 收起旧面板，开始新识别
        if self.ocr_panel:
            self.ocr_panel.pack_forget()
        self.ocr_results = []
        self.toast_msg("正在识别文字…")
        try:
            t = threading.Thread(target=self._run_ocr, daemon=True)
            t.start()
            self.ocr_thread = t
        except Exception as e:
            self.toast_msg("启动识别失败：%s" % _short(e, 60), err=True)

    def _run_ocr(self):
        """后台线程：执行 OCR，结果回传 UI 线程"""
        _load_pil()
        try:
            _load_tesseract()
        except Exception as e:
            self.root.after(0, lambda: self.toast_msg(
                "Tesseract 未安装，请先运行 install_tesseract.py", err=True))
            return

        # 取全分辨率图像（旋转已应用），OCR 需要清晰源
        try:
            img = self._full_image()
        except Exception as e:
            self.root.after(0, lambda: self.toast_msg("取图失败：%s" % _short(e, 60), err=True))
            return

        try:
            data = pytesseract.image_to_data(
                img, lang="chi_sim+eng",
                output_type=pytesseract.Output.DICT)
        except Exception as e:
            self.root.after(0, lambda: self.toast_msg(
                "OCR 识别失败：%s" % _short(e, 80), err=True))
            return

        # 提取非空文本行
        results = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if text and len(text) >= 1:
                conf = data["conf"][i]
                results.append({"text": text, "conf": int(conf) if isinstance(conf, (int, float)) and conf > 0 else 0})
        self.ocr_results = results
        self.root.after(0, self._show_ocr_results)

    def _show_ocr_results(self):
        """UI 线程：展示识别结果到侧栏"""
        if not self._alive or self.ocr_listbox is None or self.ocr_panel is None:
            return
        lb = self.ocr_listbox
        lb.delete(0, "end")
        for r in self.ocr_results:
            conf_str = " · %d%%" % r["conf"] if r["conf"] > 0 else ""
            lb.insert("end", r["text"] + conf_str)
        n = len(self.ocr_results)
        self._ocr_count_label.configure(text="%d 条" % n if n else "")
        if n > 0:
            self.ocr_panel.pack(side="right", fill="y")
            self.toast_msg("识别到 %d 条文字 ✓" % n)
        else:
            self.toast_msg("未识别到文字", err=True)

    def _copy_ocr_line(self):
        """复制选中的文字行到剪贴板"""
        lb = self.ocr_listbox
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            self.toast_msg("请先在列表中选择一行文字", err=True)
            return
        idx = sel[0]
        if 0 <= idx < len(self.ocr_results):
            text = self.ocr_results[idx]["text"]
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.toast_msg("已复制：%s" % (text[:40] + ("..." if len(text) > 40 else "")))
            except Exception:
                self.toast_msg("复制失败（剪贴板不可用）", err=True)

    def _copy_ocr_all(self):
        """复制全部识别文字到剪贴板"""
        if not self.ocr_results:
            self.toast_msg("没有可复制的文字", err=True)
            return
        text = "\n".join(r["text"] for r in self.ocr_results)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.toast_msg("已复制全部 %d 条文字 ✓" % len(self.ocr_results))
        except Exception:
            self.toast_msg("复制失败（剪贴板不可用）", err=True)

    def _error(self, title, path=None, exc=None):
        detail = ""
        if path:
            detail += str(path)
        if exc is not None:
            detail += ("\n\n" if detail else "") + _short(exc)
        log_error("%s | %s | %s" % (title, path, _short(exc) if exc else ""))
        try:
            messagebox.showerror(title, detail or title)
        except Exception:
            pass

    # ---- 解码 ----
    @staticmethod
    def _work_target(canvas):
        """解码目标尺寸：略大于窗口，既保证缩放清晰又不浪费内存"""
        try:
            w = max(canvas.winfo_width(), 1)
            h = max(canvas.winfo_height(), 1)
        except Exception:
            w, h = 960, 640
        if w < 200:      # 窗口还没布局好
            w, h = 1280, 900
        return int(w * 1.6) + 64, int(h * 1.6) + 64

    def _decode_for_display(self, path, target=None):
        """
        分格式走最快解码路径，返回 (图像, 格式, 总帧数, 原始尺寸)。
        关键：先降低解码负担，再谈缩放算法。
          - JPEG: draft() 在解码层直接缩，最快
          - 其余: reduce() 盒式降采样，按整数倍率快速缩
          - 动图: 不预解码全部帧
        注意：本函数不改实例状态；target 可显式传入，便于后台线程安全调用。
        """
        im = Image.open(path)
        fmt = (im.format or "").upper()
        orig_size = im.size

        try:
            n_frames = int(getattr(im, "n_frames", 1) or 1)
        except Exception:
            n_frames = 1
        if n_frames < 1:
            n_frames = 1
        if n_frames > ANIM_MAX_FRAMES:
            n_frames = 1          # 异常帧数，按静态图处理

        tw, th = target if target else self._work_target(self.canvas)

        # ① JPEG：DCT 缩略解码，代价几乎为零
        if fmt == "JPEG":
            try:
                im.draft("RGB", (tw, th))
            except Exception:
                pass

        # ② 非动图：reduce() 按整数倍率降采样（实测比全解码+LANCZOS 快 4~5 倍）
        animated = fmt in ("GIF", "WEBP") and n_frames > 1
        if not animated:
            try:
                f = min(orig_size[0] // max(tw, 1), orig_size[1] // max(th, 1))
                if f >= 2:
                    im = im.reduce(f)
            except Exception:
                pass

        if not animated:
            im.load()

        return im, fmt, n_frames, orig_size

    # ---- 打开 ----
    def pick_file(self):
        try:
            path = filedialog.askopenfilename(
                title="打开图片",
                filetypes=[("图片", " ".join("*" + e for e in SUPPORTED)),
                           ("所有文件", "*.*")])
        except Exception as e:
            self._error("打开对话框失败", None, e)
            return
        if not path:
            return
        try:
            # 手动打开也扩展成同目录列表，左右箭头才能连续看图
            lst, idx = _build_list([path])
            self.paths = lst or [path]
            self.idx = idx
            self._prefetch.clear()
            self.open(self.paths[self.idx])
        except Exception as e:
            self._error("打开失败", path, e)

    def step(self, delta):
        """左右键换图。delta=-1 上一张，+1 下一张。到头回绕。"""
        n = len(self.paths)
        if n < 2:
            self.toast_msg("当前目录只有这一张图片")
            return
        for _ in range(n):
            self.idx = (self.idx + delta) % n
            # quiet=True：坏图静默跳过，不弹模态框打断连续浏览
            if self.open(self.paths[self.idx], quiet=True):
                return
        # 全部无法打开
        self.idx = (self.idx - delta) % n     # 回滚到原来那张
        self.toast_msg("同目录没有其他可显示的图片", err=True)

    # ---- 相邻图预取（让按箭头"零等待"） ----
    def _candidate_neighbors(self):
        """返回邻居路径列表：先下一张再上一张，两端回绕"""
        n = len(self.paths)
        if n < 2:
            return []
        out = [self.paths[(self.idx + 1) % n]]
        if n > 2:
            out.append(self.paths[(self.idx - 1) % n])
        return out

    def _prefetch_neighbors(self):
        """
        把相邻图片提前解码好放内存，按箭头时直接命中。
        在后台线程解码：不占用 UI 线程，按键响应始终跟手。
        有硬上限：文件过大/像素过多就跳过，宁可慢一点也不吃内存。
        """
        self._prefetch_job = None
        if not self._alive or self._prefetch_busy:
            return
        targets = []
        for p in self._candidate_neighbors():
            key = os.path.abspath(p)
            if key in self._prefetch:
                continue
            try:
                if not os.path.isfile(p):
                    continue
                if os.path.getsize(p) > PREFETCH_MAX_BYTES:
                    continue
            except Exception:
                continue
            targets.append((key, p))
        # 只留邻居，防止内存无界增长
        try:
            keep = set(os.path.abspath(x) for x in self._candidate_neighbors())
            for k in [k for k in self._prefetch if k not in keep and k not in self._prefetch_inflight]:
                self._prefetch.pop(k, None)
        except Exception:
            pass
        if not targets:
            return
        # 在 UI 线程先取好解码目标尺寸，避免后台线程碰 Tk 对象
        try:
            target = self._work_target(self.canvas)
        except Exception:
            target = (1280, 900)
        self._prefetch_busy = True
        try:
            t = threading.Thread(target=self._prefetch_worker, args=(targets, target), daemon=True)
            t.start()
        except Exception:
            self._prefetch_busy = False

    def _prefetch_worker(self, targets, target=None):
        """后台解码线程。结果回传前先确认目标仍是当前图的邻居。"""
        try:
            for key, p in targets:
                if not self._alive:
                    return
                if key in self._prefetch_inflight:
                    continue
                self._prefetch_inflight.add(key)
                pm = None
                try:
                    pm, fmt, nf, osize = self._decode_for_display(p, target)
                    if fmt in ("GIF", "WEBP") and nf > 1:
                        pm = None                    # 动图不预取
                    elif pm.size[0] * pm.size[1] > PREFETCH_MAX_PIXELS:
                        pm = None                        # 太大，放弃
                    elif pm is not None:
                        try:
                            pm._fiv_orig_size = osize
                        except Exception:
                            pass
                except Exception:
                    pm = None
                finally:
                    self._prefetch_inflight.discard(key)
                if pm is None or not self._alive:
                    continue
                # 只投递到线程安全队列；由 UI 线程轮询接收。
                # 绝不在后台线程里调用 root.after()——Tk 不是线程安全的，会挂死。
                try:
                    self._prefetch_q.put((key, pm))
                except Exception:
                    pass
        finally:
            self._prefetch_busy = False

    def _drain_prefetch_q(self):
        """UI 线程：消费后台预取结果。空队列时停止轮询，避免空转。"""
        self._prefetch_poll_job = None
        got = False
        try:
            while True:
                key, pm = self._prefetch_q.get_nowait()
                got = True
                if not self._alive:
                    continue
                keep = set(os.path.abspath(x) for x in self._candidate_neighbors())
                if key in keep:
                    self._prefetch[key] = pm
                    for k in [k for k in self._prefetch if k not in keep]:
                        self._prefetch.pop(k, None)
        except queue.Empty:
            pass
        except Exception:
            pass
        # 若仍有在途任务，继续轮询
        if self._alive and (self._prefetch_busy or not self._prefetch_q.empty()):
            self._prefetch_poll_job = self._safe_after(60, self._drain_prefetch_q)

    def _schedule_prefetch(self):
        self._cancel_prefetch_job()
        self._prefetch_job = self._safe_after(60, self._prefetch_neighbors)
        if self._prefetch_poll_job is None:
            self._prefetch_poll_job = self._safe_after(80, self._drain_prefetch_q)

    def _cancel_prefetch_job(self):
        if self._prefetch_job:
            try:
                self.root.after_cancel(self._prefetch_job)
            except Exception:
                pass
        self._prefetch_job = None
        if self._prefetch_poll_job:
            try:
                self.root.after_cancel(self._prefetch_poll_job)
            except Exception:
                pass
        self._prefetch_poll_job = None

    def open(self, path, quiet=False):
        """打开图片。成功返回 True，失败返回 False（不抛异常）。
        quiet=True 时不弹错误框（翻页时用，坏图静默跳过，不打断浏览）。"""
        self._stop_anim()
        _load_pil()

        if not path or not os.path.isfile(path):
            if quiet:
                log_error("跳过（文件不存在）：%s" % path)
            else:
                self._error("文件不存在", path)
            return False

        key = os.path.abspath(path)
        cached = self._prefetch.pop(key, None)
        try:
            if cached is not None:
                # 命中预取：省掉整个解码过程，按箭头几乎零等待
                im = cached
                fmt = (getattr(im, "format", "") or "").upper()
                n_frames = 1
                orig_size = getattr(im, "_fiv_orig_size", None) or im.size
            else:
                im, fmt, n_frames, orig_size = self._decode_for_display(path)
        except MemoryError:
            if quiet:
                log_error("跳过（内存不足）：%s" % path)
            else:
                self._error("内存不足，无法打开这张图片", path)
            return False
        except Exception as e:
            if quiet:
                log_error("跳过（无法打开）：%s | %s" % (path, _short(e)))
            else:
                self._error("无法打开（格式不支持或文件损坏）", path, e)
            return False

        self._orig_size = orig_size
        animated = fmt in ("GIF", "WEBP") and n_frames > 1
        try:
            if animated:
                # 动图懒解码：内存里始终只保留当前帧
                im.seek(0)
                self.orig = im.convert("RGBA")
                self._anim_source = im
                self.anim_total = n_frames
                self.anim_idx = 0
                self._downscaled = False
            else:
                # EXIF 方向校正（手机竖拍照片的关键，否则会横躺）
                try:
                    im = ImageOps.exif_transpose(im)
                except Exception:
                    pass
                self.orig = im
                self._anim_source = None
                self.anim_total = n_frames if n_frames > 1 else 0
                self._downscaled = (im.size != self._orig_size)
        except MemoryError:
            self._error("内存不足，无法打开这张图片", path)
            return False
        except Exception as e:
            self._error("无法打开（格式不支持或文件损坏）", path, e)
            return False

        # 成功
        self.src_path = path
        self.paths[self.idx] = path        # 同步列表（可能被交互式换过）
        self.zoom = None
        self.rotate = 0                    # 旋转是单张图的视图状态，换图即复位
        self._last_size = None
        try:
            self.root.title("%s - 极速看图" % os.path.basename(path))
        except Exception:
            pass
        if self._anim_source is not None:
            self._schedule_anim(self._anim_duration())
        self.render()
        self._schedule_prefetch()
        try:
            self.root.focus_set()
        except Exception:
            pass
        return True

    def _anim_duration(self):
        try:
            d = self._anim_source.info.get("duration", 100) or 100
            return max(int(d), 20)
        except Exception:
            return 100

    def _schedule_anim(self, dur=None):
        if self._anim_source is None or not self._alive:
            return
        self._cancel_anim_job()
        self.anim_job = self._safe_after(dur or self._anim_duration(), self._next_frame)

    def _cancel_anim_job(self):
        if self.anim_job:
            try:
                self.root.after_cancel(self.anim_job)
            except Exception:
                pass
        self.anim_job = None

    def _next_frame(self):
        self.anim_job = None
        if self._anim_source is None or not self._alive:
            return
        try:
            n = self.anim_total or 1
            self.anim_idx = (self.anim_idx + 1) % n
            self._anim_source.seek(self.anim_idx)
            self.orig = self._anim_source.convert("RGBA")
        except Exception:
            self._stop_anim()
            return
        self._last_size = None
        self.render()
        self._schedule_anim()

    def _stop_anim(self):
        self._cancel_anim_job()
        self._anim_source = None
        self.anim_total = 0
        self.anim_idx = 0

    # ---- 渲染 ----
    def _on_resize(self, _evt):
        if not self._alive:
            return
        if self._render_job:
            try:
                self.root.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None
        self._render_job = self._safe_after(110, self.render)

    def _on_wheel(self, evt):
        up = getattr(evt, "delta", 0) > 0
        self.zoom_by(self.WHEEL_STEP if up else 1 / self.WHEEL_STEP)

    def _fit_scale(self):
        try:
            W = max(self.canvas.winfo_width(), 1)
            H = max(self.canvas.winfo_height(), 1)
        except Exception:
            return 1.0
        iw, ih = self.orig.size
        if self.rotate in (90, 270):
            iw, ih = ih, iw          # 旋转 90/270 后宽高互换
        if iw <= 0 or ih <= 0:
            return 1.0
        return min(W / iw, H / ih, 1.0)

    def zoom_by(self, factor):
        if self.orig is None:
            return
        cur = self.zoom if self.zoom is not None else self._fit_scale()
        if cur <= 0:
            cur = 1.0
        self.zoom = max(self.ZOOM_MIN, min(cur * factor, self._max_zoom()))
        self._last_size = None
        self.render()

    def _max_zoom(self):
        """
        动态放大上限：不只卡倍率，更卡"输出像素总数"。
        8K 图放到 40 倍 = 530 亿像素，resize 会直接吃光内存卡死，
        因此按图本身尺寸反推一个安全的倍率上限。
        """
        try:
            iw, ih = self.orig.size
            px = max(1, iw * ih)
            # 允许最多 ~1.2 亿像素的显示缓冲（普通电脑也扛得住）
            cap = (self.ZOOM_MAX_PIXELS / px) ** 0.5
            return max(self.ZOOM_MIN, min(self.ZOOM_MAX_FACTOR, cap))
        except Exception:
            return self.ZOOM_MAX_FACTOR

    def zoom_reset(self):
        self.zoom = None
        self._last_size = None
        self.render()

    # ---- 旋转 ----
    def rotate_left(self):
        """逆时针 90°（按钮 ↺）"""
        self._rotate_by(-90)

    def rotate_right(self):
        """顺时针 90°（按钮 ↻）"""
        self._rotate_by(90)

    def rotate_reset(self):
        """恢复原始方向（Ctrl+R）"""
        if self.orig is None:
            return
        if self.rotate == 0:
            self.toast_msg("当前已是原始方向")
            return
        self.rotate = 0
        self._after_rotate(upright=True)

    def _rotate_by(self, deg):
        if self.orig is None:
            self.toast_msg("还没有打开图片", err=True)
            return
        cur = self.rotate or 0
        self.rotate = (cur + deg) % 360
        self._after_rotate()

    def _after_rotate(self, upright=False):
        """旋转后重算缩放基准：旋转会改变可用显示区域"""
        self._last_size = None
        # 旋转 90/270 后宽高互换，自适应倍率要重算一次才不别扭
        self.zoom = None
        if self._alive:
            self.render()
        # 旋转是临时视图状态，明确告知用户输出会跟随
        deg = self.rotate or 0
        if upright:
            self.toast_msg("已恢复原始方向")
        elif deg:
            self.toast_msg("已旋转 %d°（复制/保存将按当前方向输出）" % deg)

    def _apply_rotate(self, img):
        """
        把旋转应用到图像对象。只在需要时转置，0° 原样返回（零开销）。
        用 PIL 的 transpose 常量，90° 倍数是无损操作（纯像素重排，不重采样）。
        """
        if not self.rotate or img is None:
            return img
        try:
            if self.rotate == 90:
                return img.transpose(Image.ROTATE_270)   # PIL 的 ROTATE_* 是逆时针
            if self.rotate == 180:
                return img.transpose(Image.ROTATE_180)
            if self.rotate == 270:
                return img.transpose(Image.ROTATE_90)
        except Exception:
            pass
        return img

    def render(self):
        self._render_job = None
        if self.orig is None or not self._alive:
            return
        try:
            W = self.canvas.winfo_width()
            H = self.canvas.winfo_height()
        except Exception:
            return
        if W < 10 or H < 10:
            return
        iw, ih = self.orig.size
        if iw <= 0 or ih <= 0:
            return

        # 旋转在缩放之前做：90° 倍数是纯像素重排，不重采样、不损画质
        src = self.orig
        if self.rotate:
            src = self._apply_rotate(self.orig)
            if src is None:
                src = self.orig
        iw, ih = src.size

        s = self.zoom if self.zoom is not None else min(W / iw, H / ih, 1.0)
        nw = max(1, int(iw * s))
        nh = max(1, int(ih * s))
        if self._last_size == (nw, nh):
            return
        # 输出像素护栏：极端放大时宁可停下也不能让 resize 吃光内存
        if nw * nh > self.ZOOM_MAX_PIXELS:
            self.toast_msg("已达放大上限（再放大将超出内存安全范围）")
            return

        # 缩小时选重采样算法：
        #   小图 → LANCZOS（画质好，代价可忽略）
        #   大图 → BILINEAR（LANCZOS 在千万像素以上会慢到不可接受）
        if s < 1.0:
            resample = Image.LANCZOS if (iw * ih) <= 4_000_000 else Image.BILINEAR
        else:
            resample = Image.NEAREST

        # ★ 可见区域渲染：放大到远超画布时，只渲染画布能显示的那一块。
        #   否则 8K 图放大 5 倍要算 1 亿像素，而屏幕只看得到 0.07%——纯浪费。
        disp = None
        try:
            need = nw * nh
            # 超过画布面积的若干倍就切块渲染，避免无谓的大图运算
            budget = max(W * H * 4, 2_000_000)
            if need > budget:
                # 画布中心对准图像中心，取可见矩形对应的源图区域
                sw = max(1, int(min(nw, W) / max(s, 1e-6)))
                sh = max(1, int(min(nh, H) / max(s, 1e-6)))
                left = max(0, (iw - sw) // 2)
                top = max(0, (ih - sh) // 2)
                right = min(iw, left + sw)
                bottom = min(ih, top + sh)
                if right > left and bottom > top:
                    crop = src.crop((left, top, right, bottom))
                    cw = max(1, int(crop.size[0] * s))
                    ch = max(1, int(crop.size[1] * s))
                    disp = crop if (cw, ch) == crop.size else crop.resize((cw, ch), resample)
            if disp is None:
                disp = src if (nw, nh) == (iw, ih) else src.resize((nw, nh), resample)
            self.tkimg = ImageTk.PhotoImage(disp)
        except MemoryError:
            self._last_size = None
            self.toast_msg("内存不足，无法按此尺寸显示", err=True)
            return
        except Exception as e:
            self._last_size = None
            self.toast_msg("渲染失败：%s" % _short(e, 60), err=True)
            return

        self._last_size = (nw, nh)
        try:
            self.canvas.delete("all")
            self.canvas.create_image(W // 2, H // 2, image=self.tkimg)
        except Exception:
            return

        pct = int(round(s * 100))
        name = ""
        fsize = ""
        try:
            if self.paths and 0 <= self.idx < len(self.paths):
                name = os.path.basename(self.paths[self.idx])
            if self.src_path and os.path.isfile(self.src_path):
                b = os.path.getsize(self.src_path)
                fsize = "  ·  %.1f MB" % (b / 1048576.0) if b >= 1048576 else "  ·  %.0f KB" % (b / 1024.0)
        except Exception:
            pass
        extra = ""
        if self.anim_total > 1:
            extra = "  ·  动图 %d 帧" % self.anim_total
        rot = ""
        if self.rotate:
            rot = "  ·  旋转 %d°" % self.rotate
        pos = ""
        try:
            if len(self.paths) > 1:
                pos = "  [%d/%d]" % (self.idx + 1, len(self.paths))
        except Exception:
            pos = ""
        try:
            self.info.configure(text="%s   %d×%d   %d%%%s%s%s%s"
                                     % (name, iw, ih, pct, pos, rot, fsize, extra))
        except Exception:
            pass

    # ---- 高保真取图（复制/另存用） ----
    def _full_image(self):
        """返回全分辨率图像（已应用旋转）：显示时可能降过采样，输出绝不将就"""
        if self._anim_source is not None:
            return self._apply_rotate(self.orig)    # 动图按当前帧输出
        if self._downscaled and self.src_path and os.path.isfile(self.src_path):
            try:
                im = Image.open(self.src_path)
                im.load()
                try:
                    im = ImageOps.exif_transpose(im)
                except Exception:
                    pass
                return self._apply_rotate(im)
            except Exception:
                pass
        return self._apply_rotate(self.orig)

    # ---- 三大功能 ----
    def copy_clip(self):
        if self.orig is None:
            self.toast_msg("还没有打开图片", err=True)
            return
        try:
            copy_image_to_clipboard(self._full_image())
            self.toast_msg("已复制到剪贴板 ✓")
        except Exception as e:
            self.toast_msg("复制失败：%s" % _short(e, 80), err=True)

    def save_fixed(self):
        if self.orig is None:
            self.toast_msg("还没有打开图片", err=True)
            return
        try:
            os.makedirs(self.save_dir, exist_ok=True)
        except Exception as e:
            self.toast_msg("保存目录不可用：%s" % _short(e, 60), err=True)
            return
        try:
            src = self.src_path
            if src and os.path.isfile(src) and not self.rotate:
                # 未旋转：原文件直接复制，零画质损失
                dst = unique_path(self.save_dir, os.path.basename(src))
                shutil.copy2(src, dst)
            elif src and os.path.isfile(src) and self.rotate:
                # 已旋转：必须重新编码，否则存下去还是原方向
                dst = unique_path(self.save_dir, os.path.basename(src))
                self._save_image(dst, self._full_image())
            else:
                img = self._full_image()
                ext = (getattr(img, "format", None) or "PNG").lower()
                ext = {"jpeg": "jpg"}.get(ext, ext)
                dst = unique_path(self.save_dir, "image." + ext)
                self._save_image(dst, img)
            self.toast_msg("已保存：%s" % dst)
        except Exception as e:
            self.toast_msg("保存失败：%s" % _short(e, 80), err=True)

    def save_as(self):
        if self.orig is None:
            self.toast_msg("还没有打开图片", err=True)
            return
        cur = self.src_path or ""
        try:
            init_name = os.path.basename(cur) or "image.png"
        except Exception:
            init_name = "image.png"
        try:
            path = filedialog.asksaveasfilename(
                title="另存为", initialdir=self.save_dir,
                initialfile=init_name,
                defaultextension=os.path.splitext(cur)[1] or ".png",
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("BMP", "*.bmp"),
                           ("WebP", "*.webp"), ("GIF", "*.gif"), ("所有文件", "*.*")])
        except Exception as e:
            self._error("另存为对话框失败", None, e)
            return
        if not path:
            return
        try:
            same_ext = (os.path.splitext(path)[1].lower() ==
                        os.path.splitext(cur)[1].lower()) if cur else False
            if cur and os.path.isfile(cur) and same_ext and not self.rotate:
                shutil.copy2(cur, path)     # 未旋转且同格式 → 直接复制，零损失
            else:
                self._save_image(path, self._full_image())
            self.toast_msg("已保存：%s" % path)
        except Exception as e:
            self.toast_msg("保存失败：%s" % _short(e, 80), err=True)

    def _save_image(self, path, img=None):
        """保存图像，遇到不兼容的模式自动降级，保证不抛异常"""
        img = img if img is not None else self.orig
        ext = os.path.splitext(path)[1].lower()
        fmt = {".png": "PNG", ".bmp": "BMP", ".webp": "WEBP", ".gif": "GIF",
               ".tif": "TIFF", ".tiff": "TIFF", ".ico": "ICO",
               ".jpg": "JPEG", ".jpeg": "JPEG"}.get(ext)

        if fmt == "ICO":
            img.convert("RGBA").save(path, sizes=[(256, 256)])
            return

        if fmt in ("JPEG", "BMP"):
            img = _flatten_to_rgb(img)   # JPEG/BMP 不支持透明，压白底

        try:
            if fmt == "JPEG":
                img.save(path, "JPEG", quality=95)
            elif fmt:
                img.save(path, fmt)
            else:
                img.save(path)
        except Exception:
            # 降级：转成最通用的 RGB 再存一次
            _flatten_to_rgb(img).save(path, fmt if fmt else None)


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    try:
        _main()
    except Exception:
        import traceback
        log_error("FATAL\n" + traceback.format_exc())
        try:
            ctypes.windll.user32.MessageBoxW(
                None, "启动失败：\n\n" + traceback.format_exc(),
                "极速看图", 0x10)
        except Exception:
            pass
        raise


def _main():
    enable_dpi_awareness()
    # 先把 PIL 拉起来，主窗口一出现就能立刻画图
    _load_pil()
    paths = [a for a in sys.argv[1:] if not a.startswith("-")]
    root = tk.Tk()
    ImageViewer(root, paths)
    root.mainloop()


if __name__ == "__main__":
    main()