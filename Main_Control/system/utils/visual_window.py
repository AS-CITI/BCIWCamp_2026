"""
程式用途：視覺視窗管理工具 (Visual Window Manager)
本模組封裝了 PsychoPy 的 Window 物件，提供簡便的介面來管理 BCI 系統的視覺 UI。
包含：
1. 建立與關閉視窗：支援全螢幕、解析度與單位設定。
2. 文字顯示：支援位置、顏色、大小與顯示時間控制。
3. 倒數計時功能：用於在視覺刺激啟動前引導受試者。
4. 更新率偵測：獲取螢幕實際的 Frame Rate，供 SSVEP 閃爍精準計算使用。
"""

from typing import List
from psychopy import visual, event, core

class VisualWindow:
    def __init__(self, 
                 size=(1000, 800), 
                 monitor="testMonitor", 
                 units="height", 
                 color="black", 
                 fullscr=False,
                 allowGUI=True):
        """
        初始化視覺視窗
        """
        self.size = size
        self.window = visual.Window(
            size=size, 
            fullscr=fullscr, 
            monitor=monitor, 
            units=units, 
            color=color, 
            allowGUI=allowGUI
        )

    def display_text(self, text, pos=(0, 0), color="white", height=0.04, bold=False, 
                     wait_time=None, wait_for_key=False, clear_screen=False):
        """
        在螢幕上顯示文字提示
        
        :param text: 要顯示的文字內容
        :param pos: 文字位置 (預設為中心)
        :param color: 文字顏色
        :param height: 文字大小
        :param bold: 是否加粗
        :param wait_time: 顯示後停留的時間 (秒)
        :param wait_for_key: 是否等待使用者按鍵後才繼續
        :param clear_screen: 是否在顯示結束後清除畫面
        """
        text_stim = visual.TextStim(self.window, text=text, pos=pos, color=color, height=height, bold=bold)
        text_stim.draw()

        self.window.flip()
        
        if wait_time:
            core.wait(wait_time)
        
        if wait_for_key:
            event.waitKeys()
        
        if clear_screen:
            self.window.flip()

    def countdown(self, start=3, wait_time=1, height=0.5, color="white"):
        """
        顯示倒數計時數字
        
        :param start: 起始數字
        :param wait_time: 每個數字顯示的秒數
        :param height: 文字高度
        :param color: 文字顏色
        """
        for num in range(start, 0, -1):
            self.display_text(str(num), height=height, color=color, wait_time=wait_time, clear_screen=False)

        self.window.flip()

    def check_terminate(self):
        """
        檢查是否按下 'Escape' 鍵，若按下則結束程式
        """
        if 'escape' in event.getKeys():
            self.window.close()
            core.quit()
            return True
        return False

    def getKeys(self, key_list: List[str]):
        """取得特定按鍵清單的狀態"""
        return event.getKeys(key_list)
    
    def flip(self, clearBuffer=True):
        """重新整理視窗畫面"""
        self.window.flip(clearBuffer=clearBuffer)
            
    def terminate(self):
        """關閉視窗"""
        if self.window:
            self.window.close()

    def getActualFrameRate(self):
        """獲取螢幕實際的更新率 (Hz)"""
        return self.window.getActualFrameRate()