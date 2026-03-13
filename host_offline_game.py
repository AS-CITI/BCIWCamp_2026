"""
程式用途：BCI 機器車與 6 軸機械手臂簡易模擬器
本程式透過pygame來替代實體機器車，模擬車子移動與機械手臂轉動。
在實作版，我們主要選擇三種機械手臂動作(arm_1, arm_2, arm_3)，
但實際上機械手臂可以做出很多動作，此離線版本可自行調整指令！
"""

import socket
import numpy as np
import time
import pygame
import sys

# 模擬環境參數設定
SERVER_PORT = 5000
# 視窗加大以容納分割畫面 (左: 800 for Car, 右: 400 for Arm)
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 600
SCREEN_SIZE = (WINDOW_WIDTH, WINDOW_HEIGHT)

# 分割區域定義
CAR_ZONE_WIDTH = 600
ARM_ZONE_WIDTH = 600

CAR_COLOR = (0, 255, 0) # 亮綠色車子
BG_COLOR_LEFT = (30, 30, 30) # 左側小車區背景 (深灰)
BG_COLOR_RIGHT = (20, 20, 20) # 右側手臂區背景 (更深灰)
TEXT_COLOR = (255, 255, 255) # 白色文字
ARM_COLOR = (255, 165, 0) # 橘色連桿
JOINT_COLOR = (255, 255, 255) # 白色關節點

# 初始化 Pygame 視窗與字體
pygame.init()
screen = pygame.display.set_mode(SCREEN_SIZE)
pygame.display.set_caption("BCI 機器車離線模擬器")
font = pygame.font.SysFont("Microsoft JhengHei", 20)
arm_font = pygame.font.SysFont("Microsoft JhengHei", 12)

# 模擬車體運動狀態 (座標參考左側 CAR_ZONE)
car_pos = np.array([400.0, 300.0])
car_angle = 0.0 # 小車面向角度 (單位: 度)
car_speed = 0.0
current_action = "STOP"

# 模擬 6 軸手臂關節角度 (初始化為 180 度，dtype=int 確保文字顯示簡潔)
arm_angles = np.array([180, 180, 180, 180, 180, 180], dtype=int)
ANGLE_LIMITS = [(30, 330), (150, 260), (100, 270), (160, 350), (10, 350), (170, 290)]
JOINT_NAMES = ["m0", "m1", "m2", "m3", "m4", "m5"]

def update_physics():
    """根據當前速度與角度更新車體座標"""
    global car_pos
    rad = np.radians(car_angle)
    # 計算位移向量 (注意: Pygame 的 Y 軸向下，所以 sin 取負)
    velocity = np.array([np.cos(rad), -np.sin(rad)]) * car_speed
    car_pos += velocity
    
    car_pos[0] = np.clip(car_pos[0], 20, CAR_ZONE_WIDTH - 20)
    car_pos[1] = np.clip(car_pos[1], 20, WINDOW_HEIGHT - 20)

def handle_sim_command(cmd):
    """將通訊指令轉換為模擬動作"""
    global car_speed, car_angle, current_action, arm_angles
    if not cmd: return

    current_action = cmd.upper()

    # 車體控制指令
    if cmd == "cf": # 前進
        car_speed = 1.0
    elif cmd == "cb": # 後退
        car_speed = -1.0
    elif cmd == "cl": # 左轉
        car_angle += 50.0
    elif cmd == "cr": # 右轉
        car_angle -= 50.0
    elif cmd == "stop": # 停止
        car_speed = 0.0
    
    # 手臂單一關節微調，在營隊中我們定義 arm_3 是調整夾子張合
    move_map = {
        "arm_3": (5, 10), "m5-": (5, -10), "m4+": (4, 10), "m4-": (4, -10),
        "m3+": (3, 10), "m3-": (3, -10), "m2+": (2, 10), "m2-": (2, -10),
        "m1+": (1, 10), "m1-": (1, -10), "m0+": (0, 10), "m0-": (0, -10)
    }
    
    # 預設姿勢，可自行調整手臂各軸的角度以達到不同的姿勢
    pose_map = {
        "arm_1": [177, 241, 196, 223, 170, 256],
        "arm_2": [179, 152, 192, 172, 172, 180], 
    }

    if cmd in move_map:
        idx, delta = move_map[cmd]
        # 更新角度並限制在安全範圍內，保持 int 型態
        arm_angles[idx] = int(np.clip(arm_angles[idx] + delta, ANGLE_LIMITS[idx][0], ANGLE_LIMITS[idx][1]))
    elif cmd in pose_map:
        # 將預設姿勢陣列強制轉換為 int
        arm_angles = np.array(pose_map[cmd], dtype=int)

def draw_arm_viz(surface, x_offset, y_base, angles):
    """繪製完整的 6 軸手臂示意圖"""
    # 稍微加長連桿長度，讓畫面更清楚
    lengths = np.array([20, 30, 80, 70, 50, 20], dtype=float) 
    
    # 手臂基座中心
    current_pos = np.array([x_offset + ARM_ZONE_WIDTH / 2.0, y_base], dtype=float)
    joint_coords = [current_pos.copy()]
    
    total_angle = 0
    for i in range(len(lengths)):
        if i < 2: 
            total_angle = 0 
        else:
            # 這裡將偏轉係數稍微加大，讓動作視覺效果更明顯
            total_angle += (angles[i] - 180) 

        rad = np.radians(total_angle - 90)
        next_pos = current_pos + np.array([np.cos(rad), -np.sin(rad)]) * lengths[i]
        
        # 繪製連桿
        pygame.draw.line(surface, ARM_COLOR, current_pos.astype(int), next_pos.astype(int), 8)
        # 繪製關節點
        pygame.draw.circle(surface, JOINT_COLOR, current_pos.astype(int), 6)
        
        current_pos = next_pos
        joint_coords.append(current_pos.copy())

    pygame.draw.circle(surface, JOINT_COLOR, current_pos.astype(int), 6)

    # 標註關節名稱
    for i, name in enumerate(JOINT_NAMES):
        coord = joint_coords[i+1]
        label_text = arm_font.render(f"{name}: {angles[i]}", True, TEXT_COLOR)
        # 錯開文字位置避免重疊
        offset_y = -15 if i % 2 == 0 else 5 
        surface.blit(label_text, (coord[0] + 12, coord[1] + offset_y))

def draw_scene():
    """繪製視窗畫面：分割左側小車區與右側手臂區"""
    # 填充左側背景
    left_rect = pygame.Rect(0, 0, CAR_ZONE_WIDTH, WINDOW_HEIGHT)
    screen.fill(BG_COLOR_LEFT, left_rect)
    
    # 填充右側背景
    right_rect = pygame.Rect(CAR_ZONE_WIDTH, 0, ARM_ZONE_WIDTH, WINDOW_HEIGHT)
    screen.fill(BG_COLOR_RIGHT, right_rect)

    # 1. 繪製左側小車 (三角形)
    rad = np.radians(car_angle)
    # 以座標為中心，計算三角形三個頂點
    p1 = car_pos + np.array([np.cos(rad), -np.sin(rad)]) * 20 # 車頭
    p2 = car_pos + np.array([np.cos(rad + 2.5), -np.sin(rad + 2.5)]) * 15 # 車尾左
    p3 = car_pos + np.array([np.cos(rad - 2.5), -np.sin(rad - 2.5)]) * 15 # 車尾右
    pygame.draw.polygon(screen, CAR_COLOR, [p1, p2, p3])

    # 2. 繪製右側完整的 6 DOF 手臂示意圖
    # 將手臂基座設在右側區域中央偏下
    draw_arm_viz(screen, CAR_ZONE_WIDTH, WINDOW_HEIGHT * 0.3, arm_angles)

    # 3. 顯示文字資訊 (統一放在視窗左上角，清晰可讀)
    # 這裡將 angles 轉換為 list(dtype=int) 的文字呈現，解決顯示 np.int64 的問題
    angles_display = f"[{', '.join(map(str, list(arm_angles)))}]"
    info_text = [
        f"系統指令: {current_action}",
        f"車體座標: {int(car_pos[0])}, {int(car_pos[1])}",
        f"車體角度: {int(car_angle)}",
        f"手臂角度 (6軸): {angles_display}"
    ]
    
    for i, txt in enumerate(info_text):
        render = font.render(txt, True, TEXT_COLOR)
        screen.blit(render, (20, 20 + i * 28))
    
    pygame.display.flip()

def start_sim_server(port):
    """啟動伺服器並執行模擬迴圈"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)
    server.setblocking(False) # 設定為非阻塞模式以維持畫面更新
    
    print(f"[模擬器] 6 軸伺服器啟動於 Port {port}")
    conn = None
    buffer = "" # 存放接收到的未完成字串，防止 readline 衝突
    clock = pygame.time.Clock()

    while True:
        # 處理 Pygame 視窗事件
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        # 處理 TCP 連線
        if not conn:
            try:
                conn, addr = server.accept()
                conn.setblocking(False)
                print(f"[連線成功] 來自 {addr}")
                buffer = "" # 清空舊緩衝
            except BlockingIOError:
                pass
        else:
            try:
                # 採用 recv + 手動 buffer 的方式處理非阻塞通訊
                data = conn.recv(1024).decode('utf-8')
                if data:
                    buffer += data
                    if "\n" in buffer:
                        # 用換行符號切割指令
                        lines = buffer.split("\n")
                        buffer = lines.pop() # 將最後一個可能不完整的指令留回 buffer
                        for line in lines:
                            if line.strip():
                                handle_sim_command(line.strip().lower())
                else:
                    # 收到空字串代表用戶端正常斷開連線
                    print("[連線斷開] 用戶端已離線，等待新對象...")
                    conn.close()
                    conn = None
            except BlockingIOError:
                # 緩衝區無數據時，繼續下一幀
                pass
            except Exception as e:
                print(f"伺服器錯誤: {e}")
                if conn: conn.close()
                conn = None

        # 更新物理邏輯與畫面
        update_physics()
        draw_scene()
        clock.tick(60) # 鎖定 60 FPS

if __name__ == "__main__":
    try:
        start_sim_server(SERVER_PORT)
    except KeyboardInterrupt:
        pygame.quit()