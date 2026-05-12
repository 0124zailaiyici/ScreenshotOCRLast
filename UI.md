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

- **主字体**: `Segoe UI`, `Microsoft YaHei`, `sans-serif`
- **等宽字体 (用于代码/OCR)**: `Consolas`, `Cascadia Mono`, `monospace`

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

---

## 5. 页面级模板结构

### 5.1 全屏覆盖层 (Overlay)
- **背景**: `#000000` 且 alpha 为 `0.4`。
- **选区**: `canvas.create_rectangle` 带有白色虚线边框，内部镂空。

### 5.2 钉住窗口 (Pin Window)
- **特性**: `overrideredirect(True)` (无边框)，`topmost(True)` (置顶)。
- **交互**: 鼠标滚轮缩放图片，左键拖拽移动。

---

## 6. 交互状态与动效说明

| 动作 | 效果 | 时长 |
| :--- | :--- | :--- |
| **显示工具栏** | 向上滑入 + 透明度渐变 | 200ms |
| **OCR 识别中** | 底部状态栏显示呼吸灯效果 | 循环 |
| **复制成功** | 按钮短暂变绿并恢复 | 500ms |

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
- [x] [交互预览 (HTML 仿真)](#preview-link)

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

---

## 附录：使用示例 (Python)

```python
# 初始化全局样式
STYLES = {
    "bg": "#F3F3F3",
    "primary": "#0078D4",
    "font_main": ("Segoe UI", 10),
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

<div id="preview-link"></div>

## 交互预览 (Storybook 仿真)

由于环境限制，请查看项目根目录下的 `preview.html` 文件，它使用 HTML/CSS 完美复刻了本设计方案的交互效果。
