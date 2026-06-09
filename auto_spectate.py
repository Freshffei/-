"""
洛克王国：世界 — 自动观战系统
===============================
状态机驱动的自动观战流程：
  SEARCH_BATTLE → AIM_AND_MOVE → CHECK_PANEL → SPECTATING → BATTLE_END → SEARCH_BATTLE

依赖：
  opencv-python, numpy, pywin32, interception
"""

import ctypes
import os
import random
import time
from enum import Enum
from typing import Optional, Tuple

import cv2
import numpy as np
import win32con
import win32gui
import win32ui
import interception

# ======================== 配置 ========================
WINDOW_KEYWORD = "洛克王国：世界"

# 模板文件
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
TEMPLATE_FIGHT = "zhandou.png"   # 战斗标记（远处可见）
TEMPLATE_NIHAO = "nihao.png"     # 交互提示（靠近玩家后出现）
TEMPLATE_VIEW = "guanzhan.png"   # 观战按钮（面板上）
TEMPLATE_CLOSE = "close.png"     # 关闭按钮（面板上，不可观战时关闭）
TEMPLATE_JUBAO = "jubao.png"     # 举报按钮（战斗结束时出现）
TEMPLATE_CHAT = "chat.png"       # 观战界面标识（进入观战后出现）
TEMPLATE_CAMERA = "xiangji.png"  # 寻找观战阶段标识（非观战非战斗时显示）
TEMPLATE_IMG = "img.png"         # 寻找观战过程标识
TEMPLATE_WATCHING = "watching.png"  # 其他观战玩家位置标记
TEMPLATE_LUOKEBEI = "luokebei.png"  # 战斗结束标识
TEMPLATE_MAP = "map.png"           # 卡死检测（地图界面）

# 匹配阈值
MATCH_THRESHOLD = 0.78           # 噪声地板~0.72，真实目标应显著高于此值
MATCH_THRESHOLD_NIHAO = 0.90    # nihao 检测阈值（真匹配0.9+）
MATCH_THRESHOLD_PANEL = 0.70    # 面板 close 的阈值
MATCH_THRESHOLD_GUANZHAN = 0.80  # guanzhan 匹配阈值（高阈值防误触）
MATCH_THRESHOLD_CHAT = 0.5      # chat 进入观战界面的确认阈值
MATCH_THRESHOLD_LUOKEBEI = 0.6  # 战斗结束标识 luokebei 检测阈值
MATCH_THRESHOLD_MAP = 0.7       # 卡死检测 map 检测阈值

# ENTER_SPECTATE 等待观战界面加载的超时（秒）
ENTER_SPECTATE_TIMEOUT = 5.0


# 死区（战斗标记水平方向距屏幕中心多少像素以内不旋转）
DEAD_ZONE = 30

# 小步旋转：每次朝目标方向旋转的鼠标移动量
STEP_ROTATE = 35                # 旋转步幅（鼠标移动量/步）

# 方向保持：连续同向旋转多少步后才允许切换方向（防止振荡）
DIRECTION_HOLD_STEPS = 3

# 时间参数（秒）
SEARCH_INTERVAL = 0.12          # 搜索战斗的截图间隔
AIM_INTERVAL = 0.02             # 瞄准步骤间隔（高频旋转）
NIHOO_CHECK_COOLDOWN = 0.5      # 检测到nihao后按F的冷却时间
SPECTATE_CHECK_INTERVAL = 3.0   # 观战中检查战斗结束的间隔
AIM_TIMEOUT = 15.0              # 瞄准+移动超时（超时后重新搜索）
PANEL_TIMEOUT = 3.0             # 面板等待超时
W_TAP_DURATION = 0.25           # W键前进步长（秒）

# 搜索时随机旋转的鼠标移动量范围（像素）
ROTATE_SEARCH_MIN = 100
ROTATE_SEARCH_MAX = 300
# =====================================================

# DPI Awareness
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


class SpectateState(Enum):
    SEARCH_BATTLE = "search_battle"
    AIM_AND_MOVE = "aim_and_move"
    CHECK_PANEL = "check_panel"
    ENTER_SPECTATE = "enter_spectate"
    SPECTATING = "spectating"
    BATTLE_END = "battle_end"



# ======================== 窗口相关 ========================

def find_game_window(keyword: str = WINDOW_KEYWORD) -> Optional[int]:
    """查找标题包含关键词的可见游戏窗口，返回句柄。"""
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


def get_client_screen_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """返回客户区屏幕坐标 (left, top, width, height)。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bottom - top
    sl, st = win32gui.ClientToScreen(hwnd, (0, 0))
    return sl, st, w, h


def capture_window_bgr(hwnd: int) -> np.ndarray:
    """通过 Win32 API 捕获窗口客户区，返回 BGR 格式 numpy 数组。"""
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


# ======================== 主控制器 ========================

class AutoSpectate:
    """自动观战状态机。"""

    def __init__(self):
        self.state = SpectateState.SEARCH_BATTLE
        self.hwnd: Optional[int] = None
        self.templates: dict = {}
        # 时间记录
        self.last_frame_time = 0.0
        self.state_start_time = 0.0
        self.last_f_press = time.time()        # 避免首帧立即按F
        self.last_spectate_check = time.time()
        self.last_search_rotate = time.time()
        self.panel_check_start = 0.0

        # 状态数据
        self.frame_count = 0
        self.battle_pos: Optional[Tuple[int, int]] = None
        self.w_key_held = False

        # 旋转方向一致性（防止多标记间振荡）
        self.rotate_dir = 0           # 当前旋转方向: 1=右, -1=左, 0=未定
        self.rotate_same_dir_count = 0  # 同方向连续步数
        self.rotate_steps_remaining = 0  # 剩余旋转步数
        self._paused = False          # 焦点丢失暂停标记
        self.jubao_pos: Optional[Tuple[int, int]] = None  # 举报按钮位置（用于避开）
        self._last_guanzhan_click = (0.0, (0, 0))  # (time, pos) 上次点击观战按钮
        self._aim_done = False          # 已对准标记，进入前进+等nihao阶段
        self._aim_iter = 0             # 瞄准迭代计数
        self._aim_done_time = 0.0     # 进入前进阶段的时间戳
        self._last_recheck = 0.0      # 上次重检测目标位置的时间
        self._stuck_count = 0         # 目标连续丢失计数（卡墙检测）
        self._spectate_wake_time = 0.0  # 观战休眠唤醒时间
        self._chat_missing_time = 0.0   # chat首次消失的时间戳
        self._chat_missing_count = 0    # chat连续消失确认次数
        self._luokebei_detect_time = 0.0  # luokebei稳定检测起始时间
        self._guanzhan_retries = 0        # 观战点击重试次数
        self._last_camera_calib = 0.0     # 上次相机矫正时间

        # nihao稳定检测
        self.nihao_detect_time = 0.0
        self.nihao_stable_required = 0.5  # 持续出现0.5秒才允许按F
        self.filtered_target_x = None     # 目标X坐标低通滤波
        self.last_turn_time = 0.0        # 上次转向时间（冷却用）
        self.last_error_sign = 0        # 误差符号 (1右/-1左/0初始)
        self.shake_count = 0            # 振荡计数器（符号连续翻转次数）
        self._last_shake_time = 0       # 上次振荡计数时间（防重复）
        self.next_align_time = 0        # 对准转向冷却时间（一次性大转+等待稳定）
        self.last_error = 0             # 上一次误差值（突变过滤）
        self._target_tpl = 'fight'     # 当前瞄准的模板名（fight/watching）
        self._search_detect_count = 0  # 搜索目标连续检测计数
        self._search_last_tpl = None   # 上次检测到的模板类型

        # ===== 目标锁定 =====
        self.lock_target = None
        self.lock_time = 0
        self.lock_timeout = 5.0

    # ── 模板 ──────────────────────────────────────

    def load_templates(self) -> None:
        """加载模板。支持同目标多张图：zhandou.png / zhandou_2.png / zhandou_3.png ..."""
        import glob as glob_mod
        mapping = {
            'fight': TEMPLATE_FIGHT,
            'nihao': TEMPLATE_NIHAO,
            'view': TEMPLATE_VIEW,
            'close': TEMPLATE_CLOSE,
            'jubao': TEMPLATE_JUBAO,
            'chat': TEMPLATE_CHAT,
            'camera': TEMPLATE_CAMERA,
            'img': TEMPLATE_IMG,
            'watching': TEMPLATE_WATCHING,
            'luokebei': TEMPLATE_LUOKEBEI,
            'map': TEMPLATE_MAP,
        }
        for name, base_filename in mapping.items():
            # 从基础文件名提取前缀，扫描 {prefix}*.png
            base = os.path.splitext(base_filename)[0]  # zhandou
            pattern = os.path.join(TEMPLATE_DIR, f"{base}*.png")
            files = sorted(glob_mod.glob(pattern))
            if not files:
                print(f"[警告] 未找到模板: {pattern}")
                continue

            tpls = []
            for f in files:
                tpl = cv2.imread(f)
                if tpl is not None:
                    tpls.append((os.path.basename(f), tpl))
                    print(f"[模板] {name}: {os.path.basename(f)} ({tpl.shape[1]}x{tpl.shape[0]})")
                else:
                    print(f"[警告] 模板加载失败: {f}")
            if tpls:
                self.templates[name] = tpls

        # 必须模板检查
        for required in ['fight', 'nihao', 'view', 'jubao']:
            if required not in self.templates:
                print(f"[错误] 必须模板 '{required}' 加载失败，无法继续。"
                      f"请确保 {TEMPLATE_DIR}/ 下存在对应文件。")

    def has_template(self, name: str) -> bool:
        return name in self.templates and len(self.templates[name]) > 0

    def _tpl_size(self, name: str):
        """返回模板组第一个模板的 (h, w)，用于坐标计算。"""
        tpls = self.templates.get(name, [])
        if tpls:
            return tpls[0][1].shape[:2]
        return (0, 0)

    # ── 窗口 ──────────────────────────────────────

    def find_and_bind_window(self) -> bool:
        """查找并绑定游戏窗口。"""
        hwnd = find_game_window()
        if hwnd is None:
            print(f"[错误] 未找到包含 '{WINDOW_KEYWORD}' 的游戏窗口")
            return False
        self.hwnd = hwnd
        title = win32gui.GetWindowText(hwnd)
        x, y, w, h = get_client_screen_rect(hwnd)
        print(f"[窗口] 已绑定: '{title}' (句柄: {hwnd})")
        print(f"[窗口] 客户区: ({x}, {y}) 大小: {w}x{h}")
        return True

    def is_window_valid(self) -> bool:
        return self.hwnd is not None and win32gui.IsWindow(self.hwnd)

    def capture(self) -> np.ndarray:
        return capture_window_bgr(self.hwnd)

    # ── 模板匹配（支持多模板：取最佳匹配）──────────────────

    def match_template(self, img: np.ndarray, name: str) -> Tuple[float, Tuple[int, int]]:
        """对模板组全部匹配，返回 (最佳匹配度, 左上角坐标)。"""
        tpls = self.templates.get(name, [])
        if not tpls:
            return 0.0, (0, 0)

        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        best_score, best_loc = 0.0, (0, 0)

        for _, template in tpls:
            tpl_h, tpl_w = template.shape[:2]
            if img.shape[0] < tpl_h or img.shape[1] < tpl_w:
                continue
            tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(img_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc

        return best_score, best_loc

    def find_all_matches(self, img: np.ndarray, name: str,
                         threshold: float = 0.7):
        """
        对所有模板匹配，合并所有超过阈值的匹配点。
        返回: [(score, (x,y)), ...]
        """
        tpls = self.templates.get(name, [])
        if not tpls:
            return []

        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        all_matches = []

        for _, template in tpls:
            tpl_h, tpl_w = template.shape[:2]
            if img.shape[0] < tpl_h or img.shape[1] < tpl_w:
                continue
            tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(img_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
            locations = np.where(res >= threshold)
            for pt in zip(*locations[::-1]):
                score = float(res[pt[1], pt[0]])
                all_matches.append((score, pt))

        return all_matches

    def smooth_turn(self, error: float) -> int:
        """
        sqrt非线性转向：
        - 误差大时增长变慢，不会突然甩飞
        - 误差小时平滑微调
        """
        abs_err = abs(error)

        # 死区
        if abs_err < 35:
            return 0

        # sqrt缩放：误差越大增长越缓，防止过冲
        turn = int(np.sqrt(abs_err) * 7)

        # 上限110，不会甩飞
        turn = min(turn, 110)

        if error < 0:
            turn = -turn

        return turn


    # ── 输入辅助 ─────────────────────────────────

    def _hold_w(self) -> None:
        if not self.w_key_held:
            interception.key_down('w', delay=0)
            self.w_key_held = True

    def _tap_w(self, duration: float = 0.03) -> None:
        """快速点按W（用于nihao锁定后的慢速靠近）。"""
        if self.w_key_held:
            self._release_w()
        interception.key_down('w', delay=0)
        time.sleep(duration)
        interception.key_up('w', delay=0)

    def _release_w(self) -> None:
        if self.w_key_held:
            interception.key_up('w', delay=0)
            self.w_key_held = False

    def _rotate_camera(self, dx: int) -> None:
        """鼠标平滑移动旋转相机，并记录转向时间用于冷却。"""
        if dx == 0:
            return
        steps = max(1, abs(dx) // 10)   # 每步10px
        step_x = dx // steps
        remainder = dx % steps
        for i in range(steps):
            move = step_x + (1 if abs(remainder) > i and dx > 0 else
                            -1 if abs(remainder) > i and dx < 0 else 0)
            if move != 0:
                interception.move_relative(move, 0)
            time.sleep(0.008)
        self.last_turn_time = time.time()

    def _click_at_client(self, client_x: int, client_y: int) -> None:
        """在窗口客户区坐标处点击。仅在允许的状态下执行。"""
        if self.state in (SpectateState.SEARCH_BATTLE, SpectateState.AIM_AND_MOVE):
            print(f"[阻止] 非点击状态 ({self.state.value}) 下禁止点击，忽略")
            return
        sx, sy = win32gui.ClientToScreen(self.hwnd, (client_x, client_y))
        print(f"[点击] 客户区({client_x}, {client_y}) → 屏幕({sx}, {sy})  状态: {self.state.value}")
        interception.click(
            sx + random.randint(-2, 2),
            sy + random.randint(-2, 2),
            delay=random.uniform(0.05, 0.12),
        )

    def _random_click(self, img: np.ndarray) -> None:
        """在画面中随机位置点击（用于关闭结算界面）。"""
        h, w = img.shape[:2]
        rx = random.randint(w // 4, w * 3 // 4)
        ry = random.randint(h // 4, h * 3 // 4)
        self._click_at_client(rx, ry)

    def _click_avoid_jubao(self, img: np.ndarray) -> None:
        """点击屏幕随机位置，但避开举报按钮区域。"""
        h, w = img.shape[:2]
        # 如果有 jubao 位置记录，避开它周围 100px
        avoid_rect = None
        if hasattr(self, 'jubao_pos') and self.jubao_pos is not None:
            tpl_h, tpl_w = self._tpl_size('jubao')
            jx, jy = self.jubao_pos
            # 避开区域：jubao位置 ± 100px
            avoid_rect = (jx - 100, jy - 100, jx + tpl_w + 100, jy + tpl_h + 100)

        for _ in range(10):  # 最多试10次避开
            rx = random.randint(w // 6, w * 5 // 6)
            ry = random.randint(h // 6, h * 5 // 6)
            if avoid_rect is None:
                break
            if not (avoid_rect[0] < rx < avoid_rect[2] and avoid_rect[1] < ry < avoid_rect[3]):
                break  # 不在避开区域内，可以点

        print(f"[点击避开] ({rx}, {ry})")
        self._click_at_client(rx, ry)

    def _press_f(self) -> None:
        """停止移动 → 按F键（不点击屏幕）。"""
        self._release_w()
        time.sleep(0.1)  # 确保角色停稳
        interception.press('f')
        time.sleep(0.5)  # 等待面板弹出

    def _escape_panel(self) -> None:
        """ESC关闭面板 → 检测close.png确认是否退出 → 循环直到界面关闭。"""
        print("[脱离] 开始关闭面板...")
        for attempt in range(5):
            # 按ESC + 随机方向键
            interception.key_down('esc', delay=0)
            time.sleep(0.08)
            interception.key_up('esc', delay=0)
            time.sleep(0.3)
            d = random.choice(['w', 'a', 's', 'd'])
            interception.key_down(d, delay=0)
            time.sleep(random.uniform(0.3, 0.5))
            interception.key_up(d, delay=0)
            time.sleep(0.3)

            # 截图检测close.png是否还在
            if self.has_template('close'):
                check_img = self.capture()
                close_score, _ = self.match_template(check_img, 'close')
                if close_score < MATCH_THRESHOLD_PANEL:
                    print(f"[脱离] close={close_score:.3f} 面板已关闭")
                    return
                print(f"[脱离] 第{attempt+1}次 close={close_score:.3f} 面板仍在，继续ESC...")
            else:
                return  # 没有close模板，假定已退出

        print("[脱离] 5次尝试后面板仍未关闭，继续运行")

    # ── 状态处理 ─────────────────────────────────

    def state_search_battle(self, img: np.ndarray) -> None:
        """
        SEARCH_BATTLE:
        zhandou优先 → 直接追。没有zhandou才用watching参考方向。
        有map.png → 卡死 → ESC解除。
        """
        # 卡死检测：map.png 出现 → ESC解除
        if self.has_template('map'):
            map_score, _ = self.match_template(img, 'map')
            if map_score >= MATCH_THRESHOLD_MAP:
                print(f"[卡死] 检测到map map={map_score:.3f}，ESC解除")
                interception.press('esc')
                time.sleep(0.5)
                return

        # 相机自动矫正：每120s按住ESC 0.5s→等待2s系统修正→按住ESC 0.5s退出矫正
        now = time.time()
        if now - self._last_camera_calib > 120.0:
            print("[矫正] 按住ESC 0.5s（进入矫正）...")
            interception.key_down('esc', delay=0)
            time.sleep(0.5)
            interception.key_up('esc', delay=0)
            print("[矫正] 等待2s系统修正...")
            time.sleep(2.0)
            print("[矫正] 按住ESC 0.5s（退出矫正）...")
            interception.key_down('esc', delay=0)
            time.sleep(0.5)
            interception.key_up('esc', delay=0)
            time.sleep(0.3)
            # 校验：检测close.png确认已退出矫正界面
            if self.has_template('close'):
                check_img = self.capture()
                close_score, _ = self.match_template(check_img, 'close')
                if close_score >= MATCH_THRESHOLD_PANEL:
                    print(f"[矫正] close={close_score:.3f} 仍在校准界面，追加ESC...")
                    self._escape_panel()
            self._last_camera_calib = now
            return

        h, w = img.shape[:2]
        screen_cx = w // 2
        center_margin = 250

        def _valid_pos(p):
            px, py = p
            if not (w * 0.20 < px < w * 0.80):
                return False
            if not (py > h * 0.25):
                return False
            if not (py < h * 0.90):
                return False
            if abs(px - screen_cx) > center_margin:
                return False
            return True

        def _pick_best(matches, tpl_name):
            """从匹配列表中选最佳目标（优先锁定，否则选最靠中心）。"""
            valid = [(tpl_name, score, pos) for score, pos in matches if _valid_pos(pos)]
            if not valid:
                return None
            now = time.time()
            # 锁定中 → 找最近似
            if self.lock_target is not None and now - self.lock_time < self.lock_timeout:
                lx, ly = self.lock_target
                best = min(valid, key=lambda x: abs(x[2][0] - lx) + abs(x[2][1] - ly))
                return best
            # 无锁定 → 最靠中心
            best = min(valid, key=lambda x: abs(x[2][0] + self._tpl_size(x[0])[1] // 2 - screen_cx))
            return best

        now = time.time()

        # =========================================================
        # 优先级1: zhandou.png — 直接追
        # =========================================================
        fight_matches = self.find_all_matches(img, 'fight', threshold=MATCH_THRESHOLD)
        best_target = _pick_best(fight_matches, 'fight')

        # =========================================================
        # 优先级2: 没有zhandou → watching.png 参考方向
        # =========================================================
        if best_target is None and self.has_template('watching'):
            watch_matches = self.find_all_matches(img, 'watching', threshold=MATCH_THRESHOLD)
            best_target = _pick_best(watch_matches, 'watching')

        # =========================================================
        # 没目标 → 旋转搜索
        # =========================================================
        if best_target is None:
            self.lock_target = None
            if now - self.last_search_rotate > 0.8:
                angle = random.randint(300, 600)
                self._rotate_camera(angle)
                self.last_search_rotate = now
            return

        # =========================================================
        # 确认目标 → 进入瞄准
        # =========================================================
        target_tpl, target_score, target_pos = best_target

        self.lock_target = target_pos
        self.lock_time = now
        self.battle_pos = target_pos
        self._target_tpl = target_tpl

        tpl_name = 'zhandou' if target_tpl == 'fight' else 'watching'
        print(f"\n[发现目标] {tpl_name} score={target_score:.3f} pos={target_pos}")

        self.state_start_time = time.time()
        self.last_f_press = time.time()
        self._aim_done = False

        self._transition(SpectateState.AIM_AND_MOVE)

    # ── 瞄准（一次转到位 → 走0.5s → 停下判断nihao → 再转）────
    AIM_FIRST_RATIO = 3.0       # error/ratio，像素/鼠标单位
    AIM_CENTER_THRESH = 60      # 误差<60px视为已对准
    AIM_WALK_DURATION = 0.5     # 每次前进0.5秒后停下判断nihao

    def state_aim_and_move(self, img: np.ndarray) -> None:
        """检测偏移 → 一次转到位 → 走0.5s → 停下判断nihao → 循环。"""
        now = time.time()
        elapsed = now - self.state_start_time

        # 超时
        if elapsed > AIM_TIMEOUT:
            print(f"[超时] 瞄准超时 ({AIM_TIMEOUT}s)，重新搜索")
            self._release_w()
            self._aim_done = False
            self.nihao_detect_time = 0.0
            self._rotate_camera(random.choice([-1, 1]) * random.randint(200, 400))
            self._transition(SpectateState.SEARCH_BATTLE)
            return

        # nihao 检测 (全程)
        nihao_score, _ = self.match_template(img, 'nihao')
        if nihao_score >= MATCH_THRESHOLD_NIHAO:
            if self.nihao_detect_time == 0:
                self.nihao_detect_time = now
            stable_time = now - self.nihao_detect_time
            if stable_time >= self.nihao_stable_required and now - self.last_f_press >= NIHOO_CHECK_COOLDOWN:
                self.last_f_press = now
                self._release_w()
                self._aim_done = False
                self.nihao_detect_time = 0.0
                print(f"[交互] nihao稳定{stable_time:.2f}s，按下F")
                self._press_f()
                time.sleep(0.3)
                panel_img = self.capture()
                if self.has_template('close'):
                    close_score, _ = self.match_template(panel_img, 'close')
                    if close_score >= MATCH_THRESHOLD_PANEL:
                        print(f"[交互] 面板已打开 close={close_score:.3f}")
                        self._transition(SpectateState.CHECK_PANEL)
                        return
        else:
            self.nihao_detect_time = 0.0

        # 已对准 → 走0.5s → 没nihao就回搜索
        if self._aim_done:
            if now - self._aim_done_time < self.AIM_WALK_DURATION:
                self._hold_w()
                return
            self._release_w()
            self._aim_done = False
            print("[瞄准] 走0.5s未发现nihao，重新搜索目标")
            self._transition(SpectateState.SEARCH_BATTLE)
            return

        # 检测偏移 → 一次转到位 → 走0.5s
        score, pos = self.match_template(img, self._target_tpl)
        if score < MATCH_THRESHOLD:
            # 目标丢失（走近后zhandou可能消失），回搜索
            self._transition(SpectateState.SEARCH_BATTLE)
            return

        screen_cx = img.shape[1] // 2
        tpl_w = self._tpl_size(self._target_tpl)[1]
        error = (pos[0] + tpl_w // 2) - screen_cx

        if abs(error) > self.AIM_CENTER_THRESH:
            dx = int(error / self.AIM_FIRST_RATIO)
            dx = max(-200, min(200, dx))
            self._rotate_camera(dx)
            tpl_name = 'zhandou' if self._target_tpl == 'fight' else 'watching'
            print(f"[对准] {tpl_name} error={error:+d}  turn={dx:+d}")

        self._aim_done = True
        self._aim_done_time = time.time()  # 旋转后的实时时间，确保走满0.5s

    def state_check_panel(self, img: np.ndarray) -> None:
        """CHECK_PANEL: 找guanzhan → 点击；找不到 → ESC脱离。"""
        now = time.time()
        elapsed = now - self.state_start_time

        guan_score, guan_pos = self.match_template(img, 'view')
        h, w = img.shape[:2]

        def _in_panel_center(p):
            return (w * 0.10 < p[0] < w * 0.90) and (h * 0.10 < p[1] < h * 0.90)

        if guan_score >= MATCH_THRESHOLD_GUANZHAN and _in_panel_center(guan_pos):
            tpl_h, tpl_w = self._tpl_size('view')
            click_x = guan_pos[0] + tpl_w // 2
            click_y = guan_pos[1] + tpl_h // 2
            print(f"[观战] 找到 guanzhan={guan_score:.3f} 点击 ({click_x}, {click_y})")
            self._click_at_client(click_x, click_y)
            time.sleep(1.0)
            self._guanzhan_retries = 0
            self._transition(SpectateState.ENTER_SPECTATE)
            return

        # 没有 guanzhan → ESC脱离
        if elapsed > 1.0:
            print(f"[面板] 未找到guanzhan (score={guan_score:.3f})，ESC脱离")
            self._escape_panel()
            self._transition(SpectateState.SEARCH_BATTLE)
            return

    def state_enter_spectate(self, img: np.ndarray) -> None:
        """ENTER_SPECTATE: 等chat(约10s后才出现) → 观战成功 / guanzhan还在则重试 / 失败则ESC脱离。"""
        now = time.time()
        elapsed = now - self.state_start_time

        # chat.png 约10s后才出现，6s后开始检测
        if elapsed > 6.0:
            chat_score, _ = self.match_template(img, 'chat')
            if chat_score >= MATCH_THRESHOLD_CHAT:
                print(f"[进入观战] 观战成功 chat={chat_score:.3f}  ({elapsed:.0f}s)")
                self._transition(SpectateState.SPECTATING)
                return

        # 前8s只等待，不检测guanzhan（点完guanzhan消失≠失败，chat还没出）
        if elapsed < 8.0:
            if self.frame_count % 15 == 0:
                print(f"[进入观战] 等待chat加载... {elapsed:.0f}s")
            return

        # 8s后chat仍未出现 → 检查guanzhan是否还在
        guan_score, guan_pos = self.match_template(img, 'view')

        if guan_score >= MATCH_THRESHOLD_GUANZHAN:
            self._guanzhan_retries += 1
            if self._guanzhan_retries <= 2:
                tpl_h, tpl_w = self._tpl_size('view')
                click_x = guan_pos[0] + tpl_w // 2
                click_y = guan_pos[1] + tpl_h // 2
                print(f"[进入观战] {elapsed:.0f}s chat未出 guanzhan还在，重试第{self._guanzhan_retries}次")
                self._click_at_client(click_x, click_y)
                time.sleep(1.0)
                self.state_start_time = now
                return
            else:
                print(f"[进入观战] 重试{self._guanzhan_retries}次仍无法观战，ESC脱离")
                self._escape_panel()
                self._transition(SpectateState.SEARCH_BATTLE)
                return

        # guanzhan不在了，chat还没出 → 可能在加载中，继续等
        if elapsed > 20.0:
            print(f"[进入观战] {elapsed:.0f}s 超时，ESC脱离")
            self._escape_panel()
            self._transition(SpectateState.SEARCH_BATTLE)

    def state_spectating(self, img: np.ndarray) -> None:
        """SPECTATING: 检测 luokebei.png 稳定1s → 战斗结束。"""
        now = time.time()
        elapsed = now - self.state_start_time

        luokebei_score, _ = self.match_template(img, 'luokebei')

        if luokebei_score >= MATCH_THRESHOLD_LUOKEBEI:
            if self._luokebei_detect_time == 0.0:
                self._luokebei_detect_time = now
            stable = now - self._luokebei_detect_time
            if self.frame_count % 5 == 0:
                print(f"[观战中] {elapsed:.0f}s  luokebei={luokebei_score:.3f}  稳定{stable:.1f}s")
            if stable >= 5.0:
                print(f"[战斗结束] {elapsed:.0f}s  luokebei稳定{stable:.1f}s → 点击屏幕 → 重新搜索")
                self._luokebei_detect_time = 0.0
                self._random_click(img)
                time.sleep(0.3)
                self._random_click(img)
                self._transition(SpectateState.SEARCH_BATTLE)
                return
        else:
            if self._luokebei_detect_time > 0 and self.frame_count % 5 == 0:
                print(f"[观战中] {elapsed:.0f}s  luokebei消失 score={luokebei_score:.3f}")
            self._luokebei_detect_time = 0.0
            # 每30s输出一次当前分数，方便确认模板是否有效
            if self.frame_count % 30 == 0:
                print(f"[观战中] {elapsed:.0f}s  luokebei当前={luokebei_score:.3f}")

    def state_battle_end(self, img: np.ndarray) -> None:
        """BATTLE_END: 点击屏幕关闭结算（避开举报按钮区域）。"""
        print(f"[结束] 点击屏幕关闭结算（避开举报按钮）...")
        self._click_avoid_jubao(img)
        time.sleep(1.0)
        self._click_avoid_jubao(img)
        time.sleep(0.5)
        self._transition(SpectateState.SEARCH_BATTLE)

    # ── 状态转换 ─────────────────────────────────

    def _transition(self, new_state: SpectateState) -> None:
        old = self.state
        # 离开移动状态时强制松W、重置瞄准
        if old in (SpectateState.AIM_AND_MOVE,):
            self._release_w()
            self._aim_done = False
            self._aim_iter = 0
            self.nihao_detect_time = 0.0
        # 离开观战重试状态时重置重试计数
        if old in (SpectateState.ENTER_SPECTATE, SpectateState.CHECK_PANEL):
            self._guanzhan_retries = 0
        self.state = new_state
        self.state_start_time = time.time()
        self.last_search_rotate = time.time()
        print(f"[状态] {old.value} → {new_state.value}")

    # ── 主循环 ─────────────────────────────────

    def run(self) -> None:
        """主入口。"""
        # 1. 找窗口
        if not self.find_and_bind_window():
            return

        # 2. 加载模板
        self.load_templates()
        if 'fight' not in self.templates:
            return

        # 3. 初始化 interception
        interception.auto_capture_devices()
        print("[输入] interception 已初始化")

        print("\n" + "=" * 50)
        print("  自动观战系统已启动")
        print(f"  按 Ctrl+C 退出")
        print("=" * 50 + "\n")

        self.state_start_time = time.time()

        # 启动缓冲：前2秒不处理帧，避免首帧误匹配
        print("[启动] 预热中 (2s)...")
        warmup_end = time.time() + 2.0
        while time.time() < warmup_end:
            time.sleep(0.1)

        # 启动检查：按优先级判断当前状态
        startup_img = self.capture()
        print(f"[启动] 判断当前游戏状态...")

        chat_score, _ = self.match_template(startup_img, 'chat')
        jubao_score, _ = self.match_template(startup_img, 'jubao')
        close_score, _ = self.match_template(startup_img, 'close')
        img_score, _ = self.match_template(startup_img, 'img')
        camera_score, _ = self.match_template(startup_img, 'camera')

        # 优先级1: chat — 正在观战/战斗中
        if chat_score >= MATCH_THRESHOLD_CHAT:
            print(f"[启动] 检测到观战/战斗中 (chat={chat_score:.3f})，直接进入观战监控")
            self._transition(SpectateState.SPECTATING)

        # 优先级2: close — 面板已打开
        elif close_score >= MATCH_THRESHOLD_PANEL:
            print(f"[启动] 检测到面板已打开 (close={close_score:.3f})，进入面板检测")
            self._transition(SpectateState.CHECK_PANEL)

        # 优先级3: jubao — 结算界面
        elif jubao_score >= MATCH_THRESHOLD:
            print(f"[启动] 检测到结算界面 (jubao={jubao_score:.3f})")
            self.jubao_pos = (0, 0)  # 位置不重要，click_avoid会避开
            self._transition(SpectateState.BATTLE_END)

        # 优先级4: 进入寻找阶段
        else:
            print(f"[启动] 进入寻找观战阶段")
            print(f"       chat={chat_score:.3f} jubao={jubao_score:.3f} close={close_score:.3f} img={img_score:.3f} camera={camera_score:.3f}")

        warmup_end = 0  # 预热完成，后续不再跳过

        try:
            while True:
                now = time.time()

                # 帧率控制
                if self.state == SpectateState.SPECTATING:
                    min_interval = 0.5  # 每0.5s一帧，及时检测luokebei
                elif self.state == SpectateState.ENTER_SPECTATE:
                    min_interval = 0.5  # 等待观战加载，0.5s检查一次
                elif self.state == SpectateState.SEARCH_BATTLE:
                    min_interval = SEARCH_INTERVAL
                elif self.state == SpectateState.AIM_AND_MOVE:
                    min_interval = AIM_INTERVAL
                else:
                    min_interval = 0.3  # CHECK_PANEL / BATTLE_END

                if now - self.last_frame_time < min_interval:
                    time.sleep(0.01)
                    continue
                self.last_frame_time = now

                # 检查窗口是否还存在
                if not self.is_window_valid():
                    print("[错误] 游戏窗口已关闭")
                    break

                # 检查焦点：不在游戏窗口则暂停
                fg_hwnd = win32gui.GetForegroundWindow()
                if fg_hwnd != self.hwnd:
                    if not self._paused:
                        self._release_w()
                        self._paused = True
                        print(f"[暂停] 游戏窗口失去焦点，等待恢复...")
                    time.sleep(0.5)
                    continue

                if self._paused:
                    self._paused = False
                    print(f"[恢复] 游戏窗口重新获得焦点")
                    # 重置方向状态，避免积累的旋转方向影响
                    self.rotate_dir = 0
                    self.rotate_same_dir_count = 0

                # 捕获画面
                img = self.capture()
                if img is None or img.size == 0:
                    continue

                self.frame_count += 1

                # 状态机调度
                if self.state == SpectateState.SEARCH_BATTLE:
                    self.state_search_battle(img)
                elif self.state == SpectateState.AIM_AND_MOVE:
                    self.state_aim_and_move(img)
                elif self.state == SpectateState.CHECK_PANEL:
                    self.state_check_panel(img)
                elif self.state == SpectateState.ENTER_SPECTATE:
                    self.state_enter_spectate(img)
                elif self.state == SpectateState.SPECTATING:
                    self.state_spectating(img)
                elif self.state == SpectateState.BATTLE_END:
                    self.state_battle_end(img)

        except KeyboardInterrupt:
            print("\n用户中断 (Ctrl+C)")
        except Exception as e:
            print(f"\n[异常] {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._release_w()
            print("系统已停止")


if __name__ == "__main__":
    app = AutoSpectate()
    app.run()
