"""
打包 auto_spectate.py 为单个 exe 文件。
用法：python build_exe.py
"""

import os
import subprocess
import sys

SCRIPT = "auto_spectate.py"
NAME = "RocoAutoSpectate"
TEMPLATE_DIR = "templates"

# 确保在脚本所在目录运行
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 收集 templates 目录下所有 png 作为数据文件
tpl_pattern = os.path.join(TEMPLATE_DIR, "*.png")
datas = f"{TEMPLATE_DIR};{TEMPLATE_DIR}"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--console",
    f"--name={NAME}",
    f"--add-data={datas}",
    "--hidden-import=interception",
    "--hidden-import=cv2",
    "--hidden-import=numpy",
    "--hidden-import=win32gui",
    "--hidden-import=win32ui",
    "--hidden-import=win32con",
    "--hidden-import=ctypes",
    "--clean",
    "--noconfirm",
    SCRIPT,
]

print(f"[构建] {' '.join(cmd)}")
subprocess.check_call(cmd)
print(f"\n[完成] dist/{NAME}.exe")
