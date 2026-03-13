"""
程式用途：腦電波 (EEG) 訊號模擬器
本程式用於在缺乏實體生醫訊號擷取設備的環境下，模擬真實的腦波特徵，
我們平常在進行研究時，也會透過模擬訊號來測試系統。
透過獨立的 LSL (Lab Streaming Layer) ，以 1000Hz 的高採樣率持續廣播訊號。

開發者可透過鍵盤熱鍵即時注入特定頻率的波形：
- 按 [A] 持續注入 10Hz Alpha 波 (模擬閉眼放鬆)
- 按 [S] 持續注入 15Hz SSVEP 波 (模擬注視視覺刺激)
- 按 [W] 恢復純高斯雜訊 (基準線)
此模組確保系統能在離線狀態下進行完整的演算法與管線化測試。
"""

import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock
from pynput import keyboard

# 硬體模擬參數
FS = 1000 
CH_COUNT = 2 
STREAM_NAME = 'EEG_stream' 

# 系統狀態
current_state = "NORMAL"

def on_press(key):
    global current_state
    try:
        if key.char == 'a':
            current_state = "ALPHA"
            print("[狀態] 產生 10Hz Alpha 波")
        elif key.char == 's':
            current_state = "SSVEP"
            print("[狀態] 產生 15Hz SSVEP 波")
        elif key.char == 'w':
            current_state = "NORMAL"
            print("[狀態] 恢復背景雜訊")
    except:
        pass

def start_fake_lsl():
    # 建立 LSL 資訊頭
    info = StreamInfo(STREAM_NAME, 'EEG', CH_COUNT, FS, 'float32', 'sim_o1o2_2026')
    
    # 建立 LSL 輸出端
    outlet = StreamOutlet(info)
    
    # 啟動鍵盤監聽
    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    print(f"EEG 模擬訊號已啟動: {STREAM_NAME} (按 Ctrl+C 結束)")
    print("測試快捷鍵: [W] 基準值 | [A] 模擬閉眼波形 | [S] 模擬 15Hz 注視波形")

    t = 0
    while True:
        start_time = local_clock()
        
        # 產生基礎高斯雜訊
        sample = np.random.normal(0, 1.2, CH_COUNT)
        
        if current_state == "ALPHA":
            # 疊加 10Hz Alpha 波
            val = 20 * np.sin(2 * np.pi * 10 * t)
            sample += val
        elif current_state == "SSVEP":
            # 疊加 15Hz SSVEP 波
            val = 20 * np.sin(2 * np.pi * 15 * t)
            sample += val
        
        # 推送樣本
        outlet.push_sample(sample.tolist())
        
        t += 1 / FS
        
        # 精準控制採樣率
        time.sleep(max(0, 1 / FS - (local_clock() - start_time)))

if __name__ == "__main__":
    start_fake_lsl()