# 台股預測實驗室（懶人包）

用 Random Forest、Gradient Boosting、Ridge 預測台股（上市、上櫃、ETF）未來半年每日價格，
並用 walk-forward 回測檢驗「過去半年到底準不準」。**重點不是做出神準的預言機，而是做出一個不會騙你的系統。**

```
GitHub Actions（每個交易日 15:00 + 每週調參）
   抓資料 → 特徵 → 訓練 → 回測 → 產出 data/*.json → 自動 commit 回 repo
Render Web Service（FastAPI）  只讀 JSON 回傳，不訓練，幾乎不吃資源
Render Static Site（React）    畫圖表、準確度排名
```

## 資料夾

```
config.json                 要計算的股票清單（改這裡就能加股票）
backend/
  run_all.py                ★ Actions 唯一入口（抓資料→特徵→預測→回測→輸出）
  data_source.py            yfinance 抓取（重試、快取）＋離線合成資料
  ticker_utils.py           自動判斷上市 .TW / 上櫃 .TWO、ETF 判斷
  features.py               33 個特徵 + 防洩漏檢查 check_causality()
  models.py                 三個模型與保守預設參數
  backtest.py               walk-forward 回測、基準、信賴區間、判定規則
  train.py                  各天期訓練 + 每日內插預測 + 信賴區間
  tune.py                   每週自動調參（巢狀驗證，防過擬合）
  app.py                    FastAPI（只讀 JSON）
  tests/test_pipeline.py    洩漏測試等 7 項
frontend/                   React + Vite + Recharts
.github/workflows/          train.yml（每日）、tune.yml（每週）
render.yaml                 Render 一鍵部署設定
data/                       產出的 JSON（目前是「合成示範資料」，跑過真實資料就會被覆蓋）
```

## 一、先在本機體驗（不需要網路）

```bash
cd backend
pip install -r requirements-train.txt
USE_SYNTHETIC=1 python -m pytest tests -q        # 7 項測試（含資料洩漏檢查）
USE_SYNTHETIC=1 python run_all.py                # 用合成資料跑通整條流程（約 15 秒/檔）

pip install -r requirements.txt
uvicorn app:app --port 8000                      # 啟動 API

cd ../frontend
npm install
npm run dev                                      # 開 http://localhost:5173
```

Windows PowerShell 設環境變數請改成：`$env:USE_SYNTHETIC="1"; python run_all.py`

## 二、跑真實資料

```bash
cd backend
python run_all.py --ticker 2408     # 先只跑一檔，確認正常
python run_all.py                   # 跑 config.json 全部
```

第一次請只放 1～3 檔。輸出會印出特徵數量、資料日期範圍、NaN 比例、各檔耗時、峰值記憶體。

## 三、放上 GitHub（讓排程跑起來）

1. 建立 GitHub repo，把整個資料夾 push 上去（預設分支 `main`）。
2. **Settings → Actions → General → Workflow permissions** 選 **Read and write permissions**（否則無法 commit 結果）。
3. **Actions** 頁籤 → 左邊 **Daily Train** → **Run workflow**（第一次要手動按，排程只會在下一個符合時間點才跑）。
4. 看 log 全部綠勾勾，repo 內出現 `data/2408.json` 的新 commit 就成功了。
5. 之後週一～五台灣 15:00 自動更新；週六 10:00 自動調參（**Weekly Tune**，也可手動觸發）。

> 公開 repo 的 Actions 免費不限時數；私有 repo 每月約 2,000 分鐘，標的多時要注意。

## 四、部署到 Render（免費版）

最簡單：Render → **New → Blueprint** → 選你的 repo（讀取 `render.yaml`）。會建立兩個服務，請設定環境變數：

| 服務 | 變數 | 值 |
|---|---|---|
| API | `DATA_BASE_URL` | `https://raw.githubusercontent.com/你的帳號/你的repo/main/data` |
| API | `ALLOWED_ORIGINS` | 前端網址，例如 `https://stock-forecast-web.onrender.com` |
| 前端 | `VITE_API_BASE` | API 網址，例如 `https://stock-forecast-api.onrender.com`（不要結尾斜線） |

設定 `DATA_BASE_URL` 後，Actions 更新資料，API 在快取過期（預設 10 分鐘）後自動讀到新資料，**不需要重新部署**。
私有 repo 的 raw 網址需要 token，建議資料用公開 repo，或改成每次更新後觸發 Render 重新部署並不設定 `DATA_BASE_URL`。

免費版閒置 15 分鐘會休眠，喚醒約 30～60 秒；前端會顯示「伺服器喚醒中」並自動重試。

## 五、日常操作

- **加股票/ETF/上櫃**：編輯 `config.json`，只填數字代號，系統自動判斷 `.TW` / `.TWO`：
  ```json
  { "code": "6488", "name": "環球晶", "peers": ["5483"] }
  ```
  ETF 不用設同業，會自動改比「相對大盤」與「相對 0050」。改完到 Actions 手動跑一次 Daily Train（可填 ticker 只跑新加的）。
- **查詢任意代號**：前端只能查「已納入清單」的標的；不在清單會顯示「尚未納入每日計算」。免費版不能即時訓練（會爆記憶體）。
- **資料不足的新標的**：有效資料 < 150 筆直接跳過；< 600 筆只訓練 1/5/10/20 日。

## 六、怎麼看結果（最重要）

判定「有參考價值」必須**同時**滿足，且至少 2 個天期成立：

1. 方向命中率 > 單邊猜測（永遠猜漲 / 永遠猜跌取較高者）
2. 95% 信賴區間（block bootstrap，區塊長度 = 天期）下界 > 50%
3. 預測看漲比例介於 20%～80%（不是只猜單一方向）
4. 有效樣本數 ≥ 5（40 日以上天期回測只有 1～2 個獨立樣本，**一律不顯示準確度**）

絕大多數情況你會看到「沒有任何模型通過驗證」——這是正常且誠實的結果，不是程式壞掉。
股價接近隨機漫步，只靠技術面與大盤特徵很難穩定勝過亂猜。圖上的虛線代表未通過驗證的模型。

## 七、與先前討論的差異（刻意的設計決定）

| 項目 | 做法 | 原因 |
|---|---|---|
| 特徵 shift(1) | 不全域 shift，改成「第 t 列只用 ≤ t 日收盤，目標從 t 收盤起算」 | 等價且不浪費一天資訊；改用 `check_causality()` 實測驗證，並測試「故意偷看明天」能被抓出來 |
| 週/月線 MACD | 標籤日 > 當天的 K 棒不帶入 | 避免用到本週/本月未收完的資料 |
| XGBoost | 改用 sklearn `HistGradientBoostingRegressor` | 更省記憶體、少一個相依套件 |
| early_stopping | **關閉** | sklearn 內建驗證集是隨機切分，等於偷看未來 |
| 調參 | 每週一次；外層 120 天不參與；gap = 天期；落差 > 0.20 淘汰 | 防過擬合。注意：標籤重疊會讓「內層驗證分數」偏樂觀，最終以回測為準 |
| 信賴區間 | 過去 3 年同天期報酬的 10%/90% 分位 | 誠實反映不確定性，不假裝精準 |
| 未來日期 | 以週一～五估算 | 未扣除台灣國定假日 |

## 八、驗證狀態（請知悉）

已在沙盒用合成資料驗證：完整管線（3 檔各 15 秒、峰值記憶體約 160MB）、7 項測試、調參流程、JSX 語法。

**尚未實測**（沙盒沒有網路）：yfinance 真實抓取（尤其櫃買指數 `^TWOII` 代號是否可用，抓不到會自動退回 `^TWII` 並在警示中註明）、
`npm install && npm run build`、FastAPI 實際啟動、Render 實際部署。第一次部署若有錯誤，把錯誤訊息貼給 AI 即可。

## 九、疑難排解

| 狀況 | 處理 |
|---|---|
| Actions 最後 commit 失敗（403） | 檢查 Workflow permissions 是否為 Read and write |
| 某檔失敗 | 看 log 最後的「失敗清單」；單檔失敗不會影響其他檔 |
| yfinance 被限流/抓不到 | 已內建重試；仍失敗就隔天自動重跑，或手動 Run workflow |
| 前端一直顯示喚醒中 | 確認 `VITE_API_BASE` 正確、API 的 `/health` 能開 |
| 前端 CORS 錯誤 | `ALLOWED_ORIGINS` 要與前端網址完全一致（含 https、不含結尾斜線） |
| 前端顯示「合成資料」警示 | 代表 `data/` 還是示範檔；跑過真實的 Daily Train 就會覆蓋 |
| 記憶體不足 | 降低 `models.py` 內 `DEFAULTS` 的 `n_estimators` / `max_iter`，或縮短 `history_years` |

## 十、接著可以請 AI 做的事

- 「把 `tune.py` 的搜尋範圍與結果貼給你，請幫我檢查是否有過擬合跡象」
- 「在 `features.py` 加入 DRAM 現貨價/外資買賣超特徵，並補上對應的因果性測試」
- 「前端新增一個頁面，列出所有標的的判定結果總表」

> 本系統僅供研究與學習，非投資建議。

## Windows 本機執行

需先安裝 Python 3.10 以上（含 pip，加入 PATH）與 Node.js（含 npm）。

1. 雙擊 `train_local.bat`：自動建立 `.venv`、安裝 Python 套件，依 `config.json` 下載真實資料並訓練全部股票。20 檔首次訓練可能需要較長時間，需連網。
2. 訓練完成後雙擊 `run_local.bat`：安裝依賴、啟動 API 與前端，開啟 http://localhost:5173。瀏覽器若先開啟，等 Vite 就緒後重新整理。
3. 更新預測時再次執行 `train_local.bat`；結束網站時，在前端視窗按 Ctrl+C 並關閉 API 視窗。

也可從命令提示字元執行 `train_local.bat --ticker 2330`，只更新單一股票，或使用 `train_local.bat --force` 強制重算。`setup_local.bat` 是共用的 Python 環境安裝程序。股票的 `name` 已設定為中文簡稱，可自行在設定中調整。
## 半年內買賣情境與本次部署

畫面新增「半年內買賣情境參考」，使用最多 120 個估算交易日內的直接預測天期（不以每日內插曲線挑低高點），比較先買後賣組合的成本後報酬。顯示進出場估算日期窗、各模型預測價格範圍及成本前後報酬。價格範圍是模型分歧，並非信賴區間；時間窗前後各 5 個估算交易日且不重疊，日期未扣除台股休市日。

`config.json` 的 `trade_plan` 提供成本假設：`fee_rate` 為每邊手續費、`sell_tax_rate` 為賣出稅率、`slippage_rate` 為每邊滑價、`min_net_return` 為淨報酬門檻、`window_days` 為時間窗寬度。預設是一般股票研究情境，請按實際商品及券商調整；未計最低手續費及股數取整。報酬以錨點模型平均價估算，不代表價格區間內任意成交都可達成。

合成資料、成本後報酬不足、模型方向不一致，或買入與賣出天期未同時獲至少兩個模型通過既有方向回測時顯示「觀望」。既有 120 日回測通常不足以驗證長天期，因此半年情境常會顯示觀望；短期排名不會當成長期可信度。買賣規則尚未做策略回測，顯示的報酬不是歷史績效。每次資料更新會重新估算，舊情境可能改變。

部署順序：

1. 將本次程式與設定推送至 GitHub 使用的分支。
2. GitHub → Actions → Daily Train → Run workflow：ticker 留空、force 勾選，等待全部股票重新產生並提交 `data/*.json`。本機也可執行 `train_local.bat --force` 後自行提交資料。
3. Render 前端 `stock-forecast-web` 需重新部署，才能顯示新卡片。若已自動部署成功則不需再手動執行；否則 Manual Deploy → Deploy latest commit。
4. Render API 若有 `DATA_BASE_URL`，程式只透傳 JSON，本次 API 不需重新部署；等資料快取（預設 10 分鐘）過期後重新整理。若未設定而讀本機 `data/`，需在第 2 步資料提交完成後重新部署 API，並確認部署包含根目錄 `data/`（目前 Blueprint 設定 API rootDir 為 backend，建議直接設定 DATA_BASE_URL 指向 GitHub raw 的 data）。
5. 開啟任一股票頁，確認新的收盤日與「半年內買賣情境參考」卡片。若顯示資料尚未包含情境，表示仍在讀取舊 JSON，請檢查 Actions、資料網址及快取。