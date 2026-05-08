import PyInstaller.__main__
import os
import sys

def build():
    # 确保在项目根目录运行
    base_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_path)

    print("正在开始打包 ScreenshotOCR...")
    
    params = [
        'main.py',              # 主程序入口
        '--name=ScreenshotOCR', # 生成的 exe 名称
        '--onefile',            # 打包成单文件
        '--noconsole',          # 运行时不显示控制台
        '--clean',              # 打包前清理临时文件
        
        # 强制包含的关键动态库
        '--hidden-import=pystray',
        '--hidden-import=pynput',
        '--hidden-import=pytesseract',
        '--hidden-import=win32clipboard',
        '--hidden-import=translators',
        '--hidden-import=PIL.ImageTk',
        
        # 排除不必要的超大库以减小体积
        '--exclude-module=matplotlib',
        '--exclude-module=notebook',
        '--exclude-module=pandas',
        '--exclude-module=scipy',
        '--exclude-module=torch',
        '--exclude-module=setuptools', # 避开沙盒环境中的版本解析 bug
    ]

    try:
        PyInstaller.__main__.run(params)
        print("\n" + "="*30)
        print("打包完成！")
        print(f"可执行文件位于: {os.path.join(base_path, 'dist', 'ScreenshotOCR.exe')}")
        print("你可以将该文件发送到桌面直接运行。")
        print("="*30)
    except Exception as e:
        print(f"打包失败: {e}")

if __name__ == "__main__":
    build()
