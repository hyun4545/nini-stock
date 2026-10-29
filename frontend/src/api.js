const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

/**
 * 讀取 API。Render 免費版閒置會休眠，第一次請求可能要 30~60 秒：
 * 失敗時自動重試，並透過 onWaking 通知畫面顯示「伺服器喚醒中」。
 * 404（尚未納入每日計算）不重試。
 */
export async function getJSON(path, { onWaking, tries = 12, gap = 5000 } = {}) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 25000);
    try {
      const res = await fetch(BASE + path, { signal: ctrl.signal });
      clearTimeout(timer);
      if (res.status === 404 || res.status === 400) {
        const e = new Error("not_found");
        e.code = 404;
        throw e;
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      return await res.json();
    } catch (e) {
      clearTimeout(timer);
      if (e.code === 404) throw e;
      lastErr = e;
      if (i === 0 && onWaking) onWaking(true);
      await new Promise((r) => setTimeout(r, gap));
    }
  }
  throw lastErr;
}
