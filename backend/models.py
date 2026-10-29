"""模型工廠、保守的預設參數、調參結果讀取。

刻意只用輕量模型（Render/Actions 記憶體友善）：
  Ridge / RandomForest（n_jobs=1、淺樹）/ HistGradientBoosting（取代 XGBoost，更省記憶體）

HistGradientBoosting 不啟用 early_stopping：sklearn 內建的驗證集是「隨機切分」，
對時間序列等於偷看未來，所以改用固定的小 max_iter 控制複雜度。
"""
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MODEL_IDS = ["gb", "rf", "ridge"]
MODEL_NAMES = {"gb": "Gradient Boosting", "rf": "Random Forest", "ridge": "Ridge"}
HORIZONS = [1, 5, 10, 20, 40, 60, 90, 120]

DEFAULTS = {
    "ridge": {"alpha": 100.0},
    "rf": {"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 40, "max_features": 0.5},
    "gb": {"learning_rate": 0.03, "max_depth": 3, "min_samples_leaf": 40,
           "l2_regularization": 5.0, "max_iter": 150},
}

PARAMS_DIR = Path(__file__).resolve().parent.parent / "data" / "params"


def make_model(mid: str, params: dict = None, seed: int = 42):
    p = {**DEFAULTS[mid], **(params or {})}
    if mid == "ridge":
        return Pipeline([("sc", StandardScaler()), ("m", Ridge(alpha=p["alpha"]))])
    if mid == "rf":
        return RandomForestRegressor(n_jobs=1, random_state=seed, **p)
    if mid == "gb":
        return HistGradientBoostingRegressor(early_stopping=False, random_state=seed, **p)
    raise ValueError(mid)


def make_targets(close, h: int):
    """未來 h 日對數報酬（最後 h 列為 NaN，因為還沒發生）。"""
    return np.log(close.shift(-h) / close)


def fit_model(mid: str, X, y, params: dict = None):
    """訓練前先把極端報酬壓在 1%~99% 分位，避免少數暴漲暴跌帶偏模型。"""
    lo, hi = np.quantile(y, [0.01, 0.99])
    m = make_model(mid, params)
    m.fit(X, np.clip(y, lo, hi))
    return m


def load_params(code: str) -> dict:
    """讀取 tune.py 產生的最佳參數；沒有檔案就回傳空（使用保守預設）。"""
    try:
        return json.loads((PARAMS_DIR / f"{code}.json").read_text(encoding="utf-8")).get("params", {})
    except Exception:  # noqa: BLE001
        return {}


def get_params(all_params: dict, mid: str, h: int):
    """取該模型「最接近 h」的已調參結果；沒有就回傳 None（用預設）。"""
    tuned = (all_params or {}).get(mid) or {}
    if not tuned:
        return None
    key = min(tuned.keys(), key=lambda k: abs(int(k) - h))
    return tuned[key]
