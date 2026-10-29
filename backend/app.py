"""輕量 API：只讀取「預先算好」的 JSON，絕不在請求時訓練（Render 免費版 512MB 撐不住）。

資料來源（二選一）：
  1. 設定環境變數 DATA_BASE_URL（建議）→ 直接讀 GitHub raw，例如
       https://raw.githubusercontent.com/<帳號>/<repo>/main/data
     這樣 Actions 更新資料後，Render 不用重新部署
  2. 沒設定就讀本機 ../data 資料夾（需 Render 自動重新部署才會更新）

環境變數：
  ALLOWED_ORIGINS  允許的前端網域，逗號分隔（例：https://my-app.onrender.com）；沒設定=全部允許（僅開發用）
  CACHE_SECONDS    記憶體快取秒數，預設 600
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

LOCAL_DATA = Path(__file__).resolve().parent.parent / "data"
BASE_URL = os.environ.get("DATA_BASE_URL", "").rstrip("/")
TTL = int(os.environ.get("CACHE_SECONDS", "600"))
ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
CODE_RE = re.compile(r"^[0-9A-Za-z]{2,8}$")

app = FastAPI(title="Stock Forecast API", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET"], allow_headers=["*"])

_cache: dict = {}


def _read(name: str):
    """讀取 data/{name}.json，含記憶體快取；找不到回傳 None。"""
    hit = _cache.get(name)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    data = None
    try:
        if BASE_URL:
            with urllib.request.urlopen(f"{BASE_URL}/{name}.json", timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        else:
            data = json.loads((LOCAL_DATA / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  找不到/網路錯誤 → 若有舊快取就先用舊的
        if hit:
            return hit[1]
        return None
    _cache[name] = (time.time(), data)
    return data


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/stocks")
def stocks():
    data = _read("index")
    if data is None:
        raise HTTPException(503, "資料尚未產生，請先執行 GitHub Actions（Daily Train）")
    return data


@app.get("/api/stock/{code}")
def stock(code: str):
    if not CODE_RE.match(code) or code.lower() in ("index", "ticker_cache"):
        raise HTTPException(400, "代號格式不正確")
    data = _read(code.upper())
    if data is None:
        raise HTTPException(404, "尚未納入每日計算")
    return data
