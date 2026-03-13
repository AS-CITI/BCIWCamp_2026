"""
程式用途：SSVEP 視覺閃爍控制器 (線上模式)
透過 PsychoPy 提供穩定頻率的視覺刺激。
已移除離線實驗紀錄、標記 (Marker) 與不良資料追蹤邏輯，
專供即時線上控制介面使用。
"""

from psychopy import visual, core
import numpy as np

class FlickerController:
    def __init__(self, visual_window, shapes, instruction_shapes=None, outlet=None):
        self.visual_window = visual_window
        self.frame_rate = self._get_frame_rate()
        self.outlet = outlet

        print(f"[UI] 偵測到螢幕更新率: {self.frame_rate:.2f} Hz")

        self.shapes = []
        for shape_data in shapes:
            shape = visual.ShapeStim(
                self.visual_window.window, vertices=shape_data["vertices"],
                fillColor=shape_data.get("color", "white"),  
                lineColor=None,  
                size=shape_data.get("size", 0.1),
                pos=shape_data.get("pos", (0, 0))
            )
            shape.opacity = 0
            shape.autoDraw = False
            hz = shape_data.get("hz", 0)
            phase = shape_data.get("phase", 0)
            self.shapes.append({
                "shape": shape, 
                "hz": hz,
                "frame_opacities": self._create_frame_opacities(hz, phase) if hz > 0 else None
            })

        self.timer = core.Clock() 
        self.frame_count = 0 

    def _get_frame_rate(self):
        """偵測並取得 PsychoPy 視窗的實際更新率"""
        frame_rate = self.visual_window.getActualFrameRate()
        if frame_rate is None or frame_rate <= 0:
            print("[UI] 警告：無法偵測更新率，預設為 60.00 Hz")
            return 60.0
        return frame_rate

    def _create_frame_opacities(self, hz, phase=0):
        """利用正弦波預先計算單一週期內各幀的透明度"""
        if hz == 0: return None
        frames_per_cycle = int(self.frame_rate / hz)
        t = np.linspace(0, 1/hz, frames_per_cycle)
        return 0.5 * (1 + np.sin(2 * np.pi * hz * t + phase * np.pi))

    def flicker(self, max_duration=None, instruction="ONLINE"):
        """執行線上控制的連續閃爍迴圈"""
        self.timer.reset()  
        self.frame_count = 0 
        ret_message = "OK"

        try:
            start_time = self.timer.getTime() 
            
            while max_duration is None or (self.timer.getTime() - start_time) < max_duration:
                for shape_data in self.shapes:
                    shape = shape_data["shape"]
                    if shape_data["hz"] == 0:
                        shape.opacity = 1
                    else:
                        frame_opacities = shape_data["frame_opacities"]
                        shape.opacity = frame_opacities[self.frame_count % len(frame_opacities)]
                    shape.draw()
                
                # 繪製中央注視十字
                text_stim = visual.TextStim(
                    self.visual_window.window, text="+", 
                    pos=(0, 0), color="white", height=0.06, bold=True
                )
                text_stim.draw()

                self.visual_window.flip()
                self.frame_count += 1

                # 檢查手動退出指令
                if self.visual_window.getKeys(["escape", "q"]):
                    print("[UI] 閃爍已手動終止")
                    ret_message = "ESCAPE"
                    break
                
        except KeyboardInterrupt:
            print("[UI] 閃爍被中斷")
            ret_message = "INTERRUPTED"
        except Exception as e:
            print(f"[UI] 閃爍發生異常: {e}")
            ret_message = "EXCEPTION"

        return ret_message
    
    def end_experiment(self):
        """結束視覺刺激並關閉視窗"""
        self.visual_window.display_text("System Offline", wait_time=2, height=0.065, clear_screen=True, bold=True)
        self.visual_window.terminate()