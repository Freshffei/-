import ctypes
from typing import Optional, Tuple

import cv2
import numpy as np
import win32con
import win32gui
import win32ui

# DPI Awareness
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# 游戏窗口标题关键词（根据实际情况修改）
WINDOW_KEYWORD = "洛克王国：世界"


def find_game_window(keyword: str = WINDOW_KEYWORD) -> Optional[int]:
    """查找包含关键词的游戏窗口，返回窗口句柄。"""
    matches = []

    def _enum_handler(hwnd: int, _ctx: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.IsIconic(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and keyword in title:
            matches.append((hwnd, title))

    win32gui.EnumWindows(_enum_handler, None)

    if not matches:
        return None
    # 标题最短的最可能是主窗口
    return min(matches, key=lambda m: len(m[1]))[0]


def get_client_rect_on_screen(hwnd: int) -> Tuple[int, int, int, int]:
    """获取窗口客户区在屏幕上的位置和大小 (left, top, width, height)。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    client_w = right - left
    client_h = bottom - top
    screen_left, screen_top = win32gui.ClientToScreen(hwnd, (0, 0))
    return screen_left, screen_top, client_w, client_h


def capture_window_bgr(hwnd: int) -> np.ndarray:
    """通过 Win32 API 抓取窗口客户区内容，返回 BGR 格式的 numpy 数组（OpenCV 可用）。"""
    client_rect = win32gui.GetClientRect(hwnd)
    client_w = client_rect[2] - client_rect[0]
    client_h = client_rect[3] - client_rect[1]

    if client_w <= 0 or client_h <= 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)

    hwndDC = win32gui.GetDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, client_w, client_h)
    saveDC.SelectObject(saveBitMap)

    try:
        result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)

        if result != 1:
            saveDC.BitBlt((0, 0), (client_w, client_h), mfcDC, (0, 0), win32con.SRCCOPY)

        signedIntsArray = saveBitMap.GetBitmapBits(True)
        img = np.frombuffer(signedIntsArray, dtype='uint8')

        expected_size = client_h * client_w * 4
        if len(img) != expected_size:
            img = np.zeros(expected_size, dtype='uint8')

        img.shape = (client_h, client_w, 4)
    finally:
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)

    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


if __name__ == "__main__":
    # 1. 查找游戏窗口
    hwnd = find_game_window()
    if hwnd is None:
        print(f"未找到包含 '{WINDOW_KEYWORD}' 的游戏窗口")
        exit()

    title = win32gui.GetWindowText(hwnd)
    x, y, w, h = get_client_rect_on_screen(hwnd)
    print(f"找到窗口: '{title}' (句柄: {hwnd})")
    print(f"客户区位置: ({x}, {y}), 大小: {w}x{h}")

    # 2. 捕获游戏画面
    img = capture_window_bgr(hwnd)
    print(f"捕获画面大小: {img.shape[1]}x{img.shape[0]}")

    # 3. 显示捕获的画面
    cv2.imshow("Game Window Capture", img)
    print("按任意键关闭预览...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
