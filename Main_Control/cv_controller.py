"""
程式用途：電腦視覺 (CV) 手勢辨識控制器
本程式利用攝影機捕捉影像，並透過 MediaPipe 套件即時追蹤手部骨架節點。
藉由計算手指關節的相對位置，判斷使用者伸出幾根手指 (1 到 5)。
判斷結果會加上 "CV_" 前綴，透過本機 TCP 網路發送給主控中心 (Controller)，
以實現無須訓練模型的輕量級視覺控制功能。
"""

import cv2
import numpy as np
import socket
import json
import time
import os
import threading
import queue
from collections import deque
import mediapipe as mp
import sys

# 1. 連線管理器 (TCP Client)
class ConnectionManager(threading.Thread):
    def __init__(self, host, port, send_queue):
        super().__init__()
        self.host = host
        self.port = port
        self.send_queue = send_queue
        self.client_socket = None
        self.running = True
        self.daemon = True 
    
    def run(self):
        print(f"[系統] 連線執行緒啟動，目標: {self.host}:{self.port}")
        while self.running:
            # 嘗試建立連線
            if self.client_socket is None:
                try:
                    self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.client_socket.settimeout(5)
                    self.client_socket.connect((self.host, self.port))
                    print(f"[連線成功] 已連上 {self.host}:{self.port}")
                except Exception:
                    self.client_socket = None
                    time.sleep(3)
                    continue

            # 消耗佇列並發送指令
            try:
                while not self.send_queue.empty():
                    data = self.send_queue.get()
                    msg = f"CV:{data}"
                    self.client_socket.sendall(msg.encode("utf-8"))
                    print(f"[發送] {msg}")
            except Exception as e:
                print(f"[傳輸失敗] {e}")
                if self.client_socket:
                    self.client_socket.close()
                self.client_socket = None 
            
            time.sleep(0.1)

    def stop(self):
        self.running = False
        if self.client_socket:
            self.client_socket.close()

# 2. 核心參數與手勢對應表
GESTURE_MAPPING = {
    "1": "CV_1",
    "2": "CV_2",
    "3": "CV_3",
    "4": "CV_4",
    "5": "CV_5",
    "Unknown": "CV_None"
}

DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = 6000

# 3. 主程式
def main():
    target_ip = DEFAULT_IP
    target_port = DEFAULT_PORT

    # 啟動連線執行緒
    send_queue = queue.Queue()
    conn_manager = ConnectionManager(target_ip, target_port, send_queue)
    conn_manager.start()

    # 初始化 MediaPipe 手部追蹤模組
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5
    )
    mp_drawing = mp.solutions.drawing_utils

    # 啟動攝影機
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[Error] 無法開啟攝影機")
        conn_manager.stop()
        return

    # 平滑化防手震
    recent = deque(maxlen=5)
    last_sent_code = "None"
    
    print("\n[系統] CV 控制器啟動")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # 影像前處理 (鏡像反轉與色彩轉換)
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        label_show = "Unknown"
        current_code = "CV_None"

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            # 擷取 21 個節點座標
            lm = hand_landmarks.landmark
            fingers_up = 0
            
            # 1. 拇指判斷 (比較指尖 X 座標與關節 X 座標)
            # 假設右手在鏡像畫面中，拇指伸直時指尖會比關節更靠外側
            if lm[4].x < lm[3].x:
                fingers_up += 1
                
            # 2. 其餘四指判斷 (比較指尖 Y 座標是否高於下一個關節 Y 座標)
            # 在 OpenCV 座標系中，Y 值越小代表位置越高
            tips_ids = [8, 12, 16, 20]
            pips_ids = [6, 10, 14, 18]
            
            for tip_id, pip_id in zip(tips_ids, pips_ids):
                if lm[tip_id].y < lm[pip_id].y:
                    fingers_up += 1

            # 將數量轉化為手勢標籤
            raw_label = str(fingers_up) if fingers_up > 0 else "Unknown"

            # 訊號平滑化 (取近期最常出現的結果)
            recent.append(raw_label)
            counts = {}
            for v in recent:
                counts[v] = counts.get(v, 0) + 1
            smooth_label = max(counts, key=counts.get)

            label_show = smooth_label
            current_code = GESTURE_MAPPING.get(smooth_label, "CV_None")

        # 指令狀態改變時，加入發送佇列
        if current_code != last_sent_code:
            send_queue.put(current_code)
            last_sent_code = current_code
            if current_code != "CV_None":
                print(f"[偵測] 手勢: {label_show} -> 發送: {current_code}")

        # 畫面 UI 繪製
        color = (0, 255, 0) if current_code != "CV_None" else (0, 0, 255)
        cv2.putText(frame, f"Gesture: {label_show}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
        
        if conn_manager.client_socket:
             cv2.putText(frame, f"Connected: {target_ip}", (10, frame.shape[0]-20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
             cv2.putText(frame, f"Connecting...", (10, frame.shape[0]-20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        cv2.imshow("Student CV Controller", frame)

        # 按 'q' 鍵離開
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    conn_manager.stop()
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()