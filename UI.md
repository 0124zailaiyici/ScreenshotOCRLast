# ScreenshotOCR UI 设计方案

本文档定义了 ScreenshotOCR 的视觉识别系统、组件规范及交互逻辑，旨在为开发提供一致的实现标准。

## 1. 设计目标与原则

- **极简高效**：减少用户从截图到获取结果的路径，核心功能一键直达。
- **原生感**：遵循 Windows 11 设计语言（Fluent UI），利用圆角、层级阴影和半透明效果。
- **专注度**：OCR 界面应保持高度的可读性，避免视觉噪音干扰文字校对。
- **稳定性**：由于使用纯 Tkinter，设计需兼顾跨 DPI 缩放的兼容性。

## 2. 全局样式定义

### 2.1 色彩系统 (Palette)

| 分类 | 变量名 | 颜色值 (Hex) | 用途 |
| :--- | :--- | :--- | :--- |
| **主色** | `--color-primary` | `System Accent` | 按钮、选中态、品牌色 (自动适配系统主题) |
| **背景** | `--color-bg-light` | `#F3F3F3` | 浅色模式背景 |
| **背景** | `--color-bg-dark` | `#202020` | 深色模式背景 |
| **表面** | `--color-surface-light` | `#FFFFFF` | 卡片、窗口表面 |
| **表面** | `--color-surface-dark` | `#2B2B2B` | 卡片、窗口表面 |
| **文本** | `--color-text-primary` | `#000000` | 主要正文 |
| **文本** | `--color-text-inverse` | `#FFFFFF` | 反色/暗色模式正文 |
| **状态** | `--color-success` | `#107C10` | 完成、成功提示 (识字功能主色) |
| **状态** | `--color-error` | `#D13438` | 错误、失败提示 |

### 2.2 视觉适配策略 (Adaptive Strategy)

- **背景适配**：截图覆盖层自动检测系统 Dark Mode。深色模式下使用 `black` (alpha 0.4) 遮罩；浅色模式下使用 `#F3F3F3` (alpha 0.3) 遮罩。
- **主题适配**：选区边框颜色实时获取 Windows 系统主题色 (Accent Color)，确保与 OS 视觉统一。
- **图标配色**：
  - `📌 钉住`：Hover 时使用 `--color-primary`。
  - `🔍 识字`：Hover 时使用 `--color-success`。
  - `📋 复制`：Hover 时使用 `--color-primary`。

### 2.2 字体层级 (Typography)

- **主字体**: `Microsoft YaHei UI`
  - **不要写 `Segoe UI`**：它**没有中文字形**，Tk 只能逐字回退，中英文混排时字重、字距、基线全都不一致（实测症状：中文明显比英文粗）。`Microsoft YaHei`（不带 ` UI`）这个名字在系统里**并不存在**，Tk 对不存在的字体名不报错、只静默回退 —— 回归防护见 `test_app.py::test_ui_font_family_is_actually_installed`。
- **等宽字体 (用于代码/OCR)**: `Consolas`, `Cascadia Mono`, `monospace`

字号用**点**（正数，Tk 会按 `tk scaling` 换算），间距一律过 `ui_theme.px()`（物理像素 = 逻辑像素 × DPI 系数）。

| 等级 | 磅值 (px) | 字重 (Weight) | 用途 |
| :--- | :--- | :--- | :--- |
| H1 | 24px | Semi-Bold | 窗口大标题 |
| H2 | 18px | Semi-Bold | 模块标题 |
| Body | 14px | Regular | 正文、输入框内容 |
| Small | 12px | Regular | 辅助文本、状态栏 |

### 2.3 间距与圆角 (Spacings & Radius)

- **基础间距**: `4px` (Base unit)
- **圆角**:
  - `Radius-S`: `4px` (小按钮、输入框)
  - `Radius-M`: `8px` (工具栏、弹窗)
  - `Radius-L`: `12px` (主窗口)

---

## 3. 基础组件规格

### 3.1 按钮 (IconButton)
用于工具栏和 OCR 操作区。

- **默认状态**: 背景透明，图标颜色 `--color-text-primary`。
- **悬停状态**: 背景 `#E5E5E5` (Light) / `#3D3D3D` (Dark)。
- **按下状态**: 背景缩放 0.95x。

**Tkinter 实现示例**:
```python
import tkinter as tk

class IconButton(tk.Label):
    def __init__(self, master, icon_text, command=None, **kwargs):
        super().__init__(master, text=icon_text, font=("Segoe UI Symbol", 12),
                         padx=8, pady=4, cursor="hand2", **kwargs)
        self.command = command
        self.bind("<Enter>", lambda e: self.config(bg="#E5E5E5"))
        self.bind("<Leave>", lambda e: self.config(bg=self.master.cget("bg")))
        self.bind("<Button-1>", self._on_click)

    def _on_click(self, event):
        if self.command: self.command()
```

---

## 4. 复合组件规格

### 4.1 浮动工具栏 (Floating Toolbar)
截图后出现在选区下方的操作条。

- **结构**: [钉住] | [识字] | [复制]
- **视觉**: `bg: #FFFFFF`, `border: 1px solid #CCCCCC`, `shadow: 0 4px 12px rgba(0,0,0,0.15)`
- **交互**: 自动避让屏幕边缘，随鼠标跟随或固定在选区右下角。

### 4.2 OCR 窗口 (OCR Window)
- **布局**: 顶部工具栏 (语言选择、翻译开关) + 中间双栏 (原文、译文) + 底部操作栏 (复制、保存)。
- **翻译状态**: 切换开关时，译文区域平滑展开。

### 4.3 右键菜单 (ContextMenu)

`ui_widgets.ContextMenu`，钉住窗口右键弹出。

- **结构**: 圆角卡片（`Radius-M`，`bg_card` 底色 + `border_card` 描边），条目之间可用 `None` 插入分隔线。
- **状态**: 悬停条目时内缩 `SPACE_XS` 高亮一块圆角（`bg_hover`）；分隔线不可点、不参与命中判定。
- **定位**: 在鼠标处弹出，**靠近屏幕边缘时自动往回收**，否则会被裁掉一半。同样走 `withdraw()` → 一次性 `geometry()` → `deiconify()`。
- **关闭路径有四条**：点中某项 / 点菜单矩形之外 / `Esc` / 焦点离开。前两条靠 `grab_set()`（应用内的点击都会被重定向到菜单窗口，即便点在别的窗口上、坐标也落在矩形外，**所以命中判定必须能识别出"点在外面"**）；第四条靠 `focus_force()` 之后的 `<FocusOut>` 兜底 —— 本地 grab 管不到应用外的点击。因此 `close()` **必须可重复调用**。
- **不用 `tk.Menu`**：它在 Windows 上不受系统深色主题控制，会弹出一个浅灰方块，是这个全自绘界面里唯一不搭的东西。

---

## 5. 页面级模板结构

### 5.1 全屏覆盖层 (Overlay)
- **背景**: `#000000` 且 alpha 为 `0.4`。
- **选区**: `canvas.create_rectangle` 带有白色虚线边框，内部镂空。

### 5.2 钉住窗口 (Pin Window)
- **特性**: `overrideredirect(True)` (无边框)，`topmost(True)` (置顶)。
- **交互**: 鼠标滚轮缩放图片，左键拖拽移动，**右键弹出菜单**，`Esc` 关闭。
- **右键菜单**（`ui_widgets.ContextMenu`，见 4.3）：
  - **复制图片** —— 复制**原始分辨率**的图，不是屏幕上缩放后的显示图。这个区别只有滚轮缩放过之后才暴露，所以回归防护里刻意先把图缩到 50%。
  - **识别文字…** —— 用原图重新识别并打开识字窗口，**识字窗口挂在钉住窗口的父窗口下**，否则关掉钉住会把它一起销毁。
  - 分隔线
  - **取消钉住** —— 不可逆，所以用分隔线单独隔开。

  > 右键**曾经是直接关闭窗口**，于是钉住的图既没法复制、也没法重新识别：想复制只能重新截一次，而截图工具栏是「钉住 / 识字 / 复制」三选一，不能都要。关闭因此收进了菜单里。
- **置顶定时器**: 每 2 秒把窗口抬到 `HWND_TOPMOST`，防止被其他置顶窗口盖住。**菜单打开时要暂停它**，否则会把刚弹出来的菜单盖住。

---

## 6. 交互状态与动效说明

| 动作 | 效果 | 时长 | 状态 |
| :--- | :--- | :--- | :--- |
| **显示工具栏** | 向上滑入 + 透明度渐变 | 200ms | **未实现**（直接显示） |
| **OCR 识别中** | 底部状态栏显示呼吸灯效果 | 循环 | **未实现**（显示静态文字「识别中…」） |
| **复制成功** | 按钮短暂变绿并恢复 | 500ms | **未实现**（弹托盘通知） |

**Tkinter 做不了透明度渐变**（没有 per-widget alpha），做这类动效需要叠一层 `-alpha` 的 Toplevel 或改用 Canvas 逐帧重绘，收益不值这个复杂度。**不要照着这张表去实现** —— 表里「未实现」的三项是设计初稿的设想，实际交互以 `README.md` 和代码为准。

---

## 7. 响应式与无障碍细则

- **DPI 适配**: 调用 `ctypes.windll.shcore.SetProcessDpiAwareness(1)` 确保 UI 在 125%/150% 缩放不模糊。
- **快捷键**: `Alt+X` (截图), `Esc` (退出截图), `Ctrl+C` (OCR 窗口内复制)。
- **高对比度**: 选区边框必须在深浅色背景下均可见 (双色描边)。

---

## 8. 交付物清单

- [x] UI.md 规范文档
- [x] 全局样式定义 (CSS/Python Const)
- [x] 核心组件代码片段
- [ ] 交互预览 (HTML 仿真) —— **未交付**，`preview.html` 不存在

### 8.1 开发交付格式 (Export Formats)

- **CSS Variables**: 可直接应用于 Web 预览或 Electron 迁移。
- **Python/Tkinter**: 核心实现方案。
- **React Component (Mockup)**:
```jsx
const ToolbarButton = ({ icon, label, onClick }) => (
  <button className="p-2 hover:bg-gray-100 rounded flex items-center gap-2" onClick={onClick}>
    <span>{icon}</span>
    <span className="text-sm">{label}</span>
  </button>
);
```
- **Vue Component (Mockup)**:
```vue
<template>
  <button @click="$emit('click')" class="btn-toolbar">
    <slot name="icon"></slot>
    <span>{{ label }}</span>
  </button>
</template>

<style scoped>
.btn-toolbar { /* 样式详见全局定义 */ }
</style>
```

### 8.2 版本记录

| 版本 | 日期 | 描述 | 负责人 |
| :--- | :--- | :--- | :--- |
| v1.0.0 | 2026-05-08 | 初始设计规范发布，包含核心组件与交互流程 | AI Assistant |
| v1.4.2 | 2026-10-14 | 新增 4.3 右键菜单组件；5.2 补上钉住窗口的右键菜单；修正字体（`Segoe UI` → `Microsoft YaHei UI`）；标注 6 中未实现的动效 | AI Assistant |

---

## 9. 与实现的偏差说明

本文档是**设计规范**，早期版本里有若干条目描述的是设想而非实现。已知偏差已就地标注，汇总如下：

| 位置 | 文档写的 | 实际 |
| :--- | :--- | :--- |
| 2.2 字体 | `Segoe UI`, `Microsoft YaHei` | `Microsoft YaHei UI` —— 前两个都不对（`Segoe UI` 无中文字形；`Microsoft YaHei` 这个名字系统里不存在） |
| 3.1 按钮 | 按下时背景缩放 0.95x | 未实现（Tk 标签没有 transform） |
| 4.1 工具栏 | 带 `box-shadow` | 未实现（Tk 没有阴影，用 `-transparentcolor` 抠圆角代替） |
| 6 动效 | 滑入 / 呼吸灯 / 变绿 | 三项均未实现，见该表「状态」列 |
| 8 交付物 | 交互预览 `preview.html` | **文件不存在**，从未创建 |

改这里之前先看 `CLAUDE.md` 的「已知注意事项」—— 那里记的是**实际踩过的坑**，优先级高于本文档。

---

## 附录：使用示例 (Python)

```python
# 初始化全局样式
STYLES = {
    "bg": "#F3F3F3",
    "primary": "#0078D4",
    "font_main": ("Microsoft YaHei UI", 10),
    "radius": 8
}

# 创建工具栏示例
def show_toolbar(x, y):
    root = tk.Toplevel()
    root.overrideredirect(True)
    root.geometry(f"120x40+{x}+{y}")
    root.config(bg="white")
    # 添加按钮...
```

---

## 交互预览 (Storybook 仿真)

**`preview.html` 从未创建** —— 本文档第 8 节的交付物清单里勾了它，但项目根目录下没有这个文件。想看真实界面就直接运行程序；`README.md` 的「界面」一节列了实际的样子。
