"""
程式用途：腦電波 (EEG) 即時訊號測試工具
本程式用於獨立驗證 EEG 訊號源（真實硬體或模擬訊號）與頻帶分析邏輯。
系統會透過 LSL 接收腦波資料塊 (Chunk)，並在畫面上渲染 15Hz 的視覺閃爍刺激。
程式以 50 毫秒為週期，即時計算 1 秒緩衝區內的 Alpha 波與 15Hz SSVEP 頻帶能量，
並在終端機顯示判定結果，供調校閾值與確認訊號品質使用，不發送車輛控制指令。

***若有大腦相關病史，不建議觀看閃爍刺激。***
"""

import numpy as np
import mne
import json
import os
import sys
import time
from collections import deque
from pylsl import StreamInlet, resolve_byprop
from psychopy import visual, event

from system.utils.visual_window import VisualWindow
from system.utils.flicker import FlickerController

FONT = "Microsoft JhengHei"

def load_config():
    """載入硬體設定檔"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "hardware_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_band_power(data, fs, fmin, fmax):
    """使用 Welch PSD 計算指定頻帶能量 (1秒視窗)"""
    if data.shape[1] < fs: return -100.0
    try:
        psds, _ = mne.time_frequency.psd_array_welch(
            data.astype(float), fs, fmin=fmin, fmax=fmax, 
            n_fft=int(fs), verbose=False
        )
        return 10 * np.log10(np.mean(psds) + 1e-12)
    except: return -100.0

def main():
    config = load_config()
    eeg_cfg = config["EEG"]
    fs = eeg_cfg.get("sfreq", 1000)
    ch_count = len(eeg_cfg.get("channels", ["O1", "O2"]))
    
    # 與線上控制策略同步的閾值
    alpha_th = eeg_cfg.get("alpha_threshold", 6.0)
    psd15_th = eeg_cfg.get("psd_15_threshold", 0.0)

    # 解析 LSL 串流
    streams = resolve_byprop('name', eeg_cfg['stream_name'], timeout=5.0)
    if not streams: return
    inlet = StreamInlet(streams[0])

    # 初始化視覺視窗與閃爍控制器
    visual_win = VisualWindow(size=(1280, 720), fullscr=False, units="height")
    sq_cfg = {"size": 0.3, "color": [1, 1, 1], "vertices": [(-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5), (0.5, 0.5)]}
    flicker_ctrl = FlickerController(visual_win, [{"hz": 15.0, "pos": (0, 0), **sq_cfg}], [])
    
    # 固定 1 秒緩衝區以確保頻率解析度
    win_samples = int(fs * 1.0) 
    eeg_buffer = deque(maxlen=win_samples)
    
    # 與線上控制週期同步 (50ms)
    update_interval = 0.05 
    last_update_time = time.time()
    frame_idx = 0

    print("\n[Alpha & 15Hz PSD 測試 (按 Ctrl+C 結束)]")
    print(f"Alpha 閾值: {alpha_th:4.1f} | 15Hz 閾值: {psd15_th:4.1f} | 更新間隔: {update_interval}s")

    try:
        while True:
            for shape_data in flicker_ctrl.shapes:
                shape, opacities = shape_data["shape"], shape_data["frame_opacities"]
                shape.opacity = opacities[frame_idx % len(opacities)]
                shape.draw()
            visual_win.flip()
            frame_idx += 1

            # 從 LSL 抓取資料塊
            chunk, _ = inlet.pull_chunk(timeout=0.0)
            if chunk:
                for s in chunk: eeg_buffer.append(s[:ch_count])

            # 處理邏輯與線上循環同步
            current_time = time.time()
            if len(eeg_buffer) == win_samples and (current_time - last_update_time) >= update_interval:
                data = np.array(eeg_buffer).T
                
                # 頻帶分析
                alpha_val = get_band_power(data, fs, 8, 13)
                psd15_val = get_band_power(data, fs, 14.5, 15.5)

                # 優先判定 Alpha (停止) 高於 SSVEP (動作)
                alpha_hit = alpha_val > alpha_th
                psd15_hit = psd15_val > psd15_th
                
                # 終端機 UI 顯示
                res = 'ALPHA' if alpha_hit else '15Hz' if psd15_hit else 'IDLE'
                sys.stdout.write(f"\r 指令: {res:2} | Alpha: {alpha_val:5.1f} | 15Hz: {psd15_val:5.1f}")
                sys.stdout.flush()
                
                last_update_time = current_time

            if 'escape' in event.getKeys(): break
    finally:
        visual_win.terminate()

if __name__ == "__main__":
    main()