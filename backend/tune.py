"""自動調參（對應 Prompt 3.5），每週跑一次即可，不要每天跑。

防過擬合設計：
  1. 外層：最後 N 天（預設 120）完全不參與調參，只留給 backtest 打成績
  2. 內層：外層之前的資料用 TimeSeriesSplit(5 折, gap = horizon)，不 shuffle
  3. 搜尋空間刻意保守（淺樹、大葉節點、強正則化）
  4. 挑「穩」不挑「高」：分數 = 各折平均驗證分數 − 0.5 × 標準差
  5. 訓練分數 − 驗證分數落差 > 0.20 的參數直接淘汰；全部被淘汰就維持預設參數
  6. 調完仍打不贏基準，backtest 照樣會標「參考價值低」，不會為了贏而放寬搜尋空間
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone

import numpy as np
from sklearn.model_selection import TimeSeriesSplit

from backtest import _bal
from models import DEFAULTS, MODEL_IDS, PARAMS_DIR, fit_model, make_targets

log = logging.getLogger("tune")
TUNE_HORIZONS = [5, 10, 20]
MAX_GAP = 0.20


def sample_params(mid, rng):
    if mid == "ridge":
        return {"alpha": float(np.exp(rng.uniform(np.log(0.1), np.log(1000))))}
    if mid == "rf":
        return {"n_estimators": int(rng.integers(50, 151)), "max_depth": int(rng.integers(3, 9)),
                "min_samples_leaf": int(rng.integers(20, 101)), "max_features": float(rng.uniform(0.3, 0.7))}
    return {"learning_rate": float(np.exp(rng.uniform(np.log(0.01), np.log(0.1)))),
            "max_depth": int(rng.integers(3, 7)), "min_samples_leaf": int(rng.integers(20, 101)),
            "l2_regularization": float(rng.uniform(0, 10)), "max_iter": int(rng.integers(100, 301))}


def tune_one(Xv, y, ok, h, mid, outer_n, n_trials, time_budget, rng):
    """回傳 (best_params|None, 診斷列, 用到的最後一個標籤位置)。"""
    n = len(y)
    last_row = n - outer_n - h - 1           # 該列的標籤（r+h）仍早於外層起點 n-outer_n
    rows = np.where(ok[:last_row + 1] & ~np.isnan(y[:last_row + 1]))[0]
    if len(rows) < 300:
        return None, {"model": mid, "horizon": h, "note": "資料不足，維持預設"}, None
    t0 = time.time()
    best, tried = None, 0
    for trial in range(n_trials):
        if time.time() - t0 > time_budget:
            break
        p = DEFAULTS[mid] if trial == 0 else sample_params(mid, rng)   # 第 0 組 = 預設，當作比較基準
        tr_s, va_s = [], []
        for tr, va in TimeSeriesSplit(n_splits=5, gap=h).split(rows):
            tr_i, va_i = rows[tr], rows[va]
            m = fit_model(mid, Xv[tr_i], y[tr_i], p)
            tr_s.append(float(_bal(m.predict(Xv[tr_i]) > 0, y[tr_i] > 0)))
            va_s.append(float(_bal(m.predict(Xv[va_i]) > 0, y[va_i] > 0)))
        tried += 1
        gap = float(np.mean(tr_s) - np.mean(va_s))
        score = float(np.mean(va_s) - 0.5 * np.std(va_s))
        cand = {"params": p, "score": score, "train": float(np.mean(tr_s)), "val": float(np.mean(va_s)),
                "std": float(np.std(va_s)), "gap": gap, "rejected": gap > MAX_GAP}
        if not cand["rejected"] and (best is None or score > best["score"]):
            best = cand
    last_label_pos = int(rows[-1] + h)
    if best is None:
        return None, {"model": mid, "horizon": h, "tried": tried, "note": "所有參數落差過大，維持預設"}, last_label_pos
    diag = {"model": mid, "horizon": h, "tried": tried, **{k: round(best[k], 4) for k in ("train", "val", "std", "gap", "score")}}
    return best["params"], diag, last_label_pos


def tune_stock(prep, outer_n=120, n_trials=20, per_model_seconds=60, seed=0):
    X, close = prep.X, prep.close
    Xv, ok = X.values.astype(float), X.notna().all(axis=1).values
    rng = np.random.default_rng(seed)
    params, diags, max_pos = {m: {} for m in MODEL_IDS}, [], 0
    for h in TUNE_HORIZONS:
        y = make_targets(close, h).values
        for mid in MODEL_IDS:
            p, d, pos = tune_one(Xv, y, ok, h, mid, outer_n, n_trials, per_model_seconds, rng)
            diags.append(d)
            if p is not None:
                params[mid][str(h)] = p
            if pos is not None:
                max_pos = max(max_pos, pos)
            log.info("調參 %s h=%d：%s", mid, h, d)
    outer_start = X.index[len(X) - outer_n]
    return {
        "code": prep.code, "tuned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outer_start_date": str(outer_start.date()),
        "max_date_used": str(X.index[min(max_pos, len(X) - 1)].date()),
        "params": params, "diagnostics": diags,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from run_all import load_config
    from pipeline import prepare
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="只調參這一檔（代號，如 2408）")
    ap.add_argument("--trials", type=int, default=20)
    args = ap.parse_args()
    cfg = load_config()
    stocks = [s for s in cfg["stocks"] if not args.ticker or s["code"] == args.ticker]
    PARAMS_DIR.mkdir(parents=True, exist_ok=True)
    fail = 0
    for s in stocks:
        try:
            prep = prepare(s, cfg.get("history_years", 6))
            res = tune_stock(prep, cfg.get("backtest_days", 120), args.trials)
            (PARAMS_DIR / f"{prep.code}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            log.info("已存 %s", PARAMS_DIR / f"{prep.code}.json")
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.exception("調參失敗 %s：%s", s["code"], e)
    sys.exit(1 if stocks and fail == len(stocks) else 0)


if __name__ == "__main__":
    main()
