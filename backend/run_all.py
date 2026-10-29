"""GitHub Actions 的唯一入口：讀 config.json → 對每檔股票 抓資料→特徵→預測→回測→輸出 data/{code}.json

用法：
  python backend/run_all.py                 # 跑 config.json 全部
  python backend/run_all.py --ticker 2408   # 只跑一檔
  python backend/run_all.py --force         # 即使最新交易日沒變也重跑
  USE_SYNTHETIC=1 python backend/run_all.py # 不連網，用合成資料跑通流程/示範介面
"""
import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import data_source
from backtest import RANK_HORIZONS, run_backtest
from features import check_causality, summarize
from models import HORIZONS, MODEL_IDS, MODEL_NAMES, load_params
from pipeline import allowed_horizons, prepare
from train import feature_importance, forecast

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
log = logging.getLogger("run_all")
DISCLAIMER = "本系統僅供研究與學習參考，非投資建議；模型預測不保證未來表現。"


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def peak_mb() -> float:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 0)  # Linux: KB → MB
    except Exception:  # noqa: BLE001
        return -1


def clean(o):
    """遞迴轉成可 JSON 序列化：numpy → python、NaN/inf → None、浮點數取小數。"""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (float, np.floating)):
        return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 4)
    return o


def process(stock_cfg: dict, cfg: dict, force: bool) -> dict:
    t0 = time.time()
    years = cfg.get("history_years", 6)
    n_days = cfg.get("backtest_days", 120)
    prep = prepare(stock_cfg, years)

    out_file = DATA / f"{prep.code}.json"
    last_date = str(prep.df.index[-1].date())
    if out_file.exists() and not force:
        try:
            if json.loads(out_file.read_text(encoding="utf-8")).get("last_date") == last_date:
                log.info("%s 最新交易日 %s 沒變，略過（加 --force 可強制重跑）", prep.code, last_date)
                return {"code": prep.code, "skipped": True}
        except Exception:  # noqa: BLE001
            pass

    summ = summarize(prep.X)
    log.info("%s 特徵：%s", prep.code, summ)
    horizons = allowed_horizons(prep.n_valid, HORIZONS)
    if not horizons:
        raise ValueError(f"有效資料只有 {prep.n_valid} 筆（需 ≥ 150，約 1 年以上上市時間），已跳過")
    skipped = [h for h in HORIZONS if h not in horizons]
    if skipped:
        prep.warnings.append(f"資料不足，長天期 {skipped} 日未訓練；預測期間縮短為 {max(horizons)} 日")

    try:  # 因果性檢查：特徵不含未來資料
        i = prep.inputs
        check_causality(prep.df, i["market"], i["sox"], i["mu"], i["peers"], n_checks=3)
    except AssertionError as e:
        raise RuntimeError(str(e)) from e

    params = load_params(prep.code)
    fc = forecast(prep, horizons, params)
    bt = run_backtest(prep, horizons, params, n_days=n_days)
    imp, imp_warn = feature_importance(prep)
    prep.warnings += imp_warn

    ranking = bt["ranking"]
    passed = [r["name"] for r in ranking if r["verdict"] == "有參考價值"]
    verdict = ("部分模型通過驗證：" + "、".join(passed)) if passed else "沒有任何模型通過驗證"
    close = prep.close
    result = {
        "code": prep.code, "ticker": prep.ticker, "name": stock_cfg.get("name", prep.code),
        "type": prep.kind, "market_index": prep.market_name, "peers_used": prep.peers_used,
        "synthetic": data_source.use_synthetic(),
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes"),
        "last_date": last_date, "last_close": round(float(close.iloc[-1]), 2),
        "data_range": [summ["date_from"], summ["date_to"]], "n_valid_rows": prep.n_valid,
        "horizons_used": horizons, "horizons_skipped": skipped, "rank_horizons": RANK_HORIZONS,
        "tuned": bool(params), "warnings": prep.warnings, "overall_verdict": verdict,
        "any_reliable": bool(passed),
        "models": [{"id": m, "name": MODEL_NAMES[m]} for m in MODEL_IDS],
        "ranking": ranking, "metrics": bt["metrics"], "baselines": bt["baselines"],
        "history": bt["history"], "forecast": fc["forecast"], "forecast_days": fc["forecast_days"],
        "horizon_preds": fc["horizon_preds"], "clipped": fc["clipped"], "fit_seconds": fc["fit_seconds"],
        "feature_importance": imp, "disclaimer": DISCLAIMER,
    }
    DATA.mkdir(exist_ok=True)
    out_file.write_text(json.dumps(clean(result), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%s 完成：%.0f 秒，峰值記憶體 %s MB，結論：%s", prep.code, time.time() - t0, peak_mb(), verdict)
    return {"code": prep.code, "skipped": False}


def rebuild_index(cfg: dict) -> None:
    items = []
    for s in cfg["stocks"]:
        f = DATA / f"{s['code']}.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        items.append({k: d.get(k) for k in ("code", "name", "ticker", "type", "last_close", "last_date",
                                            "updated_at", "overall_verdict", "any_reliable", "synthetic")})
    (DATA / "index.json").write_text(json.dumps({"stocks": items}, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    stocks = [s for s in cfg["stocks"] if not args.ticker or s["code"] == args.ticker]
    if not stocks:
        log.error("config.json 找不到代號 %s", args.ticker)
        sys.exit(2)
    t0, ok, failed = time.time(), [], []
    for s in stocks:
        try:
            r = process(s, cfg, args.force or bool(args.ticker))
            ok.append(r["code"])
        except Exception as e:  # noqa: BLE001  單檔失敗不可中斷其他檔
            log.exception("%s 失敗：%s", s["code"], e)
            failed.append(f"{s['code']}（{e}）")
    rebuild_index(cfg)
    log.info("成功 %d 檔：%s", len(ok), ok)
    log.info("失敗 %d 檔：%s", len(failed), failed)
    log.info("總耗時 %.0f 秒，峰值記憶體 %s MB", time.time() - t0, peak_mb())
    sys.exit(1 if failed and not ok else 0)


if __name__ == "__main__":
    main()
