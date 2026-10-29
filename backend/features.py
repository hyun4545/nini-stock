"""特徵工程。

【防洩漏原則】
特徵表的第 t 列「只使用 <= t 日收盤時已知的資料」，目標是「t 日收盤後的未來報酬」。
所以預測時用最後一列特徵 → 預測未來，不會偷看未來。

週線 / 月線 MACD：
  resample 後每根 K 棒的標籤是「該週五 / 該月底」，只有標籤日 <= 當天時才會被帶入日線，
  因此「本週/本月尚未收完的 K 棒」永遠不會被使用。

這個性質由 check_causality() 驗證：把資料截斷到任意日期重算，該日的特徵必須與用全部資料算出來的完全相同。
"""
import numpy as np
import pandas as pd

FEATURE_COLS = [
    # 價格
    "ret_1", "ret_5", "ret_20", "ret_60", "bias_20", "bias_60",
    # 成交量
    "vol_ratio", "vol_chg",
    # 波動度
    "vola_20", "atr_14",
    # 均線
    "ma_align", "ma20_slope", "ma60_slope",
    # RSI
    "rsi_14",
    # MACD 日 / 週 / 月（皆以收盤價正規化）
    "macd_d_dif", "macd_d_dea", "macd_d_hist",
    "macd_w_dif", "macd_w_dea", "macd_w_hist",
    "macd_m_dif", "macd_m_dea", "macd_m_hist",
    # 大盤趨勢
    "mkt_ret_20", "mkt_bias_60", "mkt_above_ma20",
    # 產業 / 相對強弱
    "rel_mkt_5", "rel_mkt_20", "rel_peer_20", "rel_sox_20",
    "sox_ret_5", "sox_ret_20", "mu_ret_20",
]


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def _macd(c: pd.Series, min_periods: int):
    ema12 = c.ewm(span=12, adjust=False, min_periods=min_periods).mean()
    ema26 = c.ewm(span=26, adjust=False, min_periods=min_periods).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea, dif - dea


def _macd_tf(close: pd.Series, rule: str, min_periods: int, daily_index) -> pd.DataFrame:
    """週/月 MACD → 對齊回日線。標籤日 > 當天的 K 棒（未收完）不會被帶入。"""
    bars = close.resample(rule).last().dropna()
    dif, dea, hist = _macd(bars, min_periods)
    out = pd.DataFrame({"dif": dif / bars, "dea": dea / bars, "hist": hist / bars})
    return out.reindex(daily_index, method="ffill")


def _aligned(df, idx):
    """把另一檔資料的收盤價對齊到個股日期（休市日用前值補，最多補 5 天）。"""
    if df is None:
        return None
    return df["Close"].reindex(idx, method="ffill", limit=5)


def build_features(stock, market=None, sox=None, mu=None, peers=None) -> pd.DataFrame:
    idx = stock.index
    c, h, l, v = stock["Close"], stock["High"], stock["Low"], stock["Volume"]
    lc = np.log(c)
    lr = lc.diff()
    f = pd.DataFrame(index=idx)

    # 價格
    f["ret_1"], f["ret_5"], f["ret_20"], f["ret_60"] = lr, lc.diff(5), lc.diff(20), lc.diff(60)
    ma5, ma20, ma60 = (c.rolling(n).mean() for n in (5, 20, 60))
    f["bias_20"], f["bias_60"] = c / ma20 - 1, c / ma60 - 1

    # 成交量
    f["vol_ratio"] = v / v.rolling(20).mean()
    f["vol_chg"] = np.log(v.where(v > 0)).diff()

    # 波動度
    f["vola_20"] = lr.rolling(20).std() * np.sqrt(252)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    f["atr_14"] = tr.ewm(alpha=1 / 14, min_periods=14).mean() / c

    # 均線
    align = (ma5 > ma20).astype(float) + (ma20 > ma60).astype(float)
    f["ma_align"] = align.where(ma60.notna())
    f["ma20_slope"], f["ma60_slope"] = ma20.pct_change(5), ma60.pct_change(10)

    # RSI
    f["rsi_14"] = _rsi(c)

    # MACD（日 / 週 / 月）
    d_dif, d_dea, d_hist = _macd(c, 26)
    f["macd_d_dif"], f["macd_d_dea"], f["macd_d_hist"] = d_dif / c, d_dea / c, d_hist / c
    w = _macd_tf(c, "W-FRI", 26, idx)
    f["macd_w_dif"], f["macd_w_dea"], f["macd_w_hist"] = w["dif"], w["dea"], w["hist"]
    m = _macd_tf(c, "ME", 12, idx)  # 月線資料少，最小期數放寬為 12 根
    f["macd_m_dif"], f["macd_m_dea"], f["macd_m_hist"] = m["dif"], m["dea"], m["hist"]

    # 大盤趨勢與相對強弱（缺資料的欄位固定補 0，確保欄位順序/數量永遠一致）
    mk = _aligned(market, idx)
    sx = _aligned(sox, idx)
    mu_c = _aligned(mu, idx)
    zero = pd.Series(0.0, index=idx)
    if mk is not None:
        lm = np.log(mk)
        f["mkt_ret_20"] = lm.diff(20)
        f["mkt_bias_60"] = mk / mk.rolling(60).mean() - 1
        mm = mk.rolling(20).mean()
        f["mkt_above_ma20"] = (mk > mm).astype(float).where(mm.notna())
        f["rel_mkt_5"], f["rel_mkt_20"] = f["ret_5"] - lm.diff(5), f["ret_20"] - lm.diff(20)
    else:
        for k in ("mkt_ret_20", "mkt_bias_60", "mkt_above_ma20", "rel_mkt_5", "rel_mkt_20"):
            f[k] = zero
    if sx is not None:
        ls = np.log(sx)
        f["sox_ret_5"], f["sox_ret_20"] = ls.diff(5), ls.diff(20)
        f["rel_sox_20"] = f["ret_20"] - ls.diff(20)
    else:
        for k in ("sox_ret_5", "sox_ret_20", "rel_sox_20"):
            f[k] = zero
    f["mu_ret_20"] = np.log(mu_c).diff(20) if mu_c is not None else zero
    pr = [np.log(a).diff(20) for a in (_aligned(p, idx) for p in (peers or [])) if a is not None]
    f["rel_peer_20"] = f["ret_20"] - pd.concat(pr, axis=1).mean(axis=1) if pr else zero

    f = f.replace([np.inf, -np.inf], np.nan)
    return f[FEATURE_COLS]


def summarize(X: pd.DataFrame) -> dict:
    ok = X.notna().all(axis=1)
    return {
        "n_features": X.shape[1],
        "date_from": str(X.index[0].date()),
        "date_to": str(X.index[-1].date()),
        "n_rows": len(X),
        "n_valid_rows": int(ok.sum()),
        "nan_ratio": round(float(X.isna().mean().mean()), 4),
    }


def _cut(df, d):
    return None if df is None else df.loc[:d]


def check_causality(stock, market=None, sox=None, mu=None, peers=None, n_checks=6, seed=0) -> bool:
    """test_no_leakage 的核心：截斷到日期 d 重算，d 當天的特徵必須與全量計算的結果一致。"""
    full = build_features(stock, market, sox, mu, peers)
    rng = np.random.default_rng(seed)
    lo = max(len(full) // 2, 1)
    for p in rng.choice(np.arange(lo, len(full) - 1), size=n_checks, replace=False):
        d = stock.index[p]
        part = build_features(
            _cut(stock, d), _cut(market, d), _cut(sox, d), _cut(mu, d),
            [_cut(x, d) for x in peers] if peers else None,
        )
        a, b = full.loc[d].values.astype(float), part.loc[d].values.astype(float)
        if not np.allclose(a, b, rtol=1e-6, atol=1e-9, equal_nan=True):
            bad = [FEATURE_COLS[i] for i in np.where(~np.isclose(a, b, rtol=1e-6, atol=1e-9, equal_nan=True))[0]]
            raise AssertionError(f"特徵含有未來資料！日期 {d.date()}，欄位：{bad}")
    return True
