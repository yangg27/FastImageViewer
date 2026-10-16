# -*- coding: utf-8 -*-
"""干净验证：确保 UserChoice 已清空 -> 双击图片 -> 确认弹出的就是极速看图"""
import os, sys, time, ctypes, tempfile, subprocess, winreg, shutil
from ctypes import wintypes
from PIL import Image

user32 = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EXTS = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"]


def find_window(needle="极速看图"):
    r = []
    def cb(h, l):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, b, n + 1)
        if needle in b.value:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r.append((h, b.value, pid.value))
            return False
        return True
    user32.EnumWindows(Proc(cb), 0)
    return r[0] if r else None


def uc_progid(e):
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % e)
        v = winreg.QueryValueEx(k, "ProgId")[0]
        winreg.CloseKey(k)
        return v
    except Exception:
        return None


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"], capture_output=True)
    time.sleep(0.7)


# ---------- 步骤 1：清空 UserChoice（多轮，防止竞争重建） ----------
print("=" * 66)
print(" 步骤1  清空 UserChoice 锁定")
print("=" * 66)
for rnd in range(4):
    for e in EXTS:
        p = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % e
        for attempt in range(2):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
                break
            except Exception:
                pass
    remain = {e: uc_progid(e) for e in EXTS if uc_progid(e)}
    print("  第%d轮后残留: %s" % (rnd + 1, remain if remain else "无"))
    if not remain:
        break
    time.sleep(0.4)

# ---------- 步骤 2：逐个扩展名真实双击 ----------
print()
print("=" * 66)
print(" 步骤2  真实双击各类图片（走系统关联链）")
print("=" * 66)
TMP = tempfile.mkdtemp(prefix="fiv_final_")
kinds = [
    ("jpg", lambda p: Image.new("RGB", (2400, 1600), (200, 80, 40)).save(p, quality=88)),
    ("png", lambda p: Image.new("RGB", (1600, 1200), (40, 160, 90)).save(p)),
    ("gif", lambda p: Image.new("RGB", (640, 480), (90, 90, 220)).save(p)),
    ("webp", lambda p: Image.new("RGB", (1280, 960), (220, 180, 40)).save(p)),
    ("bmp", lambda p: Image.new("RGB", (800, 600), (150, 60, 160)).save(p)),
    ("ico", lambda p: Image.new("RGBA", (256, 256), (30, 30, 30, 255)).save(
        p, sizes=[(256, 256)])),
]

pass_n, fail_n = 0, 0
for ext, maker in kinds:
    f = os.path.join(TMP, "sample_test." + ext)
    try:
        maker(f)
    except Exception as ex:
        print("  .%-5s 造图失败: %s" % (ext, ex))
        continue
    kill_all()
    t0 = time.perf_counter()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", f, None, None, 1)
    win = None
    while time.perf_counter() - t0 < 15:
        win = find_window()
        if win:
            break
        time.sleep(0.02)
    dt = (time.perf_counter() - t0) * 1000
    if win:
        pass_n += 1
        title_ok = os.path.basename(f) in win[1]
        print("  .%-5s ✔ %.0f ms  标题=%s %s" % (
            ext, dt, win[1], "(参数正确)" if title_ok else "(参数异常)"))
    else:
        fail_n += 1
        print("  .%-5s × 未启动极速看图 (ShellExecute rc=%d)" % (ext, rc))

print()
print("=" * 66)
print(" 结果: %d 成功 / %d 失败" % (pass_n, fail_n))
print("=" * 66)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if fail_n == 0 else 1)