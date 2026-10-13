# ScreenshotOCR

Windows 截图工具，支持截图后三选一操作：钉住到屏幕、OCR 识别文字、复制图片。常驻系统托盘，`Alt+X` 全局热键触发。

## 1. 项目背景

本项目旨在提供一个轻量级、无外部框架依赖的截图工具，支持以下核心流程：

- **全局触发**：通过 `Alt+X` 快速进入截图模式。
- **选区操作**：支持鼠标拖拽选择区域，并提供 \[钉住 | 识字 | 复制] 三合一工具栏。
- **高级 OCR 与翻译**：
  - **OCR**：集成 Tesseract 引擎进行离线识别。
  - **翻译**：支持多引擎翻译（默认阿里云），具备**语言自动检测**、**目标语言切换**及**本地历史记录**功能。
- **用户主控复制**：废弃自动复制。
- **系统集成**：常驻系统托盘，支持配置持久化。

### 资源占用（实测）

打包后的 EXE 空转（未使用翻译）时：

| 指标 | 数值 |
|------|------|
| 工作集 | 约 50 ~ 60 MB |
| 私有内存 | 约 50 MB |
| 线程数 | 10 |
| **空闲 CPU** | **0.000%** |

OCR 引擎 `tesseract.exe` 是每次识别时 spawn 的子进程、用完即退，其内存不计入本进程。
翻译所用的 `translators` 库重达 48MB，已改为**首次点击翻译时**才加载，因此常驻期间不占用。

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
   pytest test_app.py test_integration.py test_pin_logic.py
   ```
   另可运行环境自检（失败返回非零退出码）：
   ```bash
   python verify_app.py
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

### [v1.2.3] - 2026-10-13

- **\[Fix]** 消除 OCR 时一闪而过的控制台窗口：pytesseract 的 `get_tesseract_version()` / `get_languages()` 用的是裸 `subprocess` 调用，而本程序是无控制台的 GUI 进程，Windows 会为子进程新建一个**可见**的控制台窗口。`ocr_engine` 现在把 `pytesseract.pytesseract.subprocess` 整体替换为注入 `CREATE_NO_WINDOW` 的版本（实测只有 `CREATE_NO_WINDOW` 可靠，`SW_HIDE` 不足）
- **\[Perf]** `is_available()` 按 tesseract 可执行文件路径缓存，不再每次识别都多 spawn 一次 tesseract 去查版本号（每次约省 500ms）
- **\[Perf]** `translators` 改为首次真正翻译时才导入：它一个包占 **48MB**（全程序内存的 80%）并拖慢启动 **2.4 秒**。打包后常驻内存 **119.8MB → 59.6MB**，启动快 2.4 秒
- **\[Fix]** 截图会话锁的遗留回收改为判断消费队列的 Tk 线程是否存活（v1.2.2 引入的 30s 超时会在锁仍被合法持有时强行释放，导致两个截图会话并发执行、后续 `release` 抛 `release unlocked lock`）
- **\[Test]** 测试增至 **31 个**，并新增两条回归防护（子进程必须无控制台窗口、translator 不得在导入期加载 translators）；测试套件由 3.26s 降至 1.20s

### [v1.2.2] - 2026-10-13

- **\[Fix]** 修复 Tk root 变化后图标缓存失效导致的 `TclError: image "pyimageN" doesn't exist`（缓存现在随 root 自动失效）
- **\[Fix]** 修复 OCR 识别失败被伪装成识别结果的问题，改为抛出 `OcrError` 并展示修复引导
- **\[Fix]** 修复钉住窗口的置顶定时器在关闭后不取消（每 2 秒空转的泄漏）
- **\[Fix]** 修复截图会话锁异常时不释放导致热键永久失效（新增 30s 超时强制回收）
- **\[Fix]** 修复翻译历史写在当前工作目录的问题，迁移到 `%APPDATA%/ScreenshotOCR/`，旧数据自动迁移
- **\[Fix]** 修复配置项被写坏类型时运行期崩溃，加载时按 schema 校验并回落默认值
- **\[Test]** 测试由 7 failed / 5 passed 修复为 23 passed；新增 hermetic 夹具，不再读写用户真实配置
- **\[Build]** `verify_app.py` 由硬编码假验证改为 13 项真实检查，失败返回非零退出码

### [v1.2.1] - 2026-05-09

- **\[Build]** 优化打包流程：使用独立 venv 构建，排除 Anaconda 环境的冗余库（sphinx/pytest/pandas 等），EXE 从 125MB 缩减至 30MB

### [v1.2.0] - 2026-05-09

- **\[UI]** 全新主题系统：支持深色/浅色模式自动切换，跟随系统主题色
- **\[UI]** PIL 程序化生成图标（图钉/放大镜/剪贴板/勾选），替换 emoji
- **\[UI]** 工具栏鲜艳配色：图钉/复制用主题色，识字用绿色，文字自适应黑白
- **\[UI]** 简化覆盖层：截图画面真实显示，无灰色/暗色遮罩
- **\[UI]** 系统托盘图标优化为相机形状，深色/浅色模式自适应
- **\[Fix]** 修复快速重复截图导致程序卡死的问题（Esc 取消链不完整）
- **\[Fix]** 修复第二次截图工具栏图标不显示（PhotoImage 缓存生命周期管理）
- **\[Fix]** 修复多次热键触发导致截图锁无法释放的问题

### [v1.1.0] - 2026-05-08

- **\[Feature]** 实现完整的翻译功能模块，增加语言检测和多语言切换。
- **\[Feature]** 增加翻译历史记录功能（本地 JSON 持久化）。
- **\[Fix]** 修复 Tesseract 未安装时的崩溃问题，增加路径指引对话框。
- **\[Fix]** 修复多线程环境下 Tkinter 窗口销毁导致的 `TclError`。

***

