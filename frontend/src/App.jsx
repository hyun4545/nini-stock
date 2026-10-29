import React, { useEffect, useMemo, useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON } from "./api.js";

const COLORS = { gb: "var(--gb)", rf: "var(--rf)", ridge: "var(--ridge)" };
const HEX = { gb: "#1e8a5a", rf: "#c48a17", ridge: "#4c63c7" };

const num = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
const pct = (v, d = 1) => (v == null ? "–" : (v * 100).toFixed(d) + "%");
const shortDate = (s) => (s ? s.slice(0, 7) : "");

/* ---------- 小元件 ---------- */
function ChartTip({ active, payload, label, names, showBand }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  return (
    <div className="tt">
      <b>{label}</b>
      {row.actual != null && <div><span>實際收盤</span><span>{num(row.actual)}</span></div>}
      {Object.keys(names).map((k) =>
        row[k] != null ? (
          <div key={k}><span style={{ color: HEX[k] }}>{names[k]}</span><span>{num(row[k])}</span></div>
        ) : null
      )}
      {showBand && row.lower != null && (
        <div><span>80% 區間</span><span>{num(row.lower)} ~ {num(row.upper)}</span></div>
      )}
    </div>
  );
}

function Legend({ ranking, reliableOf }) {
  return (
    <div className="legend">
      {ranking.map((r) => (
        <span className="item" key={r.model}>
          <i className={reliableOf(r) ? "" : "dash"} style={{ background: HEX[r.model], borderColor: HEX[r.model] }} />
          {r.rank}. {r.name}
          {r.balanced_acc != null && <>（平衡準確度 {pct(r.balanced_acc, 2)}）</>}
          <span className={"tag" + (reliableOf(r) ? " ok" : "")}>{r.verdict}</span>
        </span>
      ))}
    </div>
  );
}

function Verdict({ d }) {
  const ok = d.any_reliable;
  return (
    <div className={"verdict" + (ok ? " ok" : "")} role="status">
      <strong>{d.overall_verdict}</strong>
      <p>
        {ok
          ? "通過驗證的條件：打贏單邊猜測、95% 信賴區間下界高於 50%、預測方向不偏單邊，且至少 2 個天期都成立。其餘模型仍屬參考價值低。"
          : "過去半年的方向判斷，沒有模型同時打贏單邊猜測並達到統計顯著。下方預測線與區間只能當作情境參考，不要當成買賣依據。"}
      </p>
    </div>
  );
}

function ForecastChart({ d, ranking, reliableOf }) {
  const rows = useMemo(() => d.forecast.map((r) => ({ ...r, span: +(r.upper - r.lower).toFixed(2) })), [d]);
  const names = Object.fromEntries(d.models.map((m) => [m.id, m.name]));
  const [lo, hi] = useMemo(() => {
    const all = d.forecast.flatMap((r) => [r.lower, r.upper, r.gb, r.rf, r.ridge]).concat(d.last_close);
    const mn = Math.min(...all), mx = Math.max(...all), pad = (mx - mn) * 0.06;
    return [Math.floor(mn - pad), Math.ceil(mx + pad)];
  }, [d]);
  return (
    <>
      <Legend ranking={ranking} reliableOf={reliableOf} />
      <div className="panel">
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={rows} margin={{ top: 8, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#c9d2da" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={56} tick={{ fontSize: 12 }} />
            <YAxis domain={[lo, hi]} tick={{ fontSize: 12 }} width={48} allowDecimals={false} />
            <Tooltip content={<ChartTip names={names} showBand />} />
            <Area dataKey="lower" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} activeDot={false} />
            <Area dataKey="span" stackId="band" stroke="none" fill="#7b8794" fillOpacity={0.2} isAnimationActive={false} activeDot={false} />
            <ReferenceLine y={d.last_close} stroke="#16212c" strokeDasharray="2 4"
              label={{ value: `最新收盤 ${num(d.last_close)}`, position: "insideTopLeft", fontSize: 12, fill: "#5b6874" }} />
            {ranking.map((r) => (
              <Line key={r.model} dataKey={r.model} stroke={HEX[r.model]} strokeWidth={2} dot={false}
                strokeDasharray={reliableOf(r) ? undefined : "6 4"} isAnimationActive={false} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function HistoryChart({ d, ranking }) {
  const names = Object.fromEntries(d.models.map((m) => [m.id, m.name]));
  const [lo, hi] = useMemo(() => {
    const all = d.history.flatMap((r) => [r.actual, r.gb, r.rf, r.ridge]).filter((v) => v != null);
    const mn = Math.min(...all), mx = Math.max(...all), pad = (mx - mn) * 0.06;
    return [Math.floor(mn - pad), Math.ceil(mx + pad)];
  }, [d]);
  return (
    <div className="panel">
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={d.history} margin={{ top: 8, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#c9d2da" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={56} tick={{ fontSize: 12 }} />
          <YAxis domain={[lo, hi]} tick={{ fontSize: 12 }} width={48} allowDecimals={false} />
          <Tooltip content={<ChartTip names={names} />} />
          <Line dataKey="actual" stroke="#16212c" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          {ranking.map((r) => (
            <Line key={r.model} dataKey={r.model} stroke={HEX[r.model]} strokeWidth={1.4} dot={false}
              strokeOpacity={0.85} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function RankingTable({ d }) {
  return (
    <div className="panel scroll">
      <table>
        <thead>
          <tr>
            <th>排名</th><th className="l">模型</th><th>平衡準確度</th><th>方向命中率</th>
            <th>通過天期</th><th className="l">判定</th>
          </tr>
        </thead>
        <tbody>
          {d.ranking.map((r) => (
            <tr key={r.model}>
              <td>{r.rank}</td>
              <td className="l">{r.name}</td>
              <td>{pct(r.balanced_acc, 2)}</td>
              <td>{pct(r.direction_acc, 2)}</td>
              <td>{r.pass_count} / {r.valid_horizons}</td>
              <td className="l"><span className={"tag" + (r.verdict === "有參考價值" ? " ok" : "")}>{r.verdict}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HorizonTable({ d }) {
  const hs = [...new Set(d.metrics.map((m) => m.horizon))].sort((a, b) => a - b);
  const nameOf = Object.fromEntries(d.models.map((m) => [m.id, m.name]));
  return (
    <div className="panel scroll">
      <table>
        <thead>
          <tr>
            <th className="l">模型</th><th>有效樣本</th><th>命中率</th><th>95% 區間</th>
            <th>看漲比例</th><th>非重疊命中率</th><th className="l">狀態</th>
          </tr>
        </thead>
        <tbody>
          {hs.map((h) => {
            const base = d.baselines.find((b) => b.horizon === h);
            return (
              <React.Fragment key={h}>
                <tr className="sep">
                  <td colSpan={7}>
                    預測 {h} 個交易日後的漲跌
                    {base && <>　｜　實際上漲比例 {pct(base.up_ratio)}　永遠猜漲 {pct(base.always_up_acc)}　永遠猜跌 {pct(base.always_down_acc)}</>}
                  </td>
                </tr>
                {d.metrics.filter((m) => m.horizon === h).map((m) => (
                  <tr key={m.model + h}>
                    <td className="l">{nameOf[m.model]}</td>
                    <td>{num(m.n_effective, 1)}</td>
                    {m.status === "ok" ? (
                      <>
                        <td>{pct(m.direction_acc)}</td>
                        <td>{pct(m.ci_low)} ~ {pct(m.ci_high)}</td>
                        <td>{pct(m.pred_up_ratio, 0)}</td>
                        <td>{pct(m.nonoverlap_acc)}（{m.nonoverlap_n}）</td>
                        <td className="l">
                          <span className={"tag" + (m.reliable ? " ok" : "")}>{m.reliable ? "通過" : "未通過"}</span>
                        </td>
                      </>
                    ) : (
                      <td colSpan={5} className="l dim">樣本不足，不顯示準確度</td>
                    )}
                  </tr>
                ))}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TradePlan({ plan }) {
  if (!plan) return (
    <section className="block">
      <h3>半年內買賣情境參考</h3>
      <p className="hint">目前資料尚未包含買賣情境。請以新版程式執行 Daily Train（勾選 force）後重新整理。</p>
    </section>
  );
  const c = plan.candidate;
  const costs = plan.costs;
  return (
    <section className="block" aria-label="半年內買賣情境參考">
      <h3>半年內買賣情境參考 · {plan.label}</h3>
      <p className="hint">{plan.method_note}</p>
      {c && (
        <>
          {plan.status === "watch" && <p className="hint">以下只展示模型情境，尚未符合追蹤條件。</p>}
          <div className="trade-grid">
            {[["買入參考", c.buy], ["賣出參考", c.sell]].map(([label, leg]) => (
              <div className="trade-card" key={label}>
                <h4>{label}</h4>
                <strong>NT$ {num(leg.price_range[0])}～{num(leg.price_range[1])}</strong>
                <p>模型平均價 NT$ {num(leg.price)}</p>
                <p>約 {leg.window[0]}～{leg.window[1]}</p>
                <p className="hint">預測錨點：第 {leg.day} 個估算交易日（{leg.date}）</p>
              </div>
            ))}
          </div>
          <p>此組合預估報酬：成本前 {pct(c.gross_return)} ／ 扣除成本後 {pct(c.net_return)}</p>
          <p className="hint">價格區間為各模型在錨點的預測價範圍，不是信賴區間。報酬以兩個錨點的模型平均價計算，不代表時間窗內任意成交價均可達成。</p>
          <details>
            <summary>各模型的預估淨報酬</summary>
            <ul>{Object.entries(c.model_net_returns).map(([mid, value]) => (
              <li key={mid}>{{ rf: "Random Forest", gb: "Gradient Boosting", ridge: "Ridge" }[mid] || mid}：{pct(value)}</li>
            ))}</ul>
          </details>
        </>
      )}
      <ul className="warns">{plan.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
      <p className="hint">
        成本假設：買賣各收手續費 {pct(costs.fee_rate, 4)}、賣出稅率 {pct(costs.sell_tax_rate, 2)}、
        買賣各計滑價 {pct(costs.slippage_rate, 2)}；淨報酬門檻 {pct(costs.min_net_return)}。
        可於 config.json 的 trade_plan 調整，未計最低手續費與股數取整。
      </p>
      <p className="hint">{plan.date_note} 每次資料更新會重新估算，請以最新收盤日為準。</p>
    </section>
  );
}

/* ---------- 主畫面 ---------- */
export default function App() {
  const [stocks, setStocks] = useState(null);
  const [code, setCode] = useState(() => (location.hash || "").replace("#", ""));
  const [input, setInput] = useState("");
  const [data, setData] = useState(null);
  const [state, setState] = useState("boot"); // boot | loading | ready | notfound | error
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    getJSON("/api/stocks", { onWaking: setWaking })
      .then((r) => {
        setStocks(r.stocks);
        setWaking(false);
        if (!code && r.stocks.length) setCode(r.stocks[0].code);
        else if (!r.stocks.length) setState("error");
      })
      .catch(() => setState("error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!code) return;
    setState("loading");
    getJSON(`/api/stock/${code}`, { onWaking: setWaking })
      .then((r) => { setData(r); setState("ready"); setWaking(false); history.replaceState(null, "", "#" + code); })
      .catch((e) => { setData(null); setState(e.code === 404 ? "notfound" : "error"); setWaking(false); });
  }, [code]);

  const onSubmit = (e) => {
    e.preventDefault();
    const c = input.trim().toUpperCase();
    if (c) setCode(c);
  };

  const ranking = data ? [...data.ranking].sort((a, b) => a.rank - b.rank) : [];
  const reliableOf = (r) => r.verdict === "有參考價值";

  return (
    <>
      <div className="wrap">
        <header className="top">
          <div>
            <h1>台股預測實驗室</h1>
            <p>三個模型的半年預測，與它們過去半年到底準不準</p>
          </div>
          <form className="search" onSubmit={onSubmit}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="輸入代號，例如 2408"
              aria-label="股票代號" inputMode="text" />
            <button className="btn" type="submit">查詢</button>
          </form>
        </header>

        {stocks && (
          <div className="chips" role="group" aria-label="已納入計算的標的">
            {stocks.map((s) => (
              <button key={s.code} className="chip" aria-pressed={s.code === code} onClick={() => { setInput(""); setCode(s.code); }}>
                {s.code} {s.name}
              </button>
            ))}
          </div>
        )}

        {waking && <div className="notice" role="status">伺服器喚醒中，約需 30～60 秒，會自動重試，請稍候…</div>}
        {state === "loading" && !waking && <div className="notice" role="status">載入中…</div>}
        {state === "notfound" && (
          <div className="notice err" role="alert">
            {code} 尚未納入每日計算。要加入請在 config.json 的 stocks 加上它，並手動執行一次 Daily Train；隔天起就會每日更新。
          </div>
        )}
        {state === "error" && !waking && (
          <div className="notice err" role="alert">連不到伺服器，或資料尚未產生（請確認 GitHub Actions 已跑過、API 網址設定正確）。</div>
        )}

        {data && state === "ready" && (
          <>
            <div className="meta">
              <h2>{data.name}（{data.code}）</h2>
              <span className="px">{num(data.last_close)}</span>
              <span className="sub">
                收盤日 {data.last_date}　更新 {data.updated_at.replace("T", " ").slice(0, 16)}　{data.ticker}　大盤基準 {data.market_index}
                {data.tuned ? "　已套用調參結果" : "　使用預設保守參數"}
              </span>
            </div>

            {data.synthetic && (
              <div className="notice err" role="alert">這是示範用的「合成資料」，不是真實股價。請依 README 執行 Daily Train 取得真實資料。</div>
            )}

            <Verdict d={data} />
            <TradePlan plan={data.trade_plan} />
            {data.warnings.length > 0 && (
              <ul className="warns">{data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            )}

            <section className="block">
              <h3>未來 {data.forecast_days} 個交易日預測</h3>
              <p className="hint">
                圖例依「過去半年準確度」由高到低排列。虛線代表該模型未通過驗證；灰色帶狀區是 80% 情境區間（取自過去 3 年同天期報酬的實際分佈），越遠越寬是正常的。
              </p>
              <ForecastChart d={data} ranking={ranking} reliableOf={reliableOf} />
            </section>

            <section className="block">
              <h3>準確度排名（過去半年回測）</h3>
              <p className="hint">
                每一天都只用「當時已知的資料」預測。平衡準確度 = 漲、跌兩種情況各自命中率的平均，50% 等於亂猜；排名取 {data.rank_horizons.join("、")} 日天期的平均。
              </p>
              <RankingTable d={data} />
              <details>
                <summary>各天期明細與單邊基準</summary>
                <HorizonTable d={data} />
              </details>
            </section>

            <section className="block">
              <h3>過去半年：隔日預測 vs 實際收盤</h3>
              <p className="hint">
                黑線是實際收盤，彩線是各模型用前一天資料預測的隔日收盤。兩者幾乎貼在一起是正常的：單日預測值非常接近前一日收盤，這也是「明日＝今日」很難被打敗的原因。
              </p>
              <HistoryChart d={data} ranking={ranking} />
            </section>
          </>
        )}
      </div>
      <footer className="disc">僅供研究參考，非投資建議</footer>
    </>
  );
}
