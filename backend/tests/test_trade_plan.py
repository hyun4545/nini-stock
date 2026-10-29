"""Deterministic checks for chronology, cost arithmetic and evidence gates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trade_plan import DEFAULTS, build_trade_plan, net_return


def fixture():
    from datetime import date, timedelta
    import math
    rows = [{"date": str(date(2026, 1, 1) + timedelta(days=i))} for i in range(120)]
    preds = {m: {"5": math.log(0.9), "20": math.log(1.0), "120": math.log(1.2)}
             for m in ("rf", "gb", "ridge")}
    metrics = [{"model": m, "horizon": h, "status": "ok", "reliable": True}
               for m in preds for h in (5, 20, 120)]
    return {"forecast": rows, "horizon_preds": preds}, metrics


def test_costs_reduce_return_and_windows_do_not_overlap():
    fc, metrics = fixture()
    plan = build_trade_plan(fc, metrics, 100)
    c = plan["candidate"]
    assert plan["status"] == "scenario"
    assert c["buy"]["day"] == 5 and c["sell"]["day"] == 120
    assert c["buy"]["window"][1] < c["sell"]["window"][0]
    expected = 120 * .999 * (1 - .001425 - .003) / (90 * 1.001 * 1.001425) - 1
    assert abs(c["net_return"] - expected) < 1e-10
    assert c["net_return"] < c["gross_return"]
    assert plan["strategy_backtested"] is False


def test_short_term_reliability_cannot_validate_long_term_trade():
    fc, metrics = fixture()
    short = [m for m in metrics if m["horizon"] < 120]
    assert build_trade_plan(fc, short, 100)["status"] == "watch"


def test_synthetic_and_disagreement_force_watch():
    fc, metrics = fixture()
    assert build_trade_plan(fc, metrics, 100, synthetic=True)["status"] == "watch"
    fc["horizon_preds"]["ridge"]["120"] = -0.3
    assert build_trade_plan(fc, metrics, 100)["status"] == "watch"


def test_empty_short_and_falling_forecasts():
    assert build_trade_plan({}, [], 100)["candidate"] is None
    fc, metrics = fixture()
    fc["forecast"] = fc["forecast"][:5]
    assert build_trade_plan(fc, metrics, 100)["candidate"] is None
    fc, metrics = fixture()
    fc["horizon_preds"] = {m: {"5": -.01, "20": -.1, "120": -.2} for m in ("rf", "gb", "ridge")}
    assert build_trade_plan(fc, metrics, 100)["status"] == "watch"


def test_cost_validation_and_flat_prices():
    import pytest
    fc, metrics = fixture()
    for settings in ({"fee_rate": -1}, {"window_days": 1.5}, {"sell_tax_rate": float("nan")}):
        with pytest.raises(ValueError):
            build_trade_plan(fc, metrics, 100, settings)
    assert net_return(100, 100, DEFAULTS) < 0
