"""把「抓資料 → 判斷上市/上櫃/ETF → 組特徵」整合成一個入口，供 run_all.py 與 tune.py 共用。"""
from dataclasses import dataclass, field

import pandas as pd

from data_source import fetch_prices
from features import build_features
from ticker_utils import instrument_warnings, is_etf, market_index_for, resolve_ticker


@dataclass
class Prepared:
    code: str
    ticker: str
    kind: str                     # "stock" | "etf"
    df: pd.DataFrame
    X: pd.DataFrame
    market_name: str
    peers_used: list
    warnings: list = field(default_factory=list)
    inputs: dict = field(default_factory=dict)   # 組特徵用的原始輸入，供因果性檢查重算

    @property
    def close(self) -> pd.Series:
        return self.df["Close"]

    @property
    def n_valid(self) -> int:
        return int(self.X.notna().all(axis=1).sum())


def allowed_horizons(n_valid: int, all_horizons: list) -> list:
    """資料不足時只訓練短天期；太少就完全跳過。"""
    if n_valid < 150:
        return []
    if n_valid < 600:
        return [h for h in all_horizons if h <= 20]
    return list(all_horizons)


def prepare(stock_cfg: dict, years: int = 6) -> Prepared:
    code = str(stock_cfg["code"]).strip().upper()
    ticker = resolve_ticker(code, years)
    df = fetch_prices(ticker, years)
    if df is None:
        raise ValueError(f"{ticker} 抓不到資料")
    warns = instrument_warnings(code)
    dropped = df.attrs.get("dropped_zero_volume", 0)
    if dropped > 5:
        warns.append(f"已排除 {dropped} 筆成交量為 0 的資料（可能停牌）")

    market, market_name = market_index_for(ticker, years)
    if ticker.endswith(".TWO") and market_name == "^TWII":
        warns.append("櫃買指數抓不到，改用加權指數作為大盤基準")
    if market is None:
        warns.append("大盤資料抓取失敗，大盤相關特徵以 0 代替")

    sox, mu = fetch_prices("^SOX", years), fetch_prices("MU", years)
    for name, d in (("費半(SOX)", sox), ("美光(MU)", mu)):
        if d is None:
            warns.append(f"{name} 抓取失敗，相關特徵以 0 代替")

    peer_codes = [str(p) for p in stock_cfg.get("peers", [])]
    kind = "etf" if is_etf(code) else "stock"
    if kind == "etf" and not peer_codes and code != "0050":
        peer_codes = ["0050"]  # ETF 沒設同業時，改比較「相對 0050」
    peers, used = [], []
    for p in peer_codes:
        if p == code:
            continue
        try:
            pdf = fetch_prices(resolve_ticker(p, years), years)
        except ValueError:
            pdf = None
        if pdf is not None:
            peers.append(pdf)
            used.append(p)
        else:
            warns.append(f"同業 {p} 抓取失敗，已略過")

    X = build_features(df, market, sox, mu, peers)
    inputs = {"market": market, "sox": sox, "mu": mu, "peers": peers or None}
    return Prepared(code, ticker, kind, df, X, market_name, used, warns, inputs)
