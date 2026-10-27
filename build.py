# -*- coding: utf-8 -*-
"""
FastImageViewer build script
把 viewer.py 打包成 Windows 独立程序（onedir 模式）。

为什么不用 --onefile：
    onefile 每次启动都要把内部文件解压到临时目录，实测启动 5.6 秒；
    onedir 只需 0.6~1.2 秒，快约 7 倍。本项目核心诉求是"启动快"，故用 onedir。

用法：
    python build.py
"""
import os
import sys
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
APP = "FastImageViewer"


def gen_icon(path):
    """生成应用图标（无外部依赖，需要 Pillow）"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  跳过图标生成（未安装 Pillow）")
        return False
    sizes = [16, 24, 32, 48, 64, 128, 256]
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, 248, 248], radius=52, fill=(37, 99, 235, 255))
    d.polygon([(40, 196), (104, 120), (150, 196)], fill=(255, 255, 255, 235))
    d.polygon([(112, 196), (168, 126), (226, 196)], fill=(255, 255, 255, 180))
    d.ellipse([164, 56, 204, 96], fill=(255, 206, 84, 255))
    im.save(path, sizes=[(s, s) for s in sizes])
    return True


def main():
    print("=" * 62)
    print("  构建 %s" % APP)
    print("=" * 62)

    try:
        import PyInstaller  # noqa
    except ImportError:
        print("\n[×] 未安装 PyInstaller。请先执行：")
        print("    pip install pillow pyinstaller")
        return 1

    icon = os.path.join(HERE, "icon.ico")
    if not os.path.isfile(icon):
        print("\n[1/2] 生成图标...")
        if gen_icon(icon):
            print("      icon.ico 已生成")
    else:
        print("\n[1/2] 图标已存在，跳过")

    print("\n[2/2] 打包中（约 40 秒）...")
    # 用独立产物目录，避免 --clean 触发删除确认拦截
    dist = os.path.join(HERE, "dist_v3")
    work = os.path.join(HERE, "build_v3")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", dist,
        "--workpath", work,
        "--specpath", work,
        "--onedir",            # 关键：不用 onefile，保证启动速度
        "--windowed",          # 不显示控制台
        "--name", APP,
        "--icon", icon,
        "--noupx",
        "--exclude-module", "numpy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide2",
        "--exclude-module", "IPython",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "pytest",
        "--hidden-import", "pytesseract",
        "--add-data", "%s/tesseract;tesseract" % HERE,   # OCR 便携版
        "viewer.py",
    ]
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        print("\n[×] 打包失败")
        return r.returncode

    out = os.path.join(dist, APP)
    exe = os.path.join(out, APP + ".exe")
    if not os.path.isfile(exe):
        print("\n[×] 未找到产物 %s" % exe)
        return 1

    total = 0
    for root, _, files in os.walk(out):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass

    print("\n" + "=" * 62)
    print("  构建完成")
    print("=" * 62)
    print("  产物目录 : %s" % out)
    print("  主程序   : %s (%.1f MB)" % (exe, os.path.getsize(exe) / 1048576.0))
    print("  总体积   : %.1f MB" % (total / 1048576.0))
    print("\n  下一步：运行 python install.py 安装并注册为图片默认打开方式")
    return 0


if __name__ == "__main__":
    sys.exit(main())