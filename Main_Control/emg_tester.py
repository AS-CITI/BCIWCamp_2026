"""
程式用途：肌電波 (EMG) 即時訊號測試工具
本程式用於獨立驗證 EMG 訊號源 (真實硬體或 Generator) 與特徵萃取邏輯。
它會連接 LSL 網路，即時擷取 3 通道的 EMG 訊號，並執行帶通濾波、陷波濾波與包絡線計算。
系統會在終端機即時顯示各通道的能量值與當前判定的動作狀態，
可提供營隊進行電極貼片位置調整與觸發閾值 (Threshold) 測試，不發送車輛控制指令。
"""

import os
import sys
import time
import json
import numpy as np

# 處理相對路徑以匯入 system 模組
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from system.listener.emg_listener import (
    connect_lsl1, personal_normalization, model_pred,
    bandpass_filter, notch_filter, calculate_envelope,
    WINDOW_SAMPLES, STEP_PASS_SAMPLES, STEP_FAIL_SAMPLES, 
    REQUIRED_RATIO, REQUIRED_CHANNELS
)

def run_local_tester():
    # 載入硬體設定檔
    config_path = os.path.join(current_dir, "hardware_config.json")
    if not os.path.exists(config_path):
        print(f"錯誤：找不到設定檔 {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 取得 EMG 相關參數
    emg_cfg = config.get("EMG", {})
    fs = emg_cfg.get("sfreq", 1000)
    ch_names = emg_cfg.get("channels", ["ch1", "ch2", "ch3"])
    target_emg_name = emg_cfg.get("stream_name", "EMG_stream")
    
    # 建立通道閾值陣列
    thresholds = emg_cfg.get("thresholds", {name: 50 for name in ch_names})
    th_values = np.array([thresholds.get(ch, 50) for ch in ch_names])

    print(f"\n[EMG 即時測試模式]")
    print(f"目標串流: {target_emg_name}")
    print(f"通道閾值: {thresholds}\n")

    # 初始化 LSL 連線與正規化模型
    try:
        inlet = connect_lsl1(stream_name=target_emg_name)
        if inlet is None:
            print(f"錯誤：找不到 LSL 串流 '{target_emg_name}'，請確認訊號源已啟動。")
            return
        
        gesture_path = os.path.join(current_dir, "system", "gesture_data.npz")
        user_scaler = None
        if os.path.exists(gesture_path):
            gesture_data = np.load(gesture_path)['gesture_data']
            user_scaler = personal_normalization(gesture_data)
            print("成功載入個人正規化參數 (gesture_data.npz)")
        else:
            print(f"找不到 {gesture_path}，將使用純閾值判定模式。")

    except Exception as e:
        print(f"初始化失敗: {e}")
        return

    print("\n>>> 開始監控 (按 Ctrl+C 結束) <<<\n")
    emg_buffer = []
    
    try:
        while True:
            # 修改為 pull_chunk 以解決累積延遲問題
            chunk, _ = inlet.pull_chunk(timeout=0.0)
            if chunk:
                for s in chunk:
                    emg_buffer.append(s[:len(ch_names)])
                
            # 緩衝區累積至指定視窗長度才進行運算
            if len(emg_buffer) >= WINDOW_SAMPLES:
                segment = np.array(emg_buffer[:WINDOW_SAMPLES])
                
                envelopes = []
                filtered_list = []
                
                # 執行各通道的訊號前處理
                for idx, ch_name in enumerate(ch_names):
                    # 20-200Hz 帶通濾波 + 60Hz 陷波濾波
                    ch_data = bandpass_filter(segment[:, idx], lowcut=20, highcut=200, fs=fs, order=6)
                    ch_data = notch_filter(ch_data, f0=60, Q=30, fs=fs)
                    filtered_list.append(ch_data)
                    envelopes.append(calculate_envelope(ch_data))
                
                envelopes = np.array(envelopes).T
                filtered_data = np.array(filtered_list).T

                # 計算超越閾值的比例 
                over_threshold_count = np.sum(envelopes > th_values, axis=1)
                valid_points = np.sum(over_threshold_count >= REQUIRED_CHANNELS)
                ratio = valid_points / WINDOW_SAMPLES
                
                # 計算當前視窗平均能量
                current_energy = np.mean(envelopes, axis=0)
                energy_str = " | ".join([f"{ch}: {val:5.1f}" for ch, val in zip(ch_names, current_energy)])
                
                # 輸出判定結果
                if ratio >= REQUIRED_RATIO:
                    if user_scaler:
                        try:
                            # 預訓練模型預測
                            norm_data = user_scaler.transform(filtered_data)
                            gesture = model_pred(norm_data)
                            sys.stdout.write(f"\r[模型] {gesture:10s} | 能量: [{energy_str}] | 觸發率: {ratio:.2f}")
                        except Exception:
                            user_scaler = None 
                    else:
                        # 閾值判定
                        max_idx = np.argmax(current_energy)
                        fallback_gestures = ["GESTURE_1", "GESTURE_2", "GESTURE_3"]
                        gesture = fallback_gestures[max_idx] if max_idx < len(fallback_gestures) else "unknown"
                        sys.stdout.write(f"\r[閾值] {gesture:10s} | 能量: [{energy_str}] | 觸發率: {ratio:.2f}")
                    
                    sys.stdout.flush()
                    emg_buffer = emg_buffer[STEP_PASS_SAMPLES:]
                else:
                    # 放鬆狀態
                    sys.stdout.write(f"\r[放鬆] 等待觸發... | 能量: [{energy_str}] | 觸發率: {ratio:.2f}      ")
                    sys.stdout.flush()
                    emg_buffer = emg_buffer[STEP_FAIL_SAMPLES:]
            
            time.sleep(0.001)
            
    except KeyboardInterrupt:
        print("\n\n測試結束。")

if __name__ == "__main__":
    run_local_tester()