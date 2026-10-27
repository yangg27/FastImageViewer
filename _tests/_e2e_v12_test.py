# -*- coding: utf-8 -*-
"""
v1.2.0 真实 exe 端到端测试 —— 旋转功能

=== 为什么这个测试要这么写（踩坑记录，勿改）===

坑 1：`keybd_event` / `SendInput` 注入字母键时，Tk 无法正确解析。
    实测日志：`keysym=?? keycode=229 char=''`，命不中 `<r>` 绑定。
    这是 Tk 在 Windows 上的既定行为（注入键没有伴随正确的键盘布局翻译），
    不代表程序有 bug —— 真实键盘输入完全正常。
    解法：用 `SendMessageW` 直接投递 `WM_KEYDOWN` + `WM_CHAR` 到窗口句柄，
    实测能 100% 命中 Tk 的 `<r>` 绑定（`char='r'`）。

坑 2：窗口没真正拿到前台焦点时，按键会发给别的窗口。
    解法：`AttachThreadInput` 把自己的线程输入队列挂到目标窗口线程上，
    再 `SetForegroundWindow` / `SetFocus` 才能突破 Windows 前台锁定。

坑 3：不能用程序内部状态自证（那是循环论证）。
    解法：截图看像素。造一张四角异色的竖图，
    顺时针 90° 后红块应从【左上】跑到【右上】，逆时针则到【左下】。
    这样才能真正验证「方向对不对」。
"""
import os
import sys
import time
import ctypes
import subprocess
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "FastImageViewer", "FastImageViewer.exe")
TMP = os.path.join(HERE, "_v12_tmp")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetFocus.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WM_KEYDOWN = 0x0100
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104

# ---- SendInput（仅用于真实按下修饰键，让 Tk 的 state 正确）----
class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _IU(ctypes.Union):
    _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", _IU)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

VK_SHIFT = 0x10
VK_CTRL = 0x11
MOD_SHIFT = 1 << 29
MOD_CTRL = 2 << 29

PASS, FAIL, FAILS = 0, 0, []


def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s  %s" % (name, detail))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  %s" % (name, detail))


def title_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _enum_cb(hwnd, lp):
    t = title_of(hwnd)
    if t and "极速看图" in t and user32.IsWindowVisible(hwnd):
        _enum_cb.found.append(hwnd)
    return True


def find_win(timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        _enum_cb.found = []
        user32.EnumWindows(_enum_cb, 0)
        if _enum_cb.found:
            return _enum_cb.found[0]
        time.sleep(0.25)
    return None


def force_foreground(hwnd):
    """绕过 Windows 前台锁定，真正把目标窗口推到前台并拿到键盘焦点"""
    fg = user32.GetForegroundWindow()
    tid_self = kernel32.GetCurrentThreadId()
    tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tid_tgt = user32.GetWindowThreadProcessId(hwnd, None)

    attached = []
    for tid in (tid_fg, tid_tgt):
        if tid and tid != tid_self:
            if user32.AttachThreadInput(tid_self, tid, True):
                attached.append(tid)
    try:
        user32.ShowWindow(hwnd, 9)      # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        time.sleep(0.25)
    finally:
        for tid in attached:
            user32.AttachThreadInput(tid_self, tid, False)
    return user32.GetForegroundWindow() == hwnd


def _send_input(seq):
    """seq = [(vk, scan, flags), ...]，flags: 0=按下, 2=抬起"""
    arr = (_INPUT * len(seq))()
    for i, (v, s, f) in enumerate(seq):
        arr[i].type = 1
        arr[i].ii.ki.wVk = v
        arr[i].ii.ki.wScan = s
        arr[i].ii.ki.dwFlags = f
        arr[i].ii.ki.time = 0
        arr[i].ii.ki.dwExtraInfo = None
    return user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT))


def send_key(hwnd, ch, shift=False, ctrl=False):
    """
    投递一个字符键，可带修饰键。

    为什么这么绕（两段式）：
      1. 字母键本身必须走 `SendMessageW(WM_CHAR)` —— `keybd_event`/`SendInput`
         注入的字母键会被 Tk 解析成 `keysym=?? keycode=229`，命不中 `<r>` 绑定。
      2. 修饰键必须走 `SendInput` **真实按下** —— 只有真实按下，
         Tk 才会把 `state` 置上 Shift(1)/Control(4) 对应位；
         单纯发一个 WM_KEYDOWN(Shift) 不会改变 Tk 的 state，
         `<Shift-R>` / `<Control-r>` 就命不中。
      实测：这种方式 `Shift-R` 与 `Control-r` 均 100% 命中。
    """
    vk = ord(ch.upper())
    scan = user32.MapVirtualKeyW(vk, 0)
    mod = (MOD_SHIFT if shift else 0) | (MOD_CTRL if ctrl else 0)

    # 1) 真实按下修饰键
    if shift:
        _send_input([(VK_SHIFT, 0, 0)])
    if ctrl:
        _send_input([(VK_CTRL, 0, 0)])
    time.sleep(0.12)

    lp = 1 | (scan << 16) | mod
    try:
        # 2) 投递字符键
        user32.SendMessageW(hwnd, WM_KEYDOWN, vk, lp)
        if ctrl:
            user32.SendMessageW(hwnd, WM_CHAR, vk & 0x1F, lp)   # Ctrl+R → 0x12
        elif shift:
            user32.SendMessageW(hwnd, WM_CHAR, ord(ch.upper()), lp)
        else:
            user32.SendMessageW(hwnd, WM_CHAR, ord(ch.lower()), lp)
        time.sleep(0.1)
    finally:
        # 3) 抬起修饰键
        if ctrl:
            _send_input([(VK_CTRL, 0, 2)])
        if shift:
            _send_input([(VK_SHIFT, 0, 2)])

    time.sleep(0.5)


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"],
                   capture_output=True, shell=False)
    time.sleep(0.8)


def make_probe(path):
    """四角异色竖图：左上红、右上绿、左下蓝、右下黄"""
    from PIL import Image
    im = Image.new("RGB", (300, 600), (250, 250, 250))
    d = im.load()
    for y in range(0, 150):
        for x in range(0, 150):
            d[x, y] = (230, 30, 30)      # 左上 红
    for y in range(0, 150):
        for x in range(150, 300):
            d[x, y] = (30, 200, 50)      # 右上 绿
    for y in range(450, 600):
        for x in range(0, 150):
            d[x, y] = (30, 60, 230)      # 左下 蓝
    for y in range(450, 600):
        for x in range(150, 300):
            d[x, y] = (250, 220, 30)     # 右下 黄
    im.save(path)


def shoot(hwnd):
    from PIL import ImageGrab
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    time.sleep(0.55)
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))


def find_color(img, rgb, tol=55):
    w, h = img.size
    px = img.load()
    tr, tg, tb = rgb
    sx = sy = n = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            p = px[x, y]
            if abs(p[0] - tr) < tol and abs(p[1] - tg) < tol and abs(p[2] - tb) < tol:
                sx += x
                sy += y
                n += 1
    if n == 0:
        return None
    return (sx / n / w, sy / n / h, n)


def quadrant(pt):
    if pt is None:
        return "未找到"
    return ("左" if pt[0] < 0.5 else "右") + ("上" if pt[1] < 0.5 else "下")


RED = (230, 30, 30)
BLUE = (30, 60, 230)


def ps_mem(name):
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO", "CSV", "/NH"],
                           capture_output=True)
        out = r.stdout.decode("gbk", "replace")
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 5 and parts[0].lower() == name.lower():
                return float(parts[4].replace(",", "").replace(" K", "").strip()) / 1024.0
    except Exception:
        pass
    return 0.0


def main():
    print("=" * 74)
    print("  v1.2.0 真实 exe 端到端 —— 旋转功能（截图像素级方向验证）")
    print("=" * 74)

    if not os.path.isfile(EXE):
        print("[×] 未找到 exe: %s" % EXE)
        return 1
    print("  exe: %s\n" % EXE)

    os.makedirs(TMP, exist_ok=True)
    img_path = os.path.join(TMP, "rotate_probe.png")
    make_probe(img_path)
    print("  测试图: 300x600 竖图（左上红/右上绿/左下蓝/右下黄）")
    print("  预期：顺时针 90° → 红块【左上】→【右上】")
    print("       逆时针 90° → 红块【左上】→【左下】\n")

    kill_all()

    # ---------- [1] 真实双击唤起 ----------
    print("[1] 真实双击唤起（ShellExecuteW）")
    t0 = time.time()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", EXE, '"%s"' % img_path, None, 1)
    chk("ShellExecuteW 调用成功", rc > 32, "rc=%d" % rc)

    hwnd = find_win(20.0)
    if hwnd is None:
        chk("窗口出现", False, "超时未找到标题含「极速看图」的窗口")
        kill_all()
        return 1
    chk("窗口出现", True, "%d ms" % int((time.time() - t0) * 1000))

    ok_fg = force_foreground(hwnd)
    chk("夺得前台焦点", ok_fg, "foreground=%s" % user32.GetForegroundWindow())

    loaded = False
    end = time.time() + 15
    while time.time() < end:
        if "rotate_probe" in title_of(hwnd):
            loaded = True
            break
        time.sleep(0.15)
    chk("图片加载完成", loaded, title_of(hwnd))

    # ---------- [2] 旋转前基准 ----------
    print("\n[2] 旋转前基准（红应在左上、蓝在左下）")
    s0 = shoot(hwnd)
    print("      截图 %dx%d" % s0.size)
    red0 = find_color(s0, RED)
    blue0 = find_color(s0, BLUE)
    chk("截图识别到红块", red0 is not None,
        "象限=%s 像素=%d 质心=(%.2f,%.2f)" % (quadrant(red0), red0[2] if red0 else 0,
                                              red0[0] if red0 else -1, red0[1] if red0 else -1))
    chk("红块在【左上】", quadrant(red0) == "左上", "实际=%s" % quadrant(red0))
    chk("蓝块在【左下】", quadrant(blue0) == "左下", "实际=%s" % quadrant(blue0))

    # ---------- [3] R 右转 90 ----------
    print("\n[3] 按 R → 顺时针 90°")
    send_key(hwnd, "r")
    s1 = shoot(hwnd)
    red1 = find_color(s1, RED)
    blue1 = find_color(s1, BLUE)
    chk("红块转到【右上】", quadrant(red1) == "右上",
        "实际=%s 质心=(%.2f,%.2f)" % (quadrant(red1), red1[0] if red1 else -1, red1[1] if red1 else -1))
    chk("蓝块转到【左上】", quadrant(blue1) == "左上", "实际=%s" % quadrant(blue1))
    chk("方向确为顺时针", quadrant(red1) == "右上",
        "若逆时针红块会到左下，实际=%s" % quadrant(red1))

    # ---------- [4] 再转 90 → 180 ----------
    print("\n[4] 再按 R → 180°（红应在右下）")
    send_key(hwnd, "r")
    s2 = shoot(hwnd)
    red2 = find_color(s2, RED)
    chk("180° 红块在【右下】", quadrant(red2) == "右下", "实际=%s" % quadrant(red2))

    # ---------- [5] 再转 90 → 270 ----------
    print("\n[5] 再按 R → 270°（红应在左下）")
    send_key(hwnd, "r")
    s3 = shoot(hwnd)
    red3 = find_color(s3, RED)
    chk("270° 红块在【左下】", quadrant(red3) == "左下", "实际=%s" % quadrant(red3))

    # ---------- [6] 第 4 转回 0 ----------
    print("\n[6] 再按 R → 360° 回原始方向")
    send_key(hwnd, "r")
    s4 = shoot(hwnd)
    red4 = find_color(s4, RED)
    chk("回到 0° 红块在【左上】", quadrant(red4) == "左上", "实际=%s" % quadrant(red4))

    # ---------- [7] Shift+R 逆时针 ----------
    print("\n[7] Shift+R → 逆时针 90°（红应在左下）")
    send_key(hwnd, "r", shift=True)
    s5 = shoot(hwnd)
    red5 = find_color(s5, RED)
    chk("逆时针红块在【左下】", quadrant(red5) == "左下", "实际=%s" % quadrant(red5))

    # ---------- [8] Ctrl+R 复位 ----------
    print("\n[8] Ctrl+R 复位")
    send_key(hwnd, "r", ctrl=True)
    s6 = shoot(hwnd)
    red6 = find_color(s6, RED)
    chk("复位后红块回【左上】", quadrant(red6) == "左上", "实际=%s" % quadrant(red6))

    # ---------- [9] 存活与内存 ----------
    print("\n[9] 旋转后存活与内存")
    chk("窗口仍存在", bool(user32.IsWindow(hwnd)), "hwnd=%s" % hwnd)
    t_end = title_of(hwnd)
    chk("标题仍可读（未崩溃）", "rotate_probe" in t_end, t_end)
    mem = ps_mem("FastImageViewer.exe")
    chk("内存 <150MB", 0 < mem < 150, "%.0f MB" % mem)

    try:
        s2.save(os.path.join(TMP, "state_180.png"))
        s5.save(os.path.join(TMP, "state_ccw.png"))
        s6.save(os.path.join(TMP, "state_final.png"))
    except Exception:
        pass

    kill_all()

    print("\n" + "=" * 74)
    print("  结果：通过 %d 项 / 失败 %d 项" % (PASS, FAIL))
    if FAILS:
        print("  失败项：%s" % ", ".join(FAILS))
        print("=" * 74)
        return 1
    print("  结论：全部通过 ✔（方向经截图像素验证，顺时针/逆时针均正确）")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())