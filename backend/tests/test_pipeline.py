"""執行：  USE_SYNTHETIC=1 python -m pytest backend/tests -q
或：      USE_SYNTHETIC=1 python backend/tests/test_pipeline.py

全部使用合成資料，不需要網路。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("USE_SYNTHETIC", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backtest import run_backtest  # noqa: E402
from features import FEATURE_COLS, build_features, check_causality  # noqa: E402
from pipeline import prepare  # noqa: E402
from train import forecast  # noqa: E402
from tune import tune_stock  # noqa: E402

CFG = {"code": "2408", "peers": ["2344", "2337"]}


def test_no_leakage():
    """任一天的特徵，截斷到該日重算結果必須完全相同（含週/月線 MACD、大盤、同業）。"""
    prep = prepare(CFG, 6)
    i = prep.inputs
    assert check_causality(prep.df, i["market"], i["sox"], i["mu"], i["peers"], n_checks=8)


def test_leakage_detector_actually_detects():
    """故意讓特徵計算偷看明天（以及偷用未收完的週K），檢查器必須抓得到，確保測試本身有效。"""
    import features
    prep = prepare(CFG, 6)
    real = features.build_features

    def leaky_next_day(stock, *a, **k):
        f = real(stock, *a, **k)
        f["ret_1"] = np.log(stock["Close"]).diff().shift(-1)      # 偷看明天報酬
        return f

    def leaky_weekly(stock, *a, **k):
        f = real(stock, *a, **k)
        wk = stock["Close"].resample("W-FRI").last()              # 本週最後收盤（週三時還不知道）
        f["macd_w_dif"] = wk.reindex(stock.index, method="bfill") / stock["Close"] - 1
        return f

    i = prep.inputs
    for leaky in (leaky_next_day, leaky_weekly):
        features.build_features = leaky
        try:
            try:
                features.check_causality(prep.df, i["market"], i["sox"], i["mu"], i["peers"], n_checks=8)
            except AssertionError:
                continue
            raise AssertionError(f"檢查器沒有抓到 {leaky.__name__}")
        finally:
            features.build_features = real


def test_weekly_monthly_use_completed_bars_only():
    """週五以前的日期，週線 MACD 不可等於「包含本週收盤」的值。"""
    prep = prepare(CFG, 6)
    X = prep.X
    mid_week = [d for d in X.index[300:] if d.weekday() == 2][:20]   # 星期三
    for d in mid_week:
        nxt = X.index[X.index.get_loc(d) + 1]
        # 週三與週四的週線特徵應該相同（本週 K 棒還沒收完，不會變動）
        if nxt.weekday() == 3:
            assert np.allclose(X.loc[d, ["macd_w_dif", "macd_w_dea"]].values.astype(float),
                               X.loc[nxt, ["macd_w_dif", "macd_w_dea"]].values.astype(float), equal_nan=True)


def test_fixed_feature_columns_without_optional_data():
    prep = prepare(CFG, 6)
    X = build_features(prep.df)          # 沒有大盤/SOX/同業
    assert list(X.columns) == FEATURE_COLS


def test_no_tuning_leakage():
    """調參用到的最後一個標籤日必須早於外層回測起始日。"""
    prep = prepare({"code": "2408"}, 6)
    res = tune_stock(prep, outer_n=120, n_trials=3, per_model_seconds=20)
    assert res["max_date_used"] < res["outer_start_date"], (res["max_date_used"], res["outer_start_date"])


def test_pipeline_smoke_and_baselines():
    prep = prepare(CFG, 6)
    hs = [1, 5, 20, 60]
    bt = run_backtest(prep, hs, n_days=120)
    assert len(bt["ranking"]) == 3 and bt["ranking"][0]["rank"] == 1
    assert {b["horizon"] for b in bt["baselines"]} == set(hs)
    long = [m for m in bt["metrics"] if m["horizon"] == 60]
    assert all(m["status"] == "樣本不足" for m in long)          # 60 日只有約 2 個有效樣本，不得顯示準確度
    fc = forecast(prep, hs)
    assert len(fc["forecast"]) == 60 and fc["forecast"][0]["lower"] <= fc["forecast"][0]["upper"]


def test_random_walk_is_not_declared_reliable():
    """合成資料是隨機漫步：不應該有模型被判定為『有參考價值』。"""
    prep = prepare(CFG, 6)
    bt = run_backtest(prep, [1, 5, 10, 20], n_days=120)
    assert all(r["verdict"] == "參考價值低" for r in bt["ranking"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
