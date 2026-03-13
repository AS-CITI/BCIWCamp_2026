"""
程式用途：系統總主控中心 (Main Controller)
本程式為營隊 BCI 專案的核心樞紐，負責整合多個獨立的感測器訊號來源，
包含：
1. 本地的 EEG 與 EMG 訊號處理結果 (透過 SensorThread 接收)
2. 遠端或本地的 CV 影像手勢辨識結果 (透過 TCP Port 6000 接收)

系統會即時彙整上述訊號，並參照可動態重載的 strategy_map.py 進行優先順序判定。
最後透過獨立的 ConnectionManager 執行緒，將最終指令發送至模擬車輛伺服器。
"""

import socket
import threading
import time
import json
import importlib
import signal
import sys
import os
import multiprocessing
import queue
import strategy_map
from pylsl import StreamInfo, StreamOutlet, local_clock
from system.utils.visual_window import VisualWindow
from system.utils.flicker import FlickerController
from system import processing as SSVEPEMG_processing 

# 1. 全域配置與初始化
try:
    with open("hardware_config.json", "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("Error: hardware_config.json not found.")
    CONFIG = {
        "System": {"cv_port": 6000, "car_ip": "127.0.0.1", "car_port": 5000},
        "EEG": {"target_freqs": [15.0]}
    }

system_status = {"CV": "None"} 
send_queue = queue.Queue()  
is_running = True 

def signal_handler(sig, frame):
    global is_running
    print("\n[System] 正在關閉控制器...")
    is_running = False
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# 2. 連線管理器 (TCP Client)
class ConnectionManager(threading.Thread):
    def __init__(self, host, port, q):
        super().__init__()
        self.host = host
        self.port = port
        self.send_queue = q
        self.client_socket = None
        self.running = True
        self.daemon = True
    
    def run(self):
        while self.running:
            if self.client_socket is None:
                try:
                    self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.client_socket.settimeout(5)
                    self.client_socket.connect((self.host, self.port))
                    print(f"已連線至車子伺服器: {self.host}:{self.port}")
                except Exception:
                    self.client_socket = None
                    time.sleep(3)
                    continue

            try:
                while not self.send_queue.empty():
                    data = self.send_queue.get()
                    msg = (data.lower().strip() + "\n").encode("utf-8")
                    self.client_socket.sendall(msg)
                    # 背景執行緒負責實際發送
                    # print(f"[發送指令]: {data}") 
            except Exception:
                if self.client_socket:
                    self.client_socket.close()
                self.client_socket = None
            time.sleep(0.05)

# 3. CV 伺服器 (接收影像辨識標籤)
def cv_server_job():
    host = "0.0.0.0"
    port = CONFIG["System"].get("cv_port", 6000)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((host, port))
        server.listen(1)
        server.settimeout(1.0)
        while is_running:
            try:
                conn, addr = server.accept()
                with conn:
                    while is_running:
                        data = conn.recv(1024).decode('utf-8')
                        if not data: break
                        if data.startswith("CV:"):
                            label = data.split(":")[1].strip()
                            system_status["CV"] = label
            except socket.timeout: continue
            except: break
    except Exception as e:
        print(f"CV Server 錯誤: {e}")

# 4. 邏輯主控中心
def control_loop_job(sensor_thread, event_outlet):
    
    last_cmd = None
    map_file = "strategy_map.py"
    last_mtime = 0
    
    # 預設對應參數
    mapping = {}
    priority_list = ["CV", "EMG", "SSVEP"]

    # 初始載入設定檔
    try:
        last_mtime = os.path.getmtime(map_file)
        mapping = strategy_map.MAPPING
        priority_list = getattr(strategy_map, 'PRIORITY', priority_list)
    except Exception as e:
        print(f"[System] Warning: 初始設定檔載入失敗: {e}")
    
    eeg_enabled = CONFIG.get("EEG", {}).get("enabled", True)
    emg_enabled = CONFIG.get("EMG", {}).get("enabled", True)
    cv_enabled = CONFIG.get("System", {}).get("use_cv", True)
    
    print(f"[System] 控制邏輯啟動。優先順序: {priority_list}")

    while is_running:
        sensor_data = sensor_thread.get_result()      
        
        # 動態重載：監聽設定檔修改時間
        try:
            curr_mtime = os.path.getmtime(map_file)
            if curr_mtime > last_mtime:
                time.sleep(0.1) 
                importlib.reload(strategy_map)
                mapping = strategy_map.MAPPING
                priority_list = getattr(strategy_map, 'PRIORITY', ["CV", "EMG", "SSVEP"])
                print(f"[System] 設定檔已更新。新優先順序: {priority_list}")
                last_mtime = curr_mtime
        except Exception:
            pass # 忽略讀取異常以確保系統穩定

        # 1. 收集各感測器候選指令
        candidates = {}

        if eeg_enabled:
            ssvep = sensor_data.get('SSVEP')
            if ssvep == "EYES_CLOSED":
                candidates["SSVEP"] = mapping.get("EYES_CLOSED", "stop")
            elif "15Hz" in str(ssvep):
                candidates["SSVEP"] = mapping.get("SSVEP_15Hz", "cf")

        if emg_enabled:
            emg = sensor_data.get('EMG')
            if emg and emg != "relax":
                candidates["EMG"] = mapping.get(f"{emg}")

        if cv_enabled:
            cv = system_status.get("CV")
            if cv and cv not in ["None", "CV_None"]:
                candidates["CV"] = mapping.get(cv)

        # 2. 決定最終指令 (嚴格優先級判定)
        final_cmd = None
        active_source = None

        # 遍歷優先順序清單，首個有效指令勝出
        for source in priority_list:
            if candidates.get(source):
                final_cmd = candidates[source]
                active_source = source
                break 

        # 3. 指令執行與發送邏輯
        if final_cmd is None:
            final_cmd = "stop"

        if final_cmd and final_cmd != "ignore":
            if final_cmd != last_cmd:
                send_queue.put(final_cmd)
                event_outlet.push_sample([f"CMD:{final_cmd}"], timestamp=local_clock())
                
                if final_cmd != "stop":
                    print(f"[發送指令] {final_cmd} (來源: {active_source})")
                elif last_cmd != "stop":
                    print("[發送指令] Stop")
                
                last_cmd = final_cmd
            
        time.sleep(0.05)

# 5. UI 視覺刺激程序
def run_ui_process():
    outlet = StreamOutlet(StreamInfo("SSVEP_Markers", 'Markers', 1, 0, 'string'))
    visual_win = VisualWindow(size=(1280, 720), fullscr=False, units="height")
    
    target_hz = 15.0
    squares = [{"hz": target_hz, "pos": (0, 0), "size": 0.5, "color": [1, 1, 1], 
               "vertices": [(-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5), (0.5, 0.5)]}]
    fixation_cross = [{"vertices": [(0.01, 0.1), (0.01, -0.1), (-0.01, -0.1), (-0.01, 0.1)], "pos": (0,0), "color": [-1,-1,-1]}, 
                      {"vertices": [(0.1, 0.01), (0.1, -0.01), (-0.1, -0.01), (-0.1, 0.01)], "pos": (0,0), "color": [-1,-1,-1]}]

    flicker = FlickerController(visual_win, squares, fixation_cross, outlet=outlet) 
    while True:
        state = flicker.flicker(max_duration=1.0, instruction="ONLINE")
        if state != "OK": break
    flicker.end_experiment()

# 主程式執行入口
if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # 啟動連線管理
    car_ip = CONFIG["System"].get("car_ip", "127.0.0.1")
    car_port = CONFIG["System"].get("car_port", 5000)
    conn_manager = ConnectionManager(car_ip, car_port, send_queue)
    conn_manager.start()

    # LSL 事件串流
    outlet_event = StreamOutlet(StreamInfo("BCI_Events", 'Markers', 1, 0, 'string'))
    
    # 啟動感測器資料處理執行緒
    sensor_thread = SSVEPEMG_processing.SensorThread()
    sensor_thread.start() 

    # 啟動 CV Server 與 控制邏輯
    threading.Thread(target=cv_server_job, daemon=True).start()
    threading.Thread(target=control_loop_job, args=(sensor_thread, outlet_event), daemon=True).start()

    # 啟動 UI 視窗 (獨立 Process)
    ui_process = multiprocessing.Process(target=run_ui_process)
    ui_process.start()

    try:
        ui_process.join()
    except KeyboardInterrupt:
        pass
    finally:
        is_running = False
        ui_process.terminate()
        sensor_thread.stop()
        sys.exit(0)