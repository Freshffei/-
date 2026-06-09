import ctypes
import time
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

# ======================== 配置 ========================
WINDOW_KEYWORD = "洛克王国：世界"
TEMPLATE_PATH = "templates/zhandou.png"
THRESHOLD = 0.5          # 匹配阈值，大于此值认为识别成功
INTERVAL_SEC = 1.0       # 截图间隔（秒）
# =====================================================

# DPI Awareness
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


def find_game_window(keyword: str = WINDOW_KEYWORD) -> Optional[int]:
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
    return min(matches, key=lambda m: len(m[1]))[0]


def capture_window_bgr(hwnd: int) -> np.ndarray:
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


def template_match(img: np.ndarray, template: np.ndarray) -> Tuple[float, Tuple[int, int]]:
    """模板匹配，返回 (最大匹配度, 左上角坐标)。"""
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    res = cv2.matchTemplate(img_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return max_val, max_loc


if __name__ == "__main__":
    # 1. 查找游戏窗口
    print("正在查找游戏窗口...")
    hwnd = find_game_window()
    if hwnd is None:
        print(f"未找到包含 '{WINDOW_KEYWORD}' 的游戏窗口，请确认游戏已启动")
        exit()

    title = win32gui.GetWindowText(hwnd)
    print(f"已绑定窗口: '{title}' (句柄: {hwnd})")

    # 2. 加载模板
    template = cv2.imread(TEMPLATE_PATH)
    if template is None:
        print(f"模板加载失败: {TEMPLATE_PATH}")
        exit()
    h, w = template.shape[:2]
    print(f"模板已加载: {TEMPLATE_PATH} ({w}x{h})")

    # 3. 实时检测循环
    print(f"\n开始实时检测，每 {INTERVAL_SEC} 秒一帧，按 'q' 退出...\n")

    frame_count = 0
    last_time = 0  # 控制帧率

    while True:
        now = time.time()
        if now - last_time < INTERVAL_SEC:
            time.sleep(0.01)
            continue
        last_time = now

        frame_count += 1

        # 窗口是否还存在
        if not win32gui.IsWindow(hwnd):
            print("游戏窗口已关闭")
            break

        # 捕获画面
        img = capture_window_bgr(hwnd)

        # 模板匹配
        score, top_left = template_match(img, template)
        detected = score >= THRESHOLD

        # 在画面上标注
        display_img = img.copy()
        status_text = f"Frame: {frame_count} | Score: {score:.3f}"
        if detected:
            bottom_right = (top_left[0] + w, top_left[1] + h)
            cv2.rectangle(display_img, top_left, bottom_right, (0, 0, 255), 2)
            cv2.putText(display_img, f"FOUND ({score:.3f})", top_left,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            status_text += " | STATUS: 战斗中!"
            print(f"[Frame {frame_count:04d}] 检测到战斗! 匹配度: {score:.3f}  位置: {top_left}")
        else:
            status_text += " | STATUS: 待机中"
            # 每10帧输出一次，避免刷屏
            if frame_count % 10 == 0:
                print(f"[Frame {frame_count:04d}] 未检测到战斗  匹配度: {score:.3f}")

        cv2.putText(display_img, status_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        cv2.imshow("RocoPilot - Real-time Detection", display_img)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("用户退出")
            break

    cv2.destroyAllWindows()
    print("检测结束")
