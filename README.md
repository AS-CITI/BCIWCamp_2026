# 2026 BCI Camp 實作操作指南
本專案為 2026 腦機介面營的腦機介面控制系統線下版本，整合了電腦視覺（CV）、腦電波（EEG）與肌電波（EMG）訊號，並透過本機伺服器與虛擬機器車及六軸機械手臂進行互動測試。

**專案聲明：**\
由於營隊原版程式碼中的核心模型與訊號處理演算法涉及真實人體實驗數據及學術研究隱私，因此本公開版本有對相關實作程式碼進行了調整。

此外，考量到多數使用者手邊並無專業的 EEG 或 EMG 硬體設備，我們有特別設計了模擬訊號產生器 (Generator)，讓使用者在一般電腦環境下即可模擬腦電與肌電交互回饋。

## 檔案結構
```text

├── Main_Control
│   ├── system/
│   │   ├── listener/          # EMG 訊號監聽與演算法模組
│   │   ├── utils/             # 視覺視窗與 SSVEP 閃爍控制器
│   │   └── processing.py      # 資料處理執行緒
│   ├── controller.py          # 系統核心控制中心 (Main Controller)
│   ├── cv_controller.py       # 電腦視覺手勢辨識模組
│   ├── strategy_map.py        # 動作映射與優先等級定義
│   ├── eeg_generator.py       # EEG 模擬訊號產生器
│   ├── emg_generator.py       # EMG 模擬訊號產生器
│   ├── eeg_tester.py          # EEG 獨立測試與門檻調校工具
│   ├── emg_tester.py          # EMG 獨立測試與門檻調校工具
│   └── hardware_config.json   # 系統連線與硬體參數設定
├── host_offline_game.py       # BCI 機器車與 6 軸機械手臂簡易模擬器
├── requirements.txt           # 主環境套件列表
└── requirements_cv.txt        # CV 環境套件列表
```

## 環境建置
在開始執行前，請確保已安裝必要的 Python 套件，本專案需要兩個虛擬環境：main_env (主環境，執行`controller.py` 、 `host_offline_game`、EEG 和 EMG 相關程式碼，可透過 **requirements.txt** 安裝)、CV_env (執行 `cv_controller.py`，可透過 **requirements_cv.txt** 安裝)，python 版本皆為 3.10。

## 標準啟動順序
請開啟多個終端機（Terminal）分別執行。

第一步：啟動簡易模擬器 \
必須最先啟動，以建立 TCP 伺服器（Port 5000）等待接收控制指令。

```bash
# 使用主環境
python host_offline_game.py
```

第二步：啟動訊號源 \
可依據需求開啟一個或多個產生器。

EEG 模擬器（按鍵盤 A 模擬 Alpha 波，按 S 模擬 15Hz SSVEP，按 W 回到基準值）：

```Bash
# 使用主環境
python eeg_generator.py
```
EMG 模擬器（按鍵盤 J、K、L 模擬不同肌肉群發力）：

```Bash
# 使用主環境
python emg_generator.py
```

CV 控制器 \
當主控程式啟動並建立 CV Server 後，即可啟動攝影機辨識模組，此模組採用純幾何規則判斷右手 1 到 5 的手勢。

```Bash
# 使用 CV 環境
python cv_controller.py
```

第四步：啟動主控中心 \
主控程式會連接模擬器、讀取 LSL 串流，並啟動視覺接收伺服器（Port 6000）。

```Bash
# 使用主環境
python controller.py
```

## 其他模組說明
1. `strategy_map.py` \
    負責定義感測器訊號與車體/手臂動作的對應關係。

    動態更新：在系統運行期間，直接修改此檔案並存檔，controller.py 會自動讀取最新設定，不需重新啟動程式。

    優先順序設定：可透過修改 PRIORITY 陣列調整多感測器同時觸發時的執行順序。

2.  `hardware_config.json` \
    管理系統的基礎網路配置與訊號處理參數。

    **car_ip:** 請設定為 "127.0.0.1" 以進行本機離線測試。

    **thresholds:** 可調整 EMG 各通道的觸發門檻值。

    **stream_name:** 必須與 Generator 中定義的 STREAM_NAME 完全一致。

3. `eeg_tester.py`, `emg_tester.py` \

    獨立的除錯工具。當整合系統不如預期運作時，可先透過這些腳本確認 LSL 串流是否正常發送，以及閾值判斷邏輯是否正確，也可以嘗試自己調整參數，了解系統運作！
