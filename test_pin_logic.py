import pytest
import tkinter as tk
from PIL import Image
from pin_window import PinWindow
import random

@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()

def test_pin_window_jitter(tk_root):
    """验证需求 1: 钉住后位置偏移不超过 10px"""
    img = Image.new('RGB', (100, 100))
    coords = (100, 100, 200, 200)
    
    # 运行多次以验证随机偏移范围
    for _ in range(20):
        win = PinWindow(img, coords=coords, master=tk_root)
        win.root.update()
        
        curr_x = win.root.winfo_x()
        curr_y = win.root.winfo_y()
        
        # 允许 ±10px 偏移
        assert abs(curr_x - coords[0]) <= 10
        assert abs(curr_y - coords[1]) <= 10
        
        win._on_close()

def test_pin_window_boundary(tk_root):
    """验证需求 2: 边界检测确保窗口在屏幕内"""
    img = Image.new('RGB', (100, 100))
    
    # 模拟在屏幕边缘截图 (假设屏幕 1920x1080)
    screen_w = tk_root.winfo_screenwidth()
    screen_h = tk_root.winfo_screenheight()
    
    # 右下角坐标
    coords = (screen_w - 50, screen_h - 50, screen_w, screen_h)
    
    win = PinWindow(img, coords=coords, master=tk_root)
    win.root.update()
    
    curr_x = win.root.winfo_x()
    curr_y = win.root.winfo_y()
    
    # 窗口不应超出右边界
    assert curr_x + 100 <= screen_w
    # 窗口不应超出下边界
    assert curr_y + 100 <= screen_h
    
    win._on_close()

def test_pin_window_no_overlap(tk_root):
    """验证需求 3: 避免与其他钉住窗口重叠"""
    img = Image.new('RGB', (50, 50))
    coords = (200, 200, 250, 250)
    
    # 创建第一个窗口
    win1 = PinWindow(img, coords=coords, master=tk_root)
    win1.root.update()
    
    # 在相同位置创建第二个窗口
    win2 = PinWindow(img, coords=coords, master=tk_root)
    win2.root.update()
    
    x1, y1 = win1.root.winfo_x(), win1.root.winfo_y()
    x2, y2 = win2.root.winfo_x(), win2.root.winfo_y()
    
    # 验证位置不完全重合且偏移了至少重叠检测步长 (20px) 或随机抖动
    # 由于有随机抖动，我们检查 AABB 是否重叠
    w1, h1 = win1.root.winfo_width(), win1.root.winfo_height()
    w2, h2 = win2.root.winfo_width(), win2.root.winfo_height()
    
    is_overlapping = (x1 < x2 + w2 and
                     x1 + w1 > x2 and
                     y1 < y2 + h2 and
                     y1 + h1 > y2)
    
    assert not is_overlapping
    
    win1._on_close()
    win2._on_close()

def test_pin_window_zoom_stability(tk_root):
    """验证缩放后位置逻辑稳定性"""
    img = Image.new('RGB', (100, 100))
    coords = (300, 300, 400, 400)
    win = PinWindow(img, coords=coords, master=tk_root)
    win.root.update()
    
    pos_before_x = win.root.winfo_x()
    pos_before_y = win.root.winfo_y()
    
    # 模拟滚轮放大
    class MockEvent:
        delta = 120
    win._on_zoom(MockEvent())
    win.root.update()
    
    # 缩放后窗口左上角位置应保持不变（Tkinter geometry 行为）
    assert win.root.winfo_x() == pos_before_x
    assert win.root.winfo_y() == pos_before_y
    
    win._on_close()

if __name__ == "__main__":
    pytest.main([__file__])
