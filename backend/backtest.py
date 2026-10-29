"""Walk-forward 回測 + 嚴格評估（對應 Prompt 3 / 3.4）。

做法：過去 N 個交易日（預設 120），每隔 refit_every 天「只用當時已知標籤」重新訓練一次，
再預測接下來的日子。訓練列必須滿足 r + h <= 區塊起點，避免用到還沒發生的標籤。

評估重點（避免被假高分騙）：
  - 三個單邊基準：永遠猜漲 / 永遠猜跌 / 依訓練期多數方向
  - balanced accuracy、預測看漲比例、Spearman IC
  - 有效樣本數 n_effective = n / h，並用「區塊長度 = h」的 block bootstrap 求 95% 信賴區間
  - 非重疊（每隔 h 天取一點）的命中率
  - 判定「有參考價值」必須同時：打贏單邊基準、信賴區間下界 > 0.5、看漲比例在 20%~80%、n_effective >= 5
"""
import numpy as np
import pandas as pd

from models import HORIZONS, MODEL_IDS, MODEL_NAMES, fit_model, get_params, make_targets

RANK_HORIZONS = [1, 5, 10, 20]   # 有足夠有效樣本、納入排名的天期
MIN_EFFECTIVE = 5
MIN_TRAIN = 150


# ---------------------------------------------------------------- 指標
def _bal(P, A):
    """balanced accuracy：上漲與下跌兩類各自命中率的平均（支援 1D/2D）。"""
    tp = (P & A).sum(-1)
    pos = A.sum(-1)
    tn = ((~P) & (~A)).sum(-1)
    neg = (~A).sum(-1)
    r1 = np.where(pos > 0, tp / np.maximum(pos, 1), np.nan)
    r0 = np.where(neg > 0, tn / np.maximum(neg, 1), np.nan)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return np.nanmean(np.stack([r1, r0]), axis=0)


def block_bootstrap_ci(P, A, block, B=400, seed=0):
    n = len(P)
    block = int(max(1, min(block, n)))
    nb = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block + 1, size=(B, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    vals = _bal(P[idx], A[idx])
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return float("nan"), float("nan")
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


# ---------------------------------------------------------------- walk-forward
def walk_forward(Xv, y, ok, h, mid, params, test_pos, refit_every=20):
    """回傳每個「結果已知」的測試日：預測的 h 日報酬、實際報酬、當時訓練期的平均報酬與多數方向。"""
    n = len(y)
    rows = np.arange(n)
    out = {"pos": [], "pred": [], "actual": [], "base_mean": [], "base_up": []}
    for s in range(0, len(test_pos), refit_every):
        block = test_pos[s:s + refit_every]
        b = block[0]
        tr = np.where(ok & ~np.isnan(y) & (rows + h <= b))[0]
        if len(tr) < MIN_TRAIN:
            continue
        cand = [t for t in block if ok[t] and not np.isnan(y[t])]
        if not cand:
            continue
        m = fit_model(mid, Xv[tr], y[tr], params)
        pred = m.predict(Xv[cand])
        out["pos"] += cand
        out["pred"] += list(pred)
        out["actual"] += list(y[cand])
        out["base_mean"] += [float(y[tr].mean())] * len(cand)
        out["base_up"] += [bool((y[tr] > 0).mean() >= 0.5)] * len(cand)
    return {k: np.array(v) for k, v in out.items()}


def evaluate(res, c0, h, seed=0):
    """c0：各測試日當天收盤價（用來換算股價誤差）。"""
    n = len(res["pos"])
    if n == 0:
        return None
    pred, act = res["pred"], res["actual"]
    P, A = pred > 0, act > 0
    up_ratio = float(A.mean())
    acc = float((P == A).mean())
    bal = float(_bal(P, A))
    n_eff = max(n / h, 1.0)
    base = {
        "up_ratio": up_ratio,
        "always_up_acc": up_ratio,
        "always_down_acc": 1 - up_ratio,
        "train_majority_acc": float((res["base_up"] == A).mean()),
    }
    price_act = c0 * np.exp(act)
    mape = float(np.mean(np.abs(c0 * np.exp(pred) - price_act) / price_act))
    naive_mape = float(np.mean(np.abs(c0 - price_act) / price_act))
    mean_mape = float(np.mean(np.abs(c0 * np.exp(res["base_mean"]) - price_act) / price_act))
    base.update({"naive_mape": naive_mape, "mean_ret_mape": mean_mape})

    row = {"horizon": h, "n": n, "n_effective": round(n_eff, 1)}
    if n_eff < MIN_EFFECTIVE:
        row["status"] = "樣本不足"
        row["reliable"] = False
        row["reasons"] = [f"有效樣本只有 {n_eff:.1f} 個（需 ≥ {MIN_EFFECTIVE}），不顯示準確度"]
        return row, base

    lo, hi = block_bootstrap_ci(P, A, h, seed=seed)
    ic = pd.Series(pred).corr(pd.Series(act), method="spearman") if np.std(pred) > 0 else float("nan")
    step = np.arange(0, n, h)
    no_acc = float((P[step] == A[step]).mean())
    up_pred = float(P.mean())
    best_one_sided = max(up_ratio, 1 - up_ratio)
    beats = acc > best_one_sided
    sig = lo > 0.5
    balanced_dir = 0.2 <= up_pred <= 0.8
    reasons = []
    if not beats:
        reasons.append(f"命中率 {acc:.1%} 沒有勝過單邊猜測（{best_one_sided:.1%}）")
    if not sig:
        reasons.append("95% 信賴區間包含 50%，統計上不顯著")
    if not balanced_dir:
        reasons.append(f"預測有 {up_pred:.0%} 的時間看漲，幾乎只在猜單一方向")
    row.update({
        "status": "ok",
        "direction_acc": acc, "balanced_acc": bal, "ci_low": lo, "ci_high": hi,
        "pred_up_ratio": up_pred, "ic": None if pd.isna(ic) else float(ic),
        "mape_price": mape, "mae_ret": float(np.mean(np.abs(pred - act))),
        "mae_naive_ret": float(np.mean(np.abs(act))),
        "beats_naive_mae": bool(np.mean(np.abs(pred - act)) < np.mean(np.abs(act))),
        "nonoverlap_acc": no_acc, "nonoverlap_n": int(len(step)),
        "beats_one_sided": bool(beats), "significant": bool(sig),
        "reliable": bool(beats and sig and balanced_dir), "reasons": reasons,
    })
    return row, base


# ---------------------------------------------------------------- 主流程
def run_backtest(prep, horizons, all_params=None, n_days=120, refit_every=20):
    X, close = prep.X, prep.close
    Xv = X.values.astype(float)
    ok = X.notna().all(axis=1).values
    n = len(X)
    test_pos = list(range(n - n_days, n))
    cv = close.values

    metrics, baselines, history_src = [], [], {}
    for h in horizons:
        y = make_targets(close, h).values
        base_row = None
        for mid in MODEL_IDS:
            res = walk_forward(Xv, y, ok, h, mid, get_params(all_params, mid, h), test_pos, refit_every)
            if len(res["pos"]) == 0:
                continue
            out = evaluate(res, cv[res["pos"]], h)
            row, base = out
            row["model"] = mid
            metrics.append(row)
            base_row = base
            if h == 1:
                history_src[mid] = res
        if base_row:
            baselines.append({"horizon": h, **base_row})

    ranking = rank_models(metrics)
    history = build_history(prep, history_src)
    return {"metrics": metrics, "baselines": baselines, "ranking": ranking, "history": history}


def rank_models(metrics):
    rows = []
    for mid in MODEL_IDS:
        ms = [m for m in metrics if m["model"] == mid and m["horizon"] in RANK_HORIZONS and m["status"] == "ok"]
        if not ms:
            rows.append({"model": mid, "name": MODEL_NAMES[mid], "balanced_acc": None, "direction_acc": None,
                         "valid_horizons": 0, "pass_count": 0, "verdict": "參考價值低",
                         "reasons": ["回測樣本不足，無法評估"]})
            continue
        passed = [m for m in ms if m["reliable"]]
        rows.append({
            "model": mid, "name": MODEL_NAMES[mid],
            "balanced_acc": float(np.mean([m["balanced_acc"] for m in ms])),
            "direction_acc": float(np.mean([m["direction_acc"] for m in ms])),
            "valid_horizons": len(ms), "pass_count": len(passed),
            "verdict": "有參考價值" if len(passed) >= 2 else "參考價值低",
            "reasons": ([] if len(passed) >= 2 else
                        [f"{len(ms)} 個可評估天期中只有 {len(passed)} 個通過全部檢驗（需 ≥ 2）"]),
        })
    rows.sort(key=lambda r: (r["balanced_acc"] is None, -(r["balanced_acc"] or 0)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def build_history(prep, history_src):
    """過去半年每日：隔天實際收盤 vs 各模型用『前一天資料』預測的隔天收盤。"""
    idx, cv = prep.df.index, prep.close.values
    by_date = {}
    for mid, res in history_src.items():
        for t, p in zip(res["pos"], res["pred"]):
            if t + 1 >= len(idx):
                continue
            d = str(idx[t + 1].date())
            row = by_date.setdefault(d, {"date": d, "actual": round(float(cv[t + 1]), 2)})
            row[mid] = round(float(cv[t] * np.exp(p)), 2)
    return [by_date[d] for d in sorted(by_date)]
