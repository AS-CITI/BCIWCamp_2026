"""
程式用途：肌電波 (EMG) 訊號模擬器
本程式用於在缺乏實體肌電感測器的環境下，模擬三通道的肌肉發力特徵。
透過獨立的 LSL (Lab Streaming Layer) ，以 1000Hz 的高採樣率持續廣播訊號。

開發者可透過鍵盤即時改變各通道的雜訊強度分佈，模擬不同手勢：
- 按住 [J] 模擬 GESTURE_1 
- 按住 [K] 模擬 GESTURE_2 
- 按住 [L] 模擬 GESTURE_3 
放開按鍵即自動恢復為baseline雜訊 (relax)。
可自行嘗試調整參數進行測試。
"""

import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock
from pynput import keyboard

# 硬體模擬參數
FS = 1000 
CH_COUNT = 3 
STREAM_NAME = 'EMG_stream' 

# 系統狀態
current_gesture = None

def on_press(key):
    global current_gesture
    try:
        if key.char == 'j': current_gesture = "GESTURE_1"
        elif key.char == 'k': current_gesture = "GESTURE_2"
        elif key.char == 'l': current_gesture = "GESTURE_3"
        
        if current_gesture:
            print(f"[狀態] 產生動作: {current_gesture}")
    except: pass

def on_release(key):
    global current_gesture
    try:
        if key.char in ['j', 'k', 'l']:
            current_gesture = None
            print("[狀態] 恢復放鬆 (relax)")
    except: pass

def start_emg_lsl():
    # 建立 LSL 資訊頭
    info = StreamInfo(STREAM_NAME, 'EMG', CH_COUNT, FS, 'float32', 'sim_emg_3gesture')
    
    # 建立 LSL 輸出端
    outlet = StreamOutlet(info)
    
    # 啟動鍵盤監聽
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print(f"EMG 3 通道多動作模擬啟動: {STREAM_NAME} (按 Ctrl+C 結束)")
    print("控制鍵: [J] GESTURE_1 | [K] GESTURE_2 | [L] GESTURE_3")

    while True:
        start_time = local_clock()
        
        if current_gesture == "GESTURE_1":
            # 模擬 GESTURE_1: 通道 1 與 2 強，通道 3 弱
            sample = [np.random.normal(0, 150), np.random.normal(0, 100), np.random.normal(0, 5)]
        elif current_gesture == "GESTURE_2":
            # 模擬 GESTURE_2: 通道 1 與 2 強，通道 3 弱 (模擬拇指發力特徵)
            sample = [np.random.normal(0, 100), np.random.normal(0, 150), np.random.normal(0, 5)]
        elif current_gesture == "GESTURE_3":
            # 模擬 GESTURE_3: 通道 2 與 3 強，通道 1 弱
            sample = [np.random.normal(0, 5), np.random.normal(0, 100), np.random.normal(0, 150)]
        else:
            # 模擬 relax: 基準線極小雜訊
            sample = np.random.normal(0, 0.5, CH_COUNT).tolist()
        
        # 推送樣本
        outlet.push_sample(sample)
        
        # 精準控制採樣率
        time.sleep(max(0, 1/FS - (local_clock() - start_time)))

if __name__ == "__main__":
    start_emg_lsl()