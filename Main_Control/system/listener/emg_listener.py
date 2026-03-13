"""
程式用途：肌電訊號 (EMG) 監聽與底層處理工具
本模組提供 EMG 訊號處理的核心演算法，包含：
1. 訊號濾波：帶通濾波 (20-200Hz) 與陷波濾波 (60Hz) 以消除雜訊與工頻干擾。
2. 特徵萃取：計算訊號包絡線 (Envelope) 並評估肌肉發力強度。
3. LSL 通訊：負責建立與 EMG 硬體裝置的連線。
4. 模型支援：提供資料正規化 (Normalization) 與手勢模型預測所需的預處理函式。
"""

from pylsl import StreamInlet, resolve_byprop
import numpy as np
import time
from scipy.signal import butter, filtfilt, iirnotch
from sklearn.preprocessing import StandardScaler

# 核心參數設定
CHANNELS_USED = [0, 1, 2]
CHANNELS_NAMES = ["ch1", "ch2", "ch3"]
SAMPLE_RATE = 1000
WINDOW_SAMPLES = int(500 / 1000 * SAMPLE_RATE)  # 分析視窗長度：500ms
STEP_PASS_MS = 1000                             # 判定成功後的跳轉位移
STEP_FAIL_MS = 100                              # 判定失敗後的跳轉位移
STEP_PASS_SAMPLES = int(STEP_PASS_MS / 1000 * SAMPLE_RATE)
STEP_FAIL_SAMPLES = int(STEP_FAIL_MS / 1000 * SAMPLE_RATE)

# 判定邏輯參數
THRESHOLDS = {"ch1": 50, "ch2": 50, "ch3": 50}
REQUIRED_RATIO = 0.3     # 有效發力點需佔視窗 30% 以上
REQUIRED_CHANNELS = 2    # 需至少 2 個通道同時觸發
TH_MULTIPLIER = 5        # 自動閾值倍率

# 模型相關全域變數
MODEL_NAME = "./emg_model/gestures_model.keras"
LABEL_ENCODER_NAME = "./emg_model/gestures.pkl"
MODEL = None # 線下版本移除 model
LABEL_ENCODER = None # 線下版本移除 label encoder

# 訊號處理函式

def bandpass_filter(data, lowcut, highcut, fs, order):
    """帶通濾波：保留指定頻率範圍內的肌電訊號"""
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut/nyq, highcut/nyq], btype='band')
    return filtfilt(b, a, data)

def notch_filter(data, f0, Q, fs):
    """陷波濾波：消除特定頻率(如 60Hz 電源)的干擾"""
    b, a = iirnotch(f0, Q, fs)
    return filtfilt(b, a, data)

def calculate_envelope(signal, cutoff=5):
    """計算訊號包絡線：將原始震盪訊號轉化為平滑的發力強度曲線"""
    abs_signal = np.abs(signal)
    b, a = butter(N=2, Wn=cutoff / (0.5 * SAMPLE_RATE), btype='low')
    return filtfilt(b, a, abs_signal)

# 網路連線函式 

def connect_lsl1(stream_name="Cygnus-Default"):
    """建立 LSL 連線：搜尋並連接指定的 EMG 串流名稱"""
    print(f"正在尋找 EMG stream: {stream_name}")
    streams = resolve_byprop('name', stream_name, timeout=5.0) 
    
    if len(streams) > 0:
        inlet = StreamInlet(streams[0])
        print(f"已連接 EMG stream: {stream_name}")
        return inlet
    else:
        print(f"找不到裝置: {stream_name}")
        return None

# 基準線與正規化函式

def baseline_threshold(data, channel_names):
    """基準線計算：根據靜止狀態下的訊號雜訊決定觸發門檻"""
    for idx, ch_name in enumerate(channel_names):
        # 進行基本的去噪處理
        ch_data = notch_filter(data[:, idx], f0=60, Q=30, fs=SAMPLE_RATE)
        ch_data = bandpass_filter(ch_data, lowcut=20, highcut=50, fs=SAMPLE_RATE, order=6)
        env = calculate_envelope(ch_data)
        # 預設使用固定門檻 50，可依需求開啟自動計算邏輯
        THRESHOLDS[ch_name] = 50
        # THRESHOLDS[ch_name] = np.median(env) * TH_MULTIPLIER
    print("Baseline Thresholds 設定完畢: ", THRESHOLDS)
    time.sleep(2)

def record_baseline(inlet, BASELINE_SEC):
    """自動錄製基準線資料"""
    print(f"開始錄製基準線，請保持放鬆 {BASELINE_SEC} 秒...")
    baseline_data = []
    start_time = time.time()
    while time.time() - start_time < BASELINE_SEC:
        sample, _ = inlet.pull_sample()
        if sample:
            baseline_data.append([sample[i] for i in CHANNELS_USED])
    baseline_data = np.array(baseline_data)
    baseline_threshold(baseline_data, CHANNELS_NAMES)

def personal_normalization(data):
    """個人化正規化：將不同受試者的發力強度映射至相同的數值特徵空間"""
    data = np.array(data)
    num_group, samples_per_group, num_channel = data.shape
    data_reshaped = data.reshape(-1, num_channel)
    scaler = StandardScaler()
    scaler.fit(data_reshaped)
    return scaler

# 模型預測函式

def model_pred(buffer_data):
    """模型預測：將預處理後的視窗資料輸入神經網路進行手勢分類"""
    if MODEL is None:
        return "MODEL_NOT_LOADED"
    
    buffer_data = np.expand_dims(buffer_data, axis=0)
    y_pred = MODEL.predict(buffer_data, verbose=0)
    label_pred = LABEL_ENCODER.inverse_transform([np.argmax(y_pred)])[0]
    return label_pred