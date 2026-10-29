"""訓練與未來預測（對應 Prompt 2）。

- 目標：未來 h 日對數報酬，不直接預測股價
- direct multi-horizon：每個 h、每個模型各訓練一個，不做遞迴預測
- 其餘天數用線性內插，得到「未來每日預測」
- 信賴區間：用「過去 3 年 h 日報酬的無條件分佈（10%/90%）」圍繞在模型平均預測周圍，
  誠實反映「不確定性很大」，而不是假裝很精準
"""
import time

import numpy as np
import pandas as pd

from models import MODEL_IDS, fit_model, get_params, make_model, make_targets

FORECAST_DAYS = 120


def _future_dates(last_date, n):
    return pd.bdate_range(start=last_date + pd.Timedelta(days=1), periods=n)  # 以週一~五估算，未扣除國定假日


def forecast(prep, horizons, all_params=None, days=FORECAST_DAYS):
    X, close = prep.X, prep.close
    ok = X.notna().all(axis=1).values
    Xv = X.values.astype(float)
    if not ok[-1]:
        raise ValueError("最新一天的特徵有缺值，無法預測")
    x_last = Xv[-1:]
    last_close = float(close.iloc[-1])
    daily_sigma = float(np.log(close).diff().tail(250).std())

    preds = {m: {} for m in MODEL_IDS}
    centers, q_lo, q_hi, clipped, timings = {}, {}, {}, [], {}
    for h in horizons:
        y = make_targets(close, h).values
        tr = np.where(ok & ~np.isnan(y))[0]
        cap = 3.0 * daily_sigma * np.sqrt(h)      # 單一天期預測的合理上限
        for mid in MODEL_IDS:
            t0 = time.time()
            m = fit_model(mid, Xv[tr], y[tr], get_params(all_params, mid, h))
            p = float(m.predict(x_last)[0])
            if abs(p) > cap:
                clipped.append(f"{mid}@h{h}")
                p = float(np.clip(p, -cap, cap))
            preds[mid][h] = p
            timings[mid] = timings.get(mid, 0.0) + time.time() - t0
        centers[h] = float(np.mean([preds[m][h] for m in MODEL_IDS]))
        recent = y[tr][-756:]                     # 約 3 年
        q10, q50, q90 = np.quantile(recent, [0.1, 0.5, 0.9])
        q_lo[h], q_hi[h] = float(q10 - q50), float(q90 - q50)

    hs = sorted(horizons)
    n_days = min(days, max(hs))
    dates = _future_dates(close.index[-1], n_days)
    grid = np.arange(1, n_days + 1)
    xs = [0] + hs

    def interp(vals):
        return np.interp(grid, xs, [0.0] + [vals[h] for h in hs])

    series = {m: interp(preds[m]) for m in MODEL_IDS}
    center = interp(centers)
    lower, upper = center + interp(q_lo), center + interp(q_hi)
    px = lambda r: last_close * np.exp(r)  # noqa: E731
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "date": str(d.date()),
            **{m: round(float(px(series[m][i])), 2) for m in MODEL_IDS},
            "ensemble": round(float(px(center[i])), 2),
            "lower": round(float(px(lower[i])), 2),
            "upper": round(float(px(upper[i])), 2),
        })
    return {
        "forecast": rows,
        "horizon_preds": {m: {str(h): round(preds[m][h], 5) for h in hs} for m in MODEL_IDS},
        "clipped": clipped,
        "fit_seconds": {m: round(t, 1) for m, t in timings.items()},
        "forecast_days": n_days,
    }


def feature_importance(prep, h=20, top=10):
    """RF 的特徵重要性與 Ridge 標準化係數；單一特徵佔比 > 50% 會回報警告。"""
    X, close = prep.X, prep.close
    ok = X.notna().all(axis=1).values
    y = make_targets(close, h).values
    tr = np.where(ok & ~np.isnan(y))[0]
    Xv = X.values.astype(float)
    out, warns = {}, []
    rf = fit_model("rf", Xv[tr], y[tr])
    imp = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
    out["rf"] = [{"feature": k, "importance": round(float(v), 4)} for k, v in imp.head(top).items()]
    if imp.iloc[0] > 0.5:
        warns.append(f"Random Forest 單一特徵 {imp.index[0]} 佔比 {imp.iloc[0]:.0%}，請檢查是否洩漏")
    rd = fit_model("ridge", Xv[tr], y[tr])
    coef = pd.Series(np.abs(rd.named_steps["m"].coef_), index=X.columns)
    coef = (coef / coef.sum()).sort_values(ascending=False)
    out["ridge"] = [{"feature": k, "importance": round(float(v), 4)} for k, v in coef.head(top).items()]
    return out, warns
