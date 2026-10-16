# -*- coding: utf-8 -*-
"""清理残留进程与窗口，再验证双击唤起"""
import os, sys, time, ctypes, tempfile, subprocess, shutil
from ctypes import wintypes

HERE = r"C:/Users/Administrator/WorkBuddy/2026-10-16-15-00-18/ImageViewer"
sys.path.insert(0, os.path.join(HERE, ".venv-build", "Lib", "site-packages"))
from PIL import Image

u = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_viewer_windows():
    r = []
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        if "极速看图" in b.value:
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            r.append((h, b.value, pid.value))
        return True
    u.EnumWindows(Proc(cb), 0)
    return r


def kill_viewer_only():
    """只杀 FastImageViewer，绝不碰 python（避免自杀）"""
    for _ in range(3):
        subprocess.run(["taskkill", "/F", "/IM", "FastImageViewer.exe"],
                       capture_output=True)
        time.sleep(0.8)
        if not list_viewer_windows():
            return True
    return not list_viewer_windows()


print("=" * 66)
print(" 清理残留窗口")
print("=" * 66)
before = list_viewer_windows()
print("  清理前: %d 个窗口" % len(before))
ok_clean = kill_viewer_only()
after = list_viewer_windows()
print("  清理后: %d 个窗口 %s" % (len(after), "✔" if not after else "✗ 仍有残留"))
if after:
    for h, t, pid in after:
        try:
            # 按 HWND 直接关闭
            u.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass
    time.sleep(1.5)
    after = list_viewer_windows()
    print("  二次清理后: %d 个窗口" % len(after))

# ---- 双击唤起验证 ----
print()
print("=" * 66)
print(" 双击唤起验证（新版已部署）")
print("=" * 66)

TMP = tempfile.mkdtemp(prefix="fiv_dbl_")
tests = [
    ("webp", lambda p: Image.new("RGB", (1920, 1080), (90, 170, 60)).save(p)),
    ("tiff", lambda p: Image.new("RGB", (1600, 1200), (150, 60, 160)).save(p)),
    ("bmp", lambda p: Image.new("RGB", (1280, 960), (60, 140, 200)).save(p)),
]

okn = 0
for ext, maker in tests:
    p = os.path.join(TMP, "dbltest." + ext)
    try:
        maker(p)
    except Exception as e:
        print("  .%-5s 造图失败 %s" % (ext, e))
        continue
    kill_viewer_only()
    t0 = time.perf_counter()
    ctypes.windll.shell32.ShellExecuteW(None, "open", p, None, None, 1)
    basename = os.path.basename(p)
    win = None
    dt = 0
    # 等窗口出现（标题先为"极速看图"，加载完图片后才更新为"文件名 - 极速看图"）
    while time.perf_counter() - t0 < 15:
        ws = list_viewer_windows()
        if ws:
            win = ws[0]
            break
        time.sleep(0.01)
    if win:
        dt = (time.perf_counter() - t0) * 1000
        # 再等标题带上文件名，确认参数传递正确
        t1 = time.perf_counter()
        while time.perf_counter() - t1 < 10:
            ws = list_viewer_windows()
            if ws and basename in ws[0][1]:
                win = ws[0]
                break
            time.sleep(0.02)
        good = basename in win[1]
        okn += 1
        print("  .%-5s 唤起 %5.0f ms  标题=%-32s %s"
              % (ext, dt, win[1], "文件参数正确" if good else "参数未传入"))
    else:
        print("  .%-5s 未唤起（该格式需手动设默认）" % ext)

kill_viewer_only()
print("\n  成功 %d/%d" % (okn, len(tests)))
shutil.rmtree(TMP, ignore_errors=True)