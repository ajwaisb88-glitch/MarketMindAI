import React, { useState, useEffect, useCallback } from 'react';
import './Performance.css';

const META = {
  monster: { icon: '👹', name: 'Monster', color: '#e3b341' },
  whale: { icon: '🐋', name: 'Whale', color: '#58a6ff' },
  marketmind: { icon: '🧠', name: 'MarketMind', color: '#3fb950' },
};
const ORDER = ['monster', 'whale', 'marketmind'];
const SEED_ASSETS = ['gold', 'btc', 'eth', 'sol', 'xrp', 'doge'];

const STATUS = {
  TP: { label: '✅ TP', color: '#3fb950' },
  SL: { label: '❌ SL', color: '#ff7b72' },
  OPEN: { label: '⏳ Open', color: '#e3b341' },
  STALE: { label: '⚪ Expired', color: '#8b949e' },
};
const fmtP = (p) => (p == null ? '—' : p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 2 })
  : p >= 1 ? p.toFixed(2) : p.toFixed(5));
const ago = (ts) => {
  if (!ts) return '—';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export default function Performance({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [seeding, setSeeding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/signals/performance`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
    setLoading(false);
  }, [apiBase]);

  // Fire the feed for a spread of assets so signals start getting logged, then load.
  const seedAndLoad = useCallback(async () => {
    setSeeding(true);
    try {
      await Promise.all(SEED_ASSETS.map((a) =>
        fetch(`${apiBase}/signals/feed?asset=${a}`).catch(() => null)));
    } catch (e) { /* ignore */ }
    setSeeding(false);
    load();
  }, [apiBase, load]);

  useEffect(() => { load(); }, [load]);

  const sys = (key) => (data?.systems || []).find((s) => s.source === key);
  const recent = data?.recent || [];

  return (
    <div className="pf">
      <div className="pf-bar">
        <div className="pf-brand"><span>📊</span>SIGNAL <b>PERFORMANCE</b></div>
        <div className="pf-sub">Live-forward — every signal graded against real prices. Not simulated.</div>
        <button className="pf-refresh" onClick={load} disabled={loading}>{loading ? '…' : '↻ Refresh'}</button>
      </div>

      {err && <div className="pf-err">⚠ Performance unavailable — {err}</div>}

      <div className="pf-grid">
        {ORDER.map((key) => {
          const s = sys(key) || {};
          const m = META[key];
          const wr = s.win_rate;
          const closed = (s.wins || 0) + (s.losses || 0);
          return (
            <section key={key} className="pf-card" style={{ '--accent': m.color }}>
              <div className="pf-head">
                <span className="pf-ico">{m.icon}</span>
                <span className="pf-name">{m.name}</span>
              </div>
              <div className="pf-wr" style={{ color: wr == null ? '#8b949e' : wr >= 50 ? '#3fb950' : '#ff7b72' }}>
                {wr == null ? '—' : `${wr}%`}
              </div>
              <div className="pf-wrlabel">win rate {closed ? `(${closed} closed)` : ''}</div>
              <div className="pf-stats">
                <div className="ps"><span className="pk">Wins</span><span className="pv win">{s.wins || 0}</span></div>
                <div className="ps"><span className="pk">Losses</span><span className="pv loss">{s.losses || 0}</span></div>
                <div className="ps"><span className="pk">Open</span><span className="pv">{s.open || 0}</span></div>
                <div className="ps"><span className="pk">Avg R</span>
                  <span className="pv" style={{ color: (s.avg_r || 0) >= 0 ? '#3fb950' : '#ff7b72' }}>
                    {s.avg_r == null ? '—' : `${s.avg_r > 0 ? '+' : ''}${s.avg_r}R`}</span></div>
              </div>
            </section>
          );
        })}
      </div>

      <section className="pf-table-card">
        <div className="pf-ph">
          <span className="pt">RECENT SIGNAL OUTCOMES</span>
          <span className="psub">{data ? `${data.tracked} tracked · ${data.closed} closed` : ''}</span>
        </div>
        {recent.length === 0 ? (
          <div className="pf-empty">
            <div className="pf-empty-ic">🕓</div>
            <div className="pf-empty-t">No signals logged yet</div>
            <p>Signals are graded here as they fire and then hit their target or stop. Start collecting now:</p>
            <button className="pf-seed" onClick={seedAndLoad} disabled={seeding}>
              {seeding ? 'Scanning…' : '▶ Scan all assets now'}
            </button>
          </div>
        ) : (
          <div className="pf-table-wrap">
            <table className="pf-table">
              <thead>
                <tr><th>System</th><th>Asset</th><th>Dir</th><th>Grade</th><th>Entry</th><th>Stop</th><th>Target</th><th>R</th><th>Outcome</th><th>When</th></tr>
              </thead>
              <tbody>
                {recent.map((r) => {
                  const st = STATUS[r.status] || STATUS.OPEN;
                  const m = META[r.source] || {};
                  return (
                    <tr key={r.id + r.ts}>
                      <td>{m.icon} {m.name || r.source}</td>
                      <td className="mono">{r.asset.toUpperCase()}</td>
                      <td style={{ color: r.direction === 'BUY' ? '#3fb950' : '#ff7b72', fontWeight: 700 }}>{r.direction}</td>
                      <td>{r.grade}</td>
                      <td className="mono">{fmtP(r.entry)}</td>
                      <td className="mono sl">{fmtP(r.stop_loss)}</td>
                      <td className="mono tp">{fmtP(r.take_profit)}</td>
                      <td className="mono" style={{ color: (r.r_multiple || 0) >= 0 ? '#3fb950' : '#ff7b72' }}>
                        {r.r_multiple == null ? '—' : `${r.r_multiple > 0 ? '+' : ''}${r.r_multiple}`}</td>
                      <td style={{ color: st.color, fontWeight: 700 }}>{st.label}</td>
                      <td className="when">{ago(r.ts)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="pf-foot">
        Outcomes use real Binance price paths since each signal fired (stop wins ties). A signal still open after 7 days is marked expired.
      </div>
    </div>
  );
}
