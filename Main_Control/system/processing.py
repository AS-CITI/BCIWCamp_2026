"""
程式用途：資料處理執行緒
本程式為背景執行緒，負責從 LSL 串流中同步抓取 EEG 與 EMG 數據。
它整合了：
1. EEG 訊號分析：使用 Welch PSD 計算 Alpha 波 (8-13Hz) 與 SSVEP (15Hz) 能量。
2. EMG 訊號分析：進行帶通與陷波濾波，計算包絡線 (Envelope)，並透過預訓練模型或能量門檻判定手勢。
處理後的狀態會存放在 status 字典中，供主控中心即時讀取。
"""

import threading
import time
import json
import os
import numpy as np
import mne
from collections import deque
from pylsl import StreamInlet, resolve_byprop

# 匯入 EMG 監聽與處理相關工具
from .listener.emg_listener import (
    connect_lsl1, personal_normalization, model_pred,
    bandpass_filter, notch_filter, calculate_envelope,
    WINDOW_SAMPLES, STEP_PASS_SAMPLES, STEP_FAIL_SAMPLES, 
    REQUIRED_RATIO, REQUIRED_CHANNELS
)

class SensorThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.status = {"EMG": "relax", "SSVEP": "None"}
        
        # 需連續出現 2 次相同結果才更新狀態
        self.debounce_len = 2 
        self.ssvep_history = deque(maxlen=self.debounce_len)
        
        # 載入硬體配置
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        config_path = os.path.join(parent_dir, "hardware_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        # 從配置中讀取 EEG 參數
        eeg_cfg = self.config.get("EEG", {})
        self.eeg_enabled = eeg_cfg.get("enabled", True)
        self.ssvep_on = eeg_cfg.get("ssvep_enabled", True)
        self.fs = eeg_cfg.get("sfreq", 1000)
        self.eeg_ch_names = eeg_cfg.get("channels", ["O1", "O2"])
        
        # 閾值設定
        self.alpha_th = eeg_cfg.get("alpha_threshold", 6.0)
        self.psd_15_th = eeg_cfg.get("psd_15_threshold", 0.0)

        # 初始化 LSL 
        self.eeg_inlet = None
        if self.eeg_enabled:
            try:
                streams = resolve_byprop('name', eeg_cfg.get("stream_name"), timeout=2.0)
                if streams:
                    self.eeg_inlet = StreamInlet(streams[0], max_buflen=360)
            except: pass

        self.emg_inlet = None
        self.user_scaler = None
        try:
            emg_cfg = self.config.get("EMG", {})
            self.emg_fs = emg_cfg.get("sfreq", 1000)
            self.emg_thresholds = np.array([emg_cfg.get("thresholds", {}).get(ch, 50) for ch in ["ch1", "ch2", "ch3"]])
            self.emg_inlet = connect_lsl1(stream_name=emg_cfg.get("stream_name"))
            
            # 嘗試載入個人正規化參數
            gesture_path = os.path.join(current_dir, "gesture_data.npz")
            if os.path.exists(gesture_path):
                self.user_scaler = personal_normalization(np.load(gesture_path)['gesture_data'])
        except: pass

    def _get_band_power(self, data, fmin, fmax):
        """利用 Welch 方法計算特定頻帶的平均能量 """
        if data.size <= 1 or data.shape[1] < self.fs: return -100.0
        try:
            psds, _ = mne.time_frequency.psd_array_welch(
                data.astype(float), self.fs, fmin=fmin, fmax=fmax, 
                n_fft=int(self.fs), verbose=False
            )
            return 10 * np.log10(np.mean(psds) + 1e-12)
        except: return -100.0

    def run(self):
        eeg_buf, emg_buf = [], []
        win_size = int(self.fs * 1.0) # 1秒分析視窗

        while self.running:
            # 1. EEG 處理邏輯
            if self.eeg_inlet:
                chunk, _ = self.eeg_inlet.pull_chunk(timeout=0.0)
                if chunk:
                    for s in chunk: eeg_buf.append(s[:len(self.eeg_ch_names)])
                
                if len(eeg_buf) >= win_size:
                    data = np.array(eeg_buf[-win_size:]).T
                    # 步進 0.5 秒進行下一次分析
                    eeg_buf = eeg_buf[int(self.fs * 0.5):] 
                    
                    alpha_db = self._get_band_power(data, 8, 13)
                    current_raw = "None"
                    
                    # 優先判定閉眼 (Alpha)
                    if alpha_db > self.alpha_th:
                        current_raw = "EYES_CLOSED"
                    elif self.ssvep_on:
                        p15_db = self._get_band_power(data, 14.5, 15.5)
                        if p15_db > self.psd_15_th:
                            current_raw = "SSVEP_15Hz"

                    # 累積結果進行平滑化
                    self.ssvep_history.append(current_raw)
                    if len(self.ssvep_history) == self.debounce_len:
                        # 緩衝區內所有結果一致時才更新狀態
                        if all(x == self.ssvep_history[0] for x in self.ssvep_history):
                            self.status["SSVEP"] = self.ssvep_history[0]

            # 2. EMG 處理邏輯
            if self.emg_inlet:
                chunk, _ = self.emg_inlet.pull_chunk(timeout=0.0)
                if chunk:
                    for s in chunk: 
                        emg_buf.append(s[:3])
                
                if len(emg_buf) >= WINDOW_SAMPLES:
                    seg = np.array(emg_buf[:WINDOW_SAMPLES])
                    filt, envs = [], []
                    
                    # 各通道獨立濾波與包絡線計算
                    for i in range(3):
                        f = bandpass_filter(seg[:, i], 20, 200, self.emg_fs, 6)
                        f = notch_filter(f, 60, 30, self.emg_fs)
                        filt.append(f)
                        envs.append(calculate_envelope(f))
                    
                    filt, envs = np.array(filt).T, np.array(envs).T
                    
                    # 檢查有效觸發點比例
                    valid = np.sum(np.sum(envs > self.emg_thresholds, axis=1) >= REQUIRED_CHANNELS)
                    ratio = valid / WINDOW_SAMPLES
                    
                    if ratio >= REQUIRED_RATIO:
                        if self.user_scaler:
                            try:
                                # 模型預測
                                self.status["EMG"] = model_pred(self.user_scaler.transform(filt))
                            except Exception:
                                self.user_scaler = None
                        else:
                            # 備援：依能量最大通道判定
                            current_energy = np.mean(envs, axis=0)
                            max_idx = np.argmax(current_energy)
                            fallback_gestures = ["GESTURE_1", "GESTURE_2", "GESTURE_3"]
                            self.status["EMG"] = fallback_gestures[max_idx] if max_idx < len(fallback_gestures) else "relax"
                        
                        emg_buf = emg_buf[STEP_PASS_SAMPLES:]
                    else:
                        self.status["EMG"] = "relax"
                        emg_buf = emg_buf[STEP_FAIL_SAMPLES:]

            time.sleep(0.001)

    def get_result(self):
        """回傳當前感測器狀態"""
        return self.status

    def stop(self):
        """終止執行緒"""
        self.running = False