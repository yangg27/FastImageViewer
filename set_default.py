# -*- coding: utf-8 -*-
"""
极速看图 - 设为默认图片打开方式
--------------------------------------------------------
说明：Windows 10/11 从 2024 年起引入了 UCPD 内核驱动，禁止任何程序静默
      修改"默认应用"（防止软件互相劫持）。因此本脚本采取两步：

      第 1 步：尽力自动设置（对无竞争、未被保护的格式通常直接生效）
      第 2 步：若被系统拦截，自动打开 Windows 设置页，按屏幕提示点两下即可

      这一步只需做一次，之后永久生效。
"""
import os
import sys
import ctypes
import winreg
import time
from ctypes import wintypes

APP = "FastImageViewer"
DISPLAY = "极速看图"
EXTS = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"]
PROGID = {
    "jpg": "FastImageViewer.jpg", "jpeg": "FastImageViewer.jpg",
    "png": "FastImageViewer.png", "gif": "FastImageViewer.gif",
    "bmp": "FastImageViewer.bmp", "webp": "FastImageViewer.webp",
    "tiff": "FastImageViewer.tiff", "tif": "FastImageViewer.tiff",
    "ico": "FastImageViewer.ico",
}

_shlwapi = ctypes.windll.shlwapi
_shlwapi.AssocQueryStringW.argtypes = [
    wintypes.DWORD, ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_shlwapi.AssocQueryStringW.restype = ctypes.c_long


def effective_app(ext):
    """问系统：这个扩展名现在实际会用哪个程序打开"""
    buf = ctypes.create_unicode_buffer(2048)
    size = wintypes.DWORD(2048)
    try:
        hr = _shlwapi.AssocQueryStringW(0, 2, "." + ext, "open", buf, ctypes.byref(size))
        return buf.value if hr == 0 else None
    except Exception:
        return None


def is_ours(path):
    return bool(path) and APP.lower() in path.lower()


def clear_userchoice(ext):
    p = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % ext
    for _ in range(2):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
            return True
        except FileNotFoundError:
            return True
        except Exception:
            time.sleep(0.05)
    return False


def write_classes_default(ext):
    try:
        k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                               r"Software\Classes\.%s" % ext, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, PROGID[ext])
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def notify_shell():
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def open_settings():
    """打开 Windows「默认应用」设置页"""
    for target in ("ms-settings:defaultapps",):
        try:
            os.startfile(target)
            return True
        except Exception:
            pass
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "open", "ms-settings:defaultapps",
                                            None, None, 1)
        return True
    except Exception:
        return False


def main():
    print("=" * 64)
    print("  %s  —  设为默认图片打开方式" % DISPLAY)
    print("=" * 64)

    if not any(is_ours(effective_app(e)) for e in EXTS):
        exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", APP, APP + ".exe")
        if not os.path.isfile(exe):
            print("\n[×] 未检测到已安装的程序，请先运行 install.py")
            input("\n按回车退出...")
            return 1

    print("\n[1/2] 尝试自动设置...")
    ok, bad = [], []
    for e in EXTS:
        if is_ours(effective_app(e)):
            ok.append(e)
            continue
        clear_userchoice(e)
        write_classes_default(e)
        time.sleep(0.15)
        if is_ours(effective_app(e)):
            ok.append(e)
        else:
            bad.append(e)

    notify_shell()
    time.sleep(0.5)

    # 再确认一次（系统可能已经重建 UserChoice）
    still_bad = [e for e in bad if not is_ours(effective_app(e))]
    print("      成功: %s" % (", ".join("." + x for x in ok) if ok else "无"))

    if not still_bad:
        print("\n[2/2] 全部完成 ✔")
        print("-" * 64)
        print("  现在双击任意图片都会用「%s」打开。" % DISPLAY)
        print("=" * 64)
        input("\n按回车退出...")
        return 0

    print("      需手动: %s" % ", ".join("." + x for x in still_bad))
    print()
    print("=" * 64)
    print("  [2/2] 系统拦截了自动设置（Windows 默认应用保护机制）")
    print("=" * 64)
    print()
    print("  这是微软的安全设计，不是程序问题。请按以下步骤点两下，")
    print("  整个过程约 20 秒，只需做一次：")
    print()
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │ ① 即将打开「默认应用」设置页                        │")
    print("  │ ② 在搜索框输入： 极速看图                            │")
    print("  │ ③ 点击搜到的「极速看图」条目                         │")
    print("  │ ④ 点击顶部的「设置默认值」按钮                       │")
    print("  │ ⑤ 完成！所有图片格式一次性全部设为默认               │")
    print("  └─────────────────────────────────────────────────────┘")
    print()
    print("  若列表里找不到「极速看图」，可改用逐个设置：")
    print("     设置页 -> 搜索「.jpg」-> 点当前程序 -> 选「极速看图」")
    print()
    try:
        input("  按回车打开设置页，或输入 n 跳过: ").strip().lower()
    except EOFError:
        pass
    else:
        open_settings()
    print()
    print("  提示：也可以右键任意图片 -> 打开方式 -> 选择其他应用")
    print("        -> 选「极速看图」-> 勾选「始终」-> 确定")
    return 0


if __name__ == "__main__":
    sys.exit(main())