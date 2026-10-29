"""資料來源：yfinance（動態抓取）+ 合成資料（離線測試/示範用）。

- 每個 (ticker, years) 只抓一次，結果放在記憶體快取，重複使用。
- 抓取失敗會重試；仍失敗就回傳 None，由呼叫端決定如何處理，不會讓整個程式崩潰。
- 環境變數 USE_SYNTHETIC=1 時改用合成資料（不連網，僅供測試/示範 UI）。
"""
import logging
import os
import time
import zlib

import numpy as np
import pandas as pd

log = logging.getLogger("data")
_CACHE: dict = {}


def use_synthetic() -> bool:
    return os.environ.get("USE_SYNTHETIC") == "1"


def fetch_prices(ticker: str, years: int = 6, retries: int = 3):
    """回傳含 Open/High/Low/Close/Volume 的日K DataFrame（已還原除權息），失敗回傳 None。"""
    key = (ticker, years)
    if key in _CACHE:
        return _CACHE[key]
    is_index = ticker.startswith("^")
    df = _synthetic(ticker, years) if use_synthetic() else _yahoo(ticker, years, retries)
    if df is not None:
        df = _clean(df, is_index)
        if len(df) < 30:
            df = None
    _CACHE[key] = df
    return df


def _yahoo(ticker, years, retries):
    try:
        import yfinance as yf
    except ImportError:
        log.error("未安裝 yfinance，請先 pip install -r backend/requirements-train.txt")
        return None
    for attempt in range(1, retries + 1):
        try:
            df = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
            if df is not None and len(df) > 0:
                return df[["Open", "High", "Low", "Close", "Volume"]]
            log.warning("%s 無資料（第 %d 次）", ticker, attempt)
        except Exception as e:  # noqa: BLE001 - 網路錯誤種類很多，統一重試
            log.warning("%s 抓取失敗（第 %d 次）：%s", ticker, attempt, e)
        time.sleep(2 * attempt)
    return None


def _clean(df: pd.DataFrame, is_index: bool) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df["Close"].notna() & (df["Close"] > 0)]
    dropped = 0
    if not is_index:  # 個股/ETF：成交量為 0 視為停牌或無效資料
        before = len(df)
        df = df[df["Volume"] > 0]
        dropped = before - len(df)
    df.attrs["dropped_zero_volume"] = dropped
    return df


def _synthetic(ticker: str, years: int) -> pd.DataFrame:
    """合成資料：共同的市場因子 + 個別波動，只為了讓管線與介面能離線跑通。"""
    n = int(years * 252)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    mkt = np.random.default_rng(2026).normal(0.0003, 0.011, n)
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    is_index = ticker.startswith("^")
    beta = 1.0 if is_index else rng.uniform(0.6, 1.4)
    base_vol = 0.004 if is_index else rng.uniform(0.008, 0.02)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.97 * lv[i - 1] + 0.15 * rng.normal()
    r = beta * mkt + base_vol * np.exp(lv) * rng.normal(size=n)
    start = {"^TWII": 10000, "^SOX": 3000}.get(ticker, rng.uniform(40, 400))
    close = start * np.exp(np.cumsum(r))
    prev = np.r_[close[0], close[:-1]]
    high = np.maximum(prev, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(prev, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    vol = 1e7 * np.exp(0.3 * rng.normal(size=n) + 8 * np.abs(r))
    return pd.DataFrame({"Open": prev, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)
