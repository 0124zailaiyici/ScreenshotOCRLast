# ScreenshotOCR

Windows 截图工具，支持截图后三选一操作：钉住到屏幕、OCR 识别文字、复制图片。常驻系统托盘，`Ctrl+Shift+A` 全局热键触发。

## 1. 项目背景

本项目旨在提供一个轻量级、无外部框架依赖的截图工具，支持以下核心流程：

- **全局触发**：通过 `Ctrl+Shift+A` 快速进入截图模式。
- **选区操作**：支持鼠标拖拽选择区域，并提供 \[钉住 | 识字 | 复制] 三合一工具栏。
- **高级 OCR 与翻译**：
  - **OCR**：集成 Tesseract 引擎进行离线识别。
  - **翻译**：支持多引擎翻译（默认阿里云），具备**语言自动检测**、**目标语言切换**及**本地历史记录**功能。
- **用户主控复制**：废弃自动复制。
- **系统集成**：常驻系统托盘，支持配置持久化。

## 2. 功能详细说明

### 2.1 OCR 识别与翻译

- **识别流程**：截图 -> 点击“识字” -> 弹出 OCR 窗口。
- **翻译增强**：
  - 支持 `zh`, `en`目标语言。
  - 自动检测源语言。
  - 翻译失败自动重试或弹出错误提示。
  - 翻译历史记录保存在 `translation_history.json`。

### 2.2 复制管理

- **手动触发**：OCR 识别后，用户需点击按钮才执行复制。
- **选择复制**：支持用鼠标选中特定行/词进行复制。


## 3. 安装与运行

### 环境要求

- Windows 10/11
- Python 3.10+
- **Tesseract-OCR 5.x**：
  - 请从 [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) 下载 Windows 安装包。
  - 安装时请勾选 **"Additional language data (download)"** 中的 **"Chinese"** 相关选项以支持中文识别。
  - 程序会自动尝试在 `C:\Program Files\Tesseract-OCR` 搜索，若安装在其他目录，请在程序提示时手动指定 `tesseract.exe` 路径。

### 快速开始
1. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```
2. **运行程序**：
   ```bash
   python main.py
   ```

### 打包为 EXE
如果你想在桌面直接点击运行，可以执行以下命令：
```bash
python build_exe.py
```
打包完成后，你可以在 `dist/` 目录下找到 `ScreenshotOCR.exe`。将它复制到桌面即可。
3. **运行测试**：
   ```bash
   pytest test_app.py
   ```

## 4. API 与模块说明

- **`translator.py`**: 提供 `translate_async(text, callback, error_callback, to_lang)` 接口。
- **`ocr_engine.py`**: 提供 `recognize(image)` 接口，返回识别文本。
- **`config.py`**: 管理 JSON 配置，支持 `set(key, value)` 和 `get(key)`。

## 5. 贡献指南 (Contribution)

欢迎通过以下方式参与贡献：
1. **提交 Issue**：报告 Bug 或提出新功能建议。
2. **提交 Pull Request**：
   - 请先 Fork 本仓库。
   - 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)。
   - 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)。
   - 推送到分支 (`git push origin feature/AmazingFeature`)。
   - 开启一个 Pull Request。

## 6. 许可证信息 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。

## 7. 更新日志 (Changelog)

### [v1.1.0] - 2026-05-08

- **\[Feature]** 实现完整的翻译功能模块，增加语言检测和多语言切换。
- **\[Feature]** 增加翻译历史记录功能（本地 JSON 持久化）。
- **\[Fix]** 修复 Tesseract 未安装时的崩溃问题，增加路径指引对话框。
- **\[Fix]** 修复多线程环境下 Tkinter 窗口销毁导致的 `TclError`。

***

