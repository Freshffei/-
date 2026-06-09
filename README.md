# RocoView — 洛克王国世界自动观战

> **输入方案**：基于 Interception 驱动级输入，在内核层面模拟键鼠，游戏反作弊无法检测。

OpenCV 模板匹配驱动的自动观战系统，专为《洛克王国：世界》设计。状态机控制完整流程：搜索战斗标记 → 瞄准靠近 → 进入观战 → 监控战斗结束 → 循环。

---

## 快速开始

### 1. 安装 Interception 驱动

Interception 是内核级输入驱动，游戏无法感知模拟输入，**必须先装**。

1. 访问 [Interception Releases](https://github.com/oblitum/Interception/releases/tag/v1.0.1)
2. 下载 `Interception.zip` 并解压到任意目录
3. **以管理员身份**打开终端（`Win+X` → 终端(管理员)），进入解压目录
4. 运行命令：
   ```powershell
   .\install-interception.exe /install
   ```
5. 看到 `Success` 提示后，**重启电脑**
6. 重启后在终端运行以下命令验证：
   ```powershell
   sc query interception
   ```
   状态显示 `RUNNING` 即安装成功

### 2. 安装 Python 依赖

```powershell
pip install opencv-python numpy pywin32 interception-python
```

### 3. 启动

启动游戏，进入可找到观战场景的区域，**以管理员身份**运行：

```powershell
python auto_spectate.py
```

按 `Ctrl+C` 退出。

---

## 运行环境

| 项目 | 配置 |
|------|------|
| 操作系统 | Windows 10/11 64-bit |
| 权限 | **管理员权限**（Interception 驱动需要） |
| Python | 3.11+ |
| 游戏分辨率 | 1920×1080（其他分辨率需重新截图模板） |

---

## 工作原理

### 状态机流程

```
SEARCH_BATTLE ──发现zhandou──→ AIM_AND_MOVE
      ↑                            │
      │                      一次转到位+前进0.5s
      │                      检测nihao → 按F交互
      │                            │
      │                            ↓
      │                       CHECK_PANEL
      │                      匹配guanzhan → 点击
      │                            │
      │                            ↓
      │                      ENTER_SPECTATE
      │                      等待chat加载(6s)
      │                      观战成功 / 重试
      │                            │
      │                            ↓
      │                       SPECTATING
      │                      检测luokebei稳定5s
      │                      战斗结束 → 点击屏幕
      │                            │
      └────────────────────────────┘
```

### 各状态说明

| 状态 | 触发 | 行为 |
|------|------|------|
| SEARCH_BATTLE | 初始 / 循环返回 | 多模板匹配 zhandou 和 watching；有目标→锁定瞄准；无目标→右转搜索 |
| AIM_AND_MOVE | zhandou 匹配成功 | 检测偏移→一次转到位→前进 0.5s→判断 nihao；无 nihao 则回搜索重找 |
| CHECK_PANEL | nihao 稳定后按 F | 匹配 guanzhan（阈值 0.80）→点击进入观战；无 guanzhan→ESC 脱离 |
| ENTER_SPECTATE | 点击 guanzhan 后 | 等待 6s 检测 chat 确认观战成功；8s 后 guanzhan 还在则重试（最多 2 次）；失败 ESC 脱离 |
| SPECTATING | 进入观战 | 每 0.5s 检测 luokebei（阈值 0.6）；稳定 5s→战斗结束→随机点击关闭结算→回搜索 |

### 辅助机制

- **多模板支持**：`zhandou.png` / `zhandou_2.png` / `zhandou_3.png` 等，匹配动态变化的图标
- **卡死检测**：检测到 `map.png` 自动按 ESC 解除
- **相机矫正**：每 120s 自动 ESC→等待 2s 修正→ESC 退出，保持视角水平
- **面板脱离**：按 ESC + 随机方向键，并通过 `close.png` 循环确认面板已关闭
- **焦点检测**：窗口失去焦点时自动暂停，恢复后继续

---

## 模板文件

所有模板位于 `templates/` 目录：

| 模板 | 用途 | 阈值 |
|------|------|------|
| `zhandou.png` | 远处战斗标记（搜索目标） | 0.78 |
| `watching.png` | 观战玩家位置标记（辅助搜索） | 0.78 |
| `nihao.png` | 靠近后的交互提示 | 0.90 |
| `guanzhan.png` | 面板上的观战按钮 | 0.80 |
| `close.png` | 面板关闭按钮（确认面板状态） | 0.70 |
| `chat.png` | 观战界面标识（确认进入观战） | 0.50 |
| `luokebei.png` | 战斗结束标识 | 0.60 |
| `map.png` | 地图界面（卡死检测） | 0.70 |

> 多帧模板命名规则：`{名称}_2.png`、`{名称}_3.png`……脚本自动扫描同名前缀的所有文件。

---

## 项目结构

```
├── auto_spectate.py      # 主程序：自动观战状态机
├── capture_window.py     # Win32 窗口查找和截图
├── realtime_detect.py    # 模板匹配实时预览工具
├── build_exe.py          # PyInstaller 打包脚本
├── Identify_fight.py     # 战斗标记识别测试
├── Identify_hello.py     # 交互提示识别测试
├── Identify_view.py      # 观战按钮识别测试
├── Identify_jubao.py     # 举报按钮识别测试
├── Identify_luokebei.py  # 战斗结束标识识别测试
├── Identify_watching.py  # 观战玩家标记识别测试
├── templates/            # 模板图片
├── img/                  # 测试用截图
└── dist/                 # 打包输出
```

## 配置项

关键参数位于 `auto_spectate.py` 顶部：

```python
MATCH_THRESHOLD = 0.78           # 噪声地板~0.72
MATCH_THRESHOLD_NIHAO = 0.90
MATCH_THRESHOLD_GUANZHAN = 0.80
MATCH_THRESHOLD_LUOKEBEI = 0.6
MATCH_THRESHOLD_MAP = 0.7

AIM_TIMEOUT = 15.0               # 瞄准超时
SEARCH_INTERVAL = 0.12           # 搜索帧间隔
AIM_WALK_DURATION = 0.5          # 每次前进时长
SPECTATE_CHECK_INTERVAL = 3.0    # 观战检查间隔
```

## 免责声明

1. **仅供学习参考**：本工具仅用于计算机视觉（OpenCV 模板匹配）及输入模拟技术的研究与交流。
2. **驱动风险**：使用 Interception 内核级驱动模拟键鼠输入，请从 [官方仓库](https://github.com/oblitum/Interception) 下载。
3. **账号风险**：使用自动化脚本可能违反《洛克王国：世界》用户协议，存在被警告、限制或封禁的风险。**由此产生的一切后果由使用者本人承担。**
4. **技术边界**：本工具不修改游戏内存、不篡改网络封包、不注入游戏进程。所有操作基于截屏 → 图像分析 → 模拟外设输入。
