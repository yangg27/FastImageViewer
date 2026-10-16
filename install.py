# -*- coding: utf-8 -*-
"""
极速看图 FastImageViewer - 安装脚本
作用：把程序复制到本机目录，并注册为图片文件默认打开方式
范围：仅当前用户 (HKCU)，不需要管理员权限，可完整卸载
用法：双击运行，或 python install.py
"""
import os
import sys
import json
import shutil
import ctypes
import winreg
import datetime

APP_NAME = "FastImageViewer"
DISPLAY_NAME = "极速看图"
EXTS = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"]
# tif/ico 用同一 ProgID 家族，避免注册表项过多
PROGID_OF = {
    "jpg": "FastImageViewer.jpg", "jpeg": "FastImageViewer.jpg",
    "png": "FastImageViewer.png",
    "gif": "FastImageViewer.gif",
    "bmp": "FastImageViewer.bmp",
    "webp": "FastImageViewer.webp",
    "tiff": "FastImageViewer.tiff", "tif": "FastImageViewer.tiff",
    "ico": "FastImageViewer.ico",
}
DESC_OF = {
    "FastImageViewer.jpg": "图片文件 (极速看图)",
    "FastImageViewer.png": "图片文件 (极速看图)",
    "FastImageViewer.gif": "动图文件 (极速看图)",
    "FastImageViewer.bmp": "图片文件 (极速看图)",
    "FastImageViewer.webp": "图片文件 (极速看图)",
    "FastImageViewer.tiff": "图片文件 (极速看图)",
    "FastImageViewer.ico": "图标文件 (极速看图)",
}

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
TARGET_DIR = os.path.join(LOCALAPPDATA, "Programs", APP_NAME)
TARGET_EXE = os.path.join(TARGET_DIR, APP_NAME + ".exe")


def find_source():
    """在本脚本同目录或上级找到打包好的程序目录"""
    cands = [
        os.path.join(HERE, "dist", APP_NAME),
        os.path.join(os.path.dirname(HERE), "dist", APP_NAME),
        os.path.join(HERE, APP_NAME),
    ]
    for c in cands:
        if os.path.isfile(os.path.join(c, APP_NAME + ".exe")):
            return c
    return None


def set_key(root, path, values):
    k = winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE)
    try:
        for name, val in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    finally:
        winreg.CloseKey(k)


def del_tree(root, path):
    try:
        winreg.DeleteKeyEx(root, path, 0, winreg.KEY_WOW64_64KEY)
        return True
    except Exception:
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
        except Exception:
            return False


def notify_shell():
    """通知资源管理器刷新图标与关联"""
    try:
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def get_existing_userchoice(ext):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % ext) as k:
            return winreg.QueryValueEx(k, "ProgId")[0]
    except Exception:
        return None


def get_existing_classes(ext):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s" % ext) as k:
            return winreg.QueryValueEx(k, "")[0]
    except Exception:
        return None


def main():
    print("=" * 62)
    print("  %s 安装程序" % DISPLAY_NAME)
    print("=" * 62)

    src = find_source()
    if not src:
        print("\n[×] 找不到程序文件。")
        print("    请确认 dist\\%s\\%s.exe 存在，并把本脚本放在解压后的根目录。" % (APP_NAME, APP_NAME))
        input("\n按回车退出...")
        return 1

    # ---------- 1. 备份现有默认关联 ----------
    backup = {"backup_time": datetime.datetime.now().isoformat(), "exts": {}}
    for e in EXTS:
        backup["exts"]["." + e] = {
            "userchoice_progid": get_existing_userchoice(e),
            "classes_default": get_existing_classes(e),
        }
    bak_dir = os.path.join(TARGET_DIR, "backup")
    try:
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "assoc_backup.json"), "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
        print("\n[1/4] 已备份现有图片关联 -> %s" % os.path.join(bak_dir, "assoc_backup.json"))
    except Exception as ex:
        print("\n[1/4] 备份关联失败（不阻塞安装）: %s" % ex)

    # ---------- 2. 复制程序 ----------
    try:
        if os.path.isdir(TARGET_DIR):
            shutil.rmtree(TARGET_DIR, ignore_errors=True)
        shutil.copytree(src, TARGET_DIR, dirs_exist_ok=True)
        print("[2/4] 程序已安装到: %s" % TARGET_DIR)
    except Exception as ex:
        print("[×] 复制程序失败: %s" % ex)
        input("\n按回车退出...")
        return 1

    if not os.path.isfile(TARGET_EXE):
        print("[×] 未找到 %s" % TARGET_EXE)
        input("\n按回车退出...")
        return 1

    # ---------- 3. 写注册表 ----------
    icon = "%s,0" % TARGET_EXE
    cmd = '"%s" "%%1"' % TARGET_EXE

    # 3a. Applications 注册（出现在"打开方式"列表）
    app_key = r"Software\Classes\Applications\%s.exe" % APP_NAME
    set_key(winreg.HKEY_CURRENT_USER, app_key, {
        "FriendlyAppName": DISPLAY_NAME, "ApplicationIcon": icon})
    set_key(winreg.HKEY_CURRENT_USER, app_key + r"\shell\open\command", {"": cmd})
    set_key(winreg.HKEY_CURRENT_USER, app_key + r"\DefaultIcon", {"": icon})
    st = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                            app_key + r"\SupportedTypes", 0, winreg.KEY_WRITE)
    for e in EXTS:
        winreg.SetValueEx(st, "." + e, 0, winreg.REG_SZ, "")
    winreg.CloseKey(st)

    # 3b. 各 ProgID
    for pid, desc in DESC_OF.items():
        set_key(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s" % pid, {"": desc})
        set_key(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\DefaultIcon" % pid, {"": icon})
        set_key(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\shell\open\command" % pid, {"": cmd})

    # 3c. 扩展名默认值 + OpenWithProgids
    for e in EXTS:
        pid = PROGID_OF[e]
        set_key(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s" % e, {"": pid})
        set_key(winreg.HKEY_CURRENT_USER, r"Software\Classes\.%s\OpenWithProgids" % e, {pid: ""})
        set_key(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\OpenWithProgids" % e,
                {pid: ""})

    # 3d. App Paths（Win+R 可直达）
    set_key(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s.exe" % APP_NAME,
            {"": TARGET_EXE, "Path": TARGET_DIR})

    # 3e. 清除 UserChoice（关键：不删它，上面的默认值不生效）
    cleared = 0
    for e in EXTS:
        if del_tree(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.%s\UserChoice" % e):
            cleared += 1
    print("[3/4] 注册表已写入，清除旧默认锁定 %d/%d 项" % (cleared, len(EXTS)))

    notify_shell()

    # ---------- 4. 结果 ----------
    print("[4/4] 完成")
    print("-" * 62)
    print("  程序位置 : %s" % TARGET_EXE)
    print("  保存目录 : %s\\Pictures\\ImageViewer" % os.path.expanduser("~"))
    print("  配置文件 : %s\\FastImageViewer\\config.json" % os.environ.get("APPDATA", ""))
    print("  卸载方式 : 运行 uninstall.py")
    print("-" * 62)
    print("\n  ✔ 双击任意图片即可用极速看图打开")
    print("  ✔ 若图标未立即刷新，注销或重启资源管理器即可")
    print("\n  快捷键: Ctrl+O 打开 | Ctrl+C 复制 | Ctrl+S 保存 | Ctrl+Shift+S 另存为")
    print("          ← → 切换图片 | 滚轮缩放 | 0 复位 | Esc 退出")

    # 询问是否立刻试一张
    try:
        ans = input("\n现在启动一次试试？(Y/n): ").strip().lower()
    except EOFError:
        ans = "n"
    if ans in ("", "y", "yes"):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "open", TARGET_EXE, None, None, 1)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())