"""Forecast scenarios, not a backtested trading strategy. No interpolated extrema."""
import math


DEFAULTS = {
    "fee_rate": 0.001425,
    "sell_tax_rate": 0.003,
    "slippage_rate": 0.001,
    "min_net_return": 0.05,
    "window_days": 5,
}


def net_return(buy, sell, costs):
    entry = buy * (1 + costs["slippage_rate"]) * (1 + costs["fee_rate"])
    exit_value = sell * (1 - costs["slippage_rate"]) * (
        1 - costs["fee_rate"] - costs["sell_tax_rate"]
    )
    return exit_value / entry - 1


def build_trade_plan(fc, metrics, last_close, settings=None, synthetic=False):
    costs = {**DEFAULTS, **(settings or {})}
    for key in DEFAULTS:
        value = costs[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"trade_plan.{key} must be finite")
        if key == "window_days":
            if not 0 <= value <= 20 or int(value) != value:
                raise ValueError("trade_plan.window_days must be an integer from 0 to 20")
        elif not 0 <= value < 1:
            raise ValueError(f"trade_plan.{key} must be from 0 to less than 1")
    rows = fc.get("forecast", [])
    result = {
        "version": 1, "status": "watch", "label": "觀望", "reasons": [],
        "costs": costs, "candidate": None, "strategy_backtested": False,
        "date_note": "日期以週一至週五估算，未扣除台股休市日；時間窗不是成交保證。",
        "method_note": "只比較模型直接預測的天期，選取扣除成本後報酬最高的先買後賣組合；價格為預測收盤價，非限價單或盤中成交價。",
    }
    if not rows or not math.isfinite(last_close) or last_close <= 0:
        result["reasons"].append("預測資料不足")
        return result
    preds = fc.get("horizon_preds", {})
    models = sorted(preds)
    if len(models) < 2:
        result["reasons"].append("可比較模型不足")
        return result
    horizons = sorted(set.intersection(*[
        {int(h) for h in preds[mid] if 1 <= int(h) <= min(len(rows), 120)} for mid in models
    ]))
    points = []
    for h in horizons:
        prices = {mid: last_close * math.exp(preds[mid][str(h)]) for mid in models}
        if not all(math.isfinite(p) and p > 0 for p in prices.values()):
            continue
        points.append({"day": h, "prices": prices, "price": sum(prices.values()) / len(models)})
    best = None
    for i, buy in enumerate(points):
        for sell in points[i + 1:]:
            gain = net_return(buy["price"], sell["price"], costs)
            if best is None or gain > best[0]:
                best = (gain, buy, sell)
    if best is None:
        result["reasons"].append("直接預測天期不足，無法形成先買後賣的組合")
        return result
    gain, buy, sell = best
    window = int(costs["window_days"])
    # Split windows between anchors so an entry window never overlaps its exit.
    split = (buy["day"] + sell["day"]) // 2

    def leg(point, start, end):
        day = point["day"]
        return {
            "day": day, "date": rows[day - 1]["date"],
            "window": [rows[start - 1]["date"], rows[end - 1]["date"]],
            "price": point["price"],
            "price_range": [min(point["prices"].values()), max(point["prices"].values())],
        }

    model_returns = {mid: net_return(buy["prices"][mid], sell["prices"][mid], costs) for mid in models}
    supported = [mid for mid in models if all(any(
        m.get("model") == mid and m.get("horizon") == h
        and m.get("status") == "ok" and m.get("reliable") is True
        for m in metrics
    ) for h in (buy["day"], sell["day"]))]
    result["candidate"] = {
        "buy": leg(buy, max(1, buy["day"] - window), min(split, buy["day"] + window)),
        "sell": leg(sell, max(split + 1, sell["day"] - window), min(len(rows), sell["day"] + window)),
        "gross_return": sell["price"] / buy["price"] - 1,
        "net_return": gain, "model_net_returns": model_returns,
        "supporting_models": supported,
    }
    if synthetic:
        result["reasons"].append("合成示範資料，不產生買賣訊號")
    if gain < costs["min_net_return"]:
        result["reasons"].append("預估淨報酬未達設定門檻")
    if any(r <= 0 for r in model_returns.values()):
        result["reasons"].append("模型對此組合的淨報酬方向不一致或不看漲")
    if len(supported) < 2:
        result["reasons"].append("買入及賣出天期未同時獲至少兩個模型通過方向回測；短期排名不代表半年有效")
    if not result["reasons"]:
        result.update(status="scenario", label="可追蹤情境")
    result["reasons"].append("此買賣規則尚未完成策略回測，預估報酬不是歷史績效或保證報酬")
    return result
