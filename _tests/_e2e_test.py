# -*- coding: utf-8 -*-
"""真实端到端：模拟双击图片 -> 走系统关联 -> 验证启动的是极速看图"""
import os, sys, time, ctypes, tempfile, subprocess, winreg
from ctypes import wintypes
from PIL import Image

user32 = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_viewer_window():
    r = []
    def cb(h, l):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, b, n + 1)
        if "极速看图" in b.value:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r.append((h, b.value, pid.value))
            return False
        return True
    user32.EnumWindows(Proc(cb), 0)
    return r[0] if r else None


def resolve_progid(ext):
    """模拟：系统如何解析这个扩展名"""
    # 1) UserChoice 优先
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % ext)
        v = winreg.QueryValueEx(k, "ProgId")[0]
        winreg.CloseKey(k)
        return v, "UserChoice"
    except Exception:
        pass
    # 2) HKCU Classes 默认值
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s" % ext)
        v = winreg.QueryValueEx(k, "")[0]
        winreg.CloseKey(k)
        if v:
            return v, "Classes默认值"
    except Exception:
        pass
    return None, "未解析"


def get_open_command(progid):
    for hive, path in [
        (winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\shell\open\command" % progid),
        (winreg.HKEY_CLASSES_ROOT, r"%s\shell\open\command" % progid),
    ]:
        try:
            k = winreg.OpenKey(hive, path)
            v = winreg.QueryValueEx(k, "")[0]
            winreg.CloseKey(k)
            return v
        except Exception:
            pass
    return None


print("=" * 66)
print(" 1. 系统关联解析链验证")
print("=" * 66)
EXTS = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"]
all_ok = True
for e in EXTS:
    pid, how = resolve_progid(e)
    cmd = get_open_command(pid) if pid else None
    good = bool(pid and pid.startswith("FastImageViewer") and cmd and "FastImageViewer" in cmd)
    if not good:
        all_ok = False
    print("  .%-5s -> %-22s [%s]  %s" % (
        e, pid or "(空)", how,
        "OK" if good else "→ 命令: %s" % (cmd or "无")))

print()
print("=" * 66)
print(" 2. 真实双击模拟（ShellExecute 走系统关联）")
print("=" * 66)
TMP = tempfile.mkdtemp(prefix="fiv_e2e_")
img = os.path.join(TMP, "双击测试.png")
Image.new("RGB", (1920, 1080), (220, 120, 40)).save(img)
print("  测试图片: %s" % img)

# 关闭已有实例避免误判
subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"], capture_output=True)
time.sleep(0.8)

t0 = time.perf_counter()
rc = ctypes.windll.shell32.ShellExecuteW(None, "open", img, None, None, 1)
print("  ShellExecute 返回码: %d (>32 表示成功)" % rc)
win = None
while time.perf_counter() - t0 < 20:
    win = find_viewer_window()
    if win:
        break
    time.sleep(0.02)
dt = (time.perf_counter() - t0) * 1000

if win:
    print("  ✔ 窗口已出现，耗时 %.0f ms  标题: %s" % (dt, win[1]))
    # 读窗口标题里的文件名确认传参正确
    if "双击测试" in win[1]:
        print("  ✔ 文件参数传递正确（标题含文件名）")
    else:
        print("  ! 标题未包含文件名: %s" % win[1])
    print()
    print("=" * 66)
    print("  最终结果: 双击图片 -> 极速看图启动成功，耗时 %.0f ms" % dt)
    print("=" * 66)
    subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"], capture_output=True)
else:
    print("  × 20s 内未启动极速看图窗口")

import shutil
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if (all_ok and win) else 1)