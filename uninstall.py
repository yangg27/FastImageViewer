# -*- coding: utf-8 -*-
"""
极速看图 FastImageViewer - 卸载脚本
作用：恢复安装前的图片默认关联，删除程序文件
用法：双击运行，或 python uninstall.py
"""
import os
import sys
import json
import shutil
import ctypes
import winreg

APP_NAME = "FastImageViewer"
DISPLAY_NAME = "极速看图"
EXTS = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"]
PROGIDS = ["FastImageViewer.jpg", "FastImageViewer.png", "FastImageViewer.gif",
           "FastImageViewer.bmp", "FastImageViewer.webp", "FastImageViewer.tiff",
           "FastImageViewer.ico"]

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
TARGET_DIR = os.path.join(LOCALAPPDATA, "Programs", APP_NAME)


def del_tree(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                del_tree(root, path + "\\" + sub)
        winreg.DeleteKey(root, path)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def notify_shell():
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def main():
    print("=" * 62)
    print("  %s 卸载程序" % DISPLAY_NAME)
    print("=" * 62)

    # ---------- 1. 读取备份并恢复 ----------
    bak = os.path.join(TARGET_DIR, "backup", "assoc_backup.json")
    restored = 0
    if os.path.isfile(bak):
        try:
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
            for ext, rec in (data.get("exts") or {}).items():
                prev = rec.get("classes_default")
                if not prev or str(prev).startswith("FastImageViewer"):
                    continue
                try:
                    k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                           r"Software\Classes\%s" % ext, 0, winreg.KEY_WRITE)
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, prev)
                    winreg.CloseKey(k)
                    restored += 1
                except Exception:
                    pass
            print("[1/3] 已恢复 %d 个扩展名的原默认程序" % restored)
        except Exception as ex:
            print("[1/3] 读取备份失败: %s" % ex)
    else:
        print("[1/3] 未找到备份文件，跳过关联恢复")

    # ---------- 2. 清理本软件注册表项 ----------
    n = 0
    for pid in PROGIDS:
        if del_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s" % pid):
            n += 1
    for key in [r"Software\Classes\Applications\%s.exe" % APP_NAME,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s.exe" % APP_NAME]:
        del_tree(winreg.HKEY_CURRENT_USER, key)

    # 清扩展名里指向本软件的值
    for e in EXTS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s" % e) as k:
                cur = winreg.QueryValueEx(k, "")[0]
            if str(cur).startswith("FastImageViewer"):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s" % e)
        except Exception:
            pass
        del_tree(winreg.HKEY_CURRENT_USER,
                 r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % e)

    notify_shell()
    print("[2/3] 注册表项已清理 (%d 个 ProgID)" % n)

    # ---------- 3. 删除程序目录 ----------
    if os.path.isdir(TARGET_DIR):
        try:
            shutil.rmtree(TARGET_DIR, ignore_errors=True)
            print("[3/3] 程序目录已删除: %s" % TARGET_DIR)
        except Exception as ex:
            print("[3/3] 删除失败（可能程序正在运行）: %s" % ex)
    else:
        print("[3/3] 程序目录不存在，无需删除")

    print("-" * 62)
    print("  卸载完成。图片将回退到系统原默认程序。")
    print("  配置与保存的图片保留在: %s\\Pictures\\ImageViewer" % os.path.expanduser("~"))
    input("\n按回车退出...")
    return 0


if __name__ == "__main__":
    sys.exit(main())