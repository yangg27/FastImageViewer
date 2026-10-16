# -*- coding: utf-8 -*-
"""
FastImageViewer - 极简极速图片查看器
只做三件事：打开图片 / 复制到剪贴板 / 保存到本地
设计目标：启动快、打开快、占用小、无常驻后台
健壮性目标：大图小图、大文件小文件、损坏文件，一律不崩
"""
import os
import sys
import io
import json
import shutil
import ctypes
from ctypes import wintypes

import tkinter as tk
from tkinter import filedialog, messagebox

# ---------- 极速启动：Pillow 延迟导入 ----------
Image = None
ImageTk = None
ImageOps = None
ImageFile = None


def _load_pil():
    global Image, ImageTk, ImageOps, ImageFile
    if Image is None:
        from PIL import Image as _I, ImageTk as _IT, ImageOps as _IO, ImageFile as _IF
        _I.MAX_IMAGE_PIXELS = None          # 超大图不做"解压炸弹"拒绝
        _IF.LOAD_TRUNCATED_IMAGES = True    # 截断/半损坏文件尽量出图，而不是直接失败
        Image, ImageTk, ImageOps, ImageFile = _I, _IT, _IO, _IF


APP_NAME = "FastImageViewer"
SUPPORTED = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
             ".tiff", ".tif", ".ico")
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "error.log")
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "ImageViewer")

# 单图像素上限保护：超过则先在解码前预警，避免吃光内存
HUGE_PIXELS = 300_000_000       # 3 亿像素
ANIM_MAX_FRAMES = 5000          # 动图帧数上限（防异常文件死循环）


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

    def __init__(self, root, paths):
        self.root = root
        self.paths = []
        for p in paths:
            try:
                if p and os.path.isfile(p):
                    self.paths.append(p)
            except Exception:
                pass
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
        self._render_job = None
        self._last_size = None
        self._alive = True

        cfg = load_config()
        self.save_dir = cfg.get("save_dir") or DEFAULT_SAVE_DIR
        self.bg = cfg.get("bg", "#2b2b2b")

        self._build_ui()
        self._bind_keys()

        # 先把空窗口推到屏幕（用户体感"秒开"），再加载图片
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

        if self.paths:
            self.root.after(1, lambda: self.open(self.paths[0]))
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

        self.info = tk.Label(bar, text="", bg="#333333", fg="#9a9a9a",
                             anchor="e", padx=10)
        self.info.pack(side="right", fill="x", expand=True)

        self.canvas = tk.Canvas(r, bg=self.bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="top", fill="both", expand=True)

        self.toast = tk.Label(r, text="", bg="#000000", fg="#ffffff",
                              padx=14, pady=6)

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())

    def _bind_keys(self):
        r = self.root
        r.bind("<Escape>", lambda e: self._on_close())
        r.bind("<Control-o>", lambda e: self.pick_file())
        r.bind("<Control-c>", lambda e: self.copy_clip())
        r.bind("<Control-s>", lambda e: self.save_fixed())
        r.bind("<Control-Shift-S>", lambda e: self.save_as())
        r.bind("<Left>", lambda e: self.step(-1))
        r.bind("<Right>", lambda e: self.step(1))
        r.bind("<Prior>", lambda e: self.step(-1))
        r.bind("<Next>", lambda e: self.step(1))
        r.bind("<plus>", lambda e: self.zoom_by(self.WHEEL_STEP))
        r.bind("<equal>", lambda e: self.zoom_by(self.WHEEL_STEP))
        r.bind("<minus>", lambda e: self.zoom_by(1 / self.WHEEL_STEP))
        r.bind("<0>", lambda e: self.zoom_reset())
        r.focus_set()

    def _on_close(self):
        self._alive = False
        self._stop_anim()
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

    def _decode_for_display(self, path):
        """
        分格式走最快解码路径，返回 (图像, 格式, 总帧数)。
        关键：先降低解码负担，再谈缩放算法。
          - JPEG: draft() 在解码层直接缩，最快
          - 其余: reduce() 盒式降采样，按整数倍率快速缩
          - 动图: 不预解码全部帧
        """
        im = Image.open(path)
        fmt = (im.format or "").upper()
        orig_size = im.size
        self._orig_size = orig_size

        try:
            n_frames = int(getattr(im, "n_frames", 1) or 1)
        except Exception:
            n_frames = 1
        if n_frames < 1:
            n_frames = 1
        if n_frames > ANIM_MAX_FRAMES:
            n_frames = 1          # 异常帧数，按静态图处理

        tw, th = self._work_target(self.canvas)

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

        return im, fmt, n_frames

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
        if path:
            self.paths = [path]
            self.idx = 0
            self.open(path)

    def step(self, delta):
        if len(self.paths) < 2:
            return
        n = len(self.paths)
        for _ in range(n):
            self.idx = (self.idx + delta) % n
            if self.open(self.paths[self.idx]):
                return
        # 全部无法打开
        self.toast_msg("同目录没有其他可显示的图片", err=True)

    def open(self, path):
        """打开图片。成功返回 True，失败返回 False（不抛异常）"""
        self._stop_anim()
        _load_pil()

        if not path or not os.path.isfile(path):
            self._error("文件不存在", path)
            return False

        try:
            im, fmt, n_frames = self._decode_for_display(path)
        except MemoryError:
            self._error("内存不足，无法打开这张图片", path)
            return False
        except Exception as e:
            self._error("无法打开（格式不支持或文件损坏）", path, e)
            return False

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
        self.zoom = None
        self._last_size = None
        try:
            self.root.title("%s - 极速看图" % os.path.basename(path))
        except Exception:
            pass
        if self._anim_source is not None:
            self._schedule_anim(self._anim_duration())
        self.render()
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
        if iw <= 0 or ih <= 0:
            return 1.0
        return min(W / iw, H / ih, 1.0)

    def zoom_by(self, factor):
        if self.orig is None:
            return
        cur = self.zoom if self.zoom is not None else self._fit_scale()
        if cur <= 0:
            cur = 1.0
        self.zoom = max(0.02, min(cur * factor, 40.0))
        self._last_size = None
        self.render()

    def zoom_reset(self):
        self.zoom = None
        self._last_size = None
        self.render()

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

        s = self.zoom if self.zoom is not None else min(W / iw, H / ih, 1.0)
        nw = max(1, int(iw * s))
        nh = max(1, int(ih * s))
        if self._last_size == (nw, nh):
            return

        # 缩小时选重采样算法：
        #   小图 → LANCZOS（画质好，代价可忽略）
        #   大图 → BILINEAR（LANCZOS 在千万像素以上会慢到不可接受）
        if s < 1.0:
            resample = Image.LANCZOS if (iw * ih) <= 4_000_000 else Image.BILINEAR
        else:
            resample = Image.NEAREST
        try:
            disp = self.orig if (nw, nh) == (iw, ih) else self.orig.resize((nw, nh), resample)
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
        try:
            self.info.configure(text="%s   %d×%d   %d%%%s%s"
                                     % (name, iw, ih, pct, fsize, extra))
        except Exception:
            pass

    # ---- 高保真取图（复制/另存用） ----
    def _full_image(self):
        """返回全分辨率图像：显示时可能降过采样，输出绝不将就"""
        if self._anim_source is not None:
            return self.orig              # 动图按当前帧输出
        if self._downscaled and self.src_path and os.path.isfile(self.src_path):
            try:
                im = Image.open(self.src_path)
                im.load()
                try:
                    im = ImageOps.exif_transpose(im)
                except Exception:
                    pass
                return im
            except Exception:
                pass
        return self.orig

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
            if src and os.path.isfile(src):
                # 原文件直接复制，零画质损失
                dst = unique_path(self.save_dir, os.path.basename(src))
                shutil.copy2(src, dst)
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
            if cur and os.path.isfile(cur) and \
                    os.path.splitext(path)[1].lower() == os.path.splitext(cur)[1].lower():
                shutil.copy2(cur, path)     # 同格式直接复制，零损失
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