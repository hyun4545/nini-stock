"""台股代號處理：自動判斷上市(.TW) / 上櫃(.TWO)、ETF 判斷、特殊商品警示。"""
import json
from pathlib import Path

from data_source import fetch_prices, use_synthetic

CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "ticker_cache.json"


def is_etf(code: str) -> bool:
    """ETF 判斷規則集中在這裡，要調整只改這個函式。（目前：代號以 00 開頭）"""
    return code.startswith("00")


def instrument_warnings(code: str) -> list:
    w = []
    if is_etf(code):
        tail = code[-1].upper()
        if tail == "B":
            w.append("債券型 ETF：走勢特性與股票不同，模型參考價值有限")
        elif tail == "L":
            w.append("槓桿型 ETF：每日再平衡，長天期走勢失真，模型參考價值有限")
        elif tail == "R":
            w.append("反向型 ETF：每日再平衡，長天期走勢失真，模型參考價值有限")
        elif tail == "U":
            w.append("期貨型 ETF：受轉倉成本影響，模型參考價值有限")
        w.append("ETF 走勢高度跟隨大盤，方向命中率不代表模型有獨立預測力")
    return w


def _load_cache() -> dict:
    if use_synthetic():          # 合成模式不讀寫快取，避免污染真實執行
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(c: dict) -> None:
    if use_synthetic():
        return
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def resolve_ticker(code: str, years: int = 6) -> str:
    """只輸入數字代號 → 回傳 yfinance 代號。先試 .TW 再試 .TWO，結果會快取。"""
    code = str(code).strip().upper()
    if code.startswith("^") or "." in code:
        return code
    cache = _load_cache()
    order = [cache[code]] if code in cache else []
    order += [s for s in (".TW", ".TWO") if s not in order]
    for suffix in order:
        if fetch_prices(code + suffix, years) is not None:
            if cache.get(code) != suffix:
                cache[code] = suffix
                _save_cache(cache)
            return code + suffix
    raise ValueError(f"找不到代號 {code}：.TW 與 .TWO 都抓不到資料，請確認代號是否正確")


def market_index_for(ticker: str, years: int = 6):
    """回傳 (大盤 DataFrame, 使用的指數名稱)。上櫃優先櫃買指數，抓不到退回加權指數。"""
    if ticker.endswith(".TWO"):
        df = fetch_prices("^TWOII", years)
        if df is not None:
            return df, "^TWOII"
    return fetch_prices("^TWII", years), "^TWII"
