import React, { useState, useEffect, useCallback } from 'react';
import './MarketRead.css';

const ASSETS = ['gold', 'xauusd', 'btc', 'eth', 'sol', 'silver'];
const TFS = ['D1', 'H4', 'H1', 'M15', 'M5', 'M1'];
const trendColor = (t) => (t === 'bull' ? '#3fb950' : t === 'bear' ? '#ff7b72' : '#8b949e');
const fmt = (p) => (p == null ? '—' : p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 2 }) : p >= 1 ? p.toFixed(2) : p.toFixed(5));

const LAYERS = [
  { key: 'htf', name: 'HTF trend', wkey: 'htf', measure: (l) => `D1 ${l.htf.D1} · H4 ${l.htf.H4} · H1 ${l.htf.H1}` },
  { key: 'bettervolume', name: 'BetterVolume (M15)', wkey: 'bv', measure: (l) => `${l.bettervolume.color} · vol ${l.bettervolume.vol_ratio}×` },
  { key: 'order_book', name: 'Order book / DOM', wkey: 'ob', measure: (l) => `${l.order_book.read} · imb ${l.order_book.imbalance >= 0 ? '+' : ''}${l.order_book.imbalance}` },
  { key: 'order_flow', name: 'Order flow (CVD)', wkey: 'of', measure: (l) => `${l.order_flow.read} · Δ ${l.order_flow.cvd ?? '—'}` },
  { key: 'pressure', name: 'Taker pressure / spoof', wkey: 'pr', measure: (l) => `${l.pressure.side} · spoof ${l.pressure.spoof_prob_pct}%` },
];

export default function MarketRead({ apiBase }) {
  const [asset, setAsset] = useState('gold');
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/market/read?asset=${asset}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      if (j.status !== 'ok') throw new Error(j.message || 'no data');
      setD(j);
    } catch (e) { setErr(String(e.message || e)); setD(null); }
    setLoading(false);
  }, [apiBase, asset]);

  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [load]);

  const dir = d?.direction, grade = d?.grade;
  const dirColor = dir === 'BUY' ? '#3fb950' : dir === 'SELL' ? '#ff7b72' : '#8b949e';
  const bias = d?.bias ?? 0;
  const e = d?.entry;

  return (
    <div className="mr">
      <div className="mr-bar">
        <div className="mr-brand"><span>📐</span>MARKET <b>READ</b></div>
        <div className="mr-pick"><label>Asset</label>
          <select value={asset} onChange={(ev) => setAsset(ev.target.value)}>
            {ASSETS.map((a) => <option key={a} value={a}>{a.toUpperCase()}</option>)}
          </select></div>
        <div className="mr-sub">order flow + DOM heat-map + BetterVolume × institutional time</div>
        <button className="mr-refresh" onClick={load} disabled={loading}>{loading ? '…' : '↻'}</button>
      </div>

      {err && <div className="mr-err">⚠ {err}</div>}

      {d && (
        <>
          <section className="mr-hero">
            <div className="mr-hero-l">
              <div className="mr-price">{fmt(d.price)}<span> {asset.toUpperCase()}</span></div>
              <div className="mr-win">{d.window.label} · {d.window.liquidity} liquidity · {d.tradeable ? 'tradeable' : 'stand aside'}</div>
            </div>
            <div className="mr-hero-r">
              <div className="mr-dir" style={{ color: dirColor }}>{dir === 'NONE' ? 'NO TRADE' : dir}</div>
              <div className="mr-grade" style={{ borderColor: dirColor, color: dirColor }}>{grade}</div>
              <div className="mr-conf">conf {d.confidence}%</div>
            </div>
          </section>

          <div className="mr-bias">
            <span className="l">NET BIAS</span>
            <div className="mr-bias-track">
              <div className="mid" />
              <div className="fill" style={{ width: `${Math.min(50, Math.abs(bias) * 50)}%`,
                left: bias >= 0 ? '50%' : `${50 - Math.min(50, Math.abs(bias) * 50)}%`,
                background: bias >= 0 ? '#3fb950' : '#ff7b72' }} />
            </div>
            <span className="v" style={{ color: dirColor }}>{bias >= 0 ? '+' : ''}{bias}</span>
          </div>

          <div className="mr-tfs">
            <span className="mr-tfs-k">TIMEFRAMES</span>
            {TFS.map((tf) => (
              <span key={tf} className="mr-tf">
                <span className="t">{tf}</span>
                <span className="d" style={{ color: trendColor(d.timeframes[tf]) }}>
                  {d.timeframes[tf] === 'bull' ? '▲' : d.timeframes[tf] === 'bear' ? '▼' : '■'} {d.timeframes[tf]}</span>
              </span>
            ))}
          </div>

          <section className="mr-layers">
            <div className="mr-ph"><span className="pt">THE MATH — WHAT THE MARKET IS DOING</span>
              <span className="psub">bias = Σ weight × score</span></div>
            <table className="mr-table">
              <thead><tr><th>Layer</th><th>Measurement</th><th>Score</th><th>Weight</th><th>Contribution</th></tr></thead>
              <tbody>
                {LAYERS.map((L) => {
                  const lay = d.layers[L.key]; const w = d.weights[L.wkey]; const sc = lay.score || 0;
                  const contrib = w * sc;
                  return (
                    <tr key={L.key}>
                      <td className="mr-lname">{L.name}</td>
                      <td className="mr-lmeas">{L.measure(d.layers)}</td>
                      <td className="mono" style={{ color: sc > 0.03 ? '#3fb950' : sc < -0.03 ? '#ff7b72' : '#8b949e' }}>{sc >= 0 ? '+' : ''}{sc}</td>
                      <td className="mono dim">{w}</td>
                      <td className="mono" style={{ color: contrib > 0.01 ? '#3fb950' : contrib < -0.01 ? '#ff7b72' : '#8b949e' }}>{contrib >= 0 ? '+' : ''}{contrib.toFixed(3)}</td>
                    </tr>
                  );
                })}
                <tr className="mr-total"><td colSpan={4}>NET BIAS (gated by time × discounted by spoof → confidence {d.confidence}%)</td>
                  <td className="mono" style={{ color: dirColor }}>{bias >= 0 ? '+' : ''}{bias}</td></tr>
              </tbody>
            </table>
          </section>

          {e ? (
            <section className="mr-entry" style={{ '--dir': dirColor }}>
              <div className="mr-ph"><span className="pt">🎯 PINPOINT ENTRY — multi-timeframe</span>
                <span className="psub">{e.entry_tf} entry · stop {e.stop_basis}</span></div>
              <div className="mr-entry-grid">
                <div className="mr-cell"><span className="k">Entry ({e.entry_tf})</span><span className="v">{fmt(e.entry)}</span></div>
                <div className="mr-cell"><span className="k">Stop</span><span className="v sl">{fmt(e.stop_loss)}</span></div>
                <div className="mr-cell"><span className="k">TP1 · 1R</span><span className="v tp">{fmt(e.tp1)}</span></div>
                <div className="mr-cell"><span className="k">TP2 · 2R</span><span className="v tp">{fmt(e.tp2)}</span></div>
                <div className="mr-cell"><span className="k">TP3 · 3R ⤳</span><span className="v tp">{fmt(e.tp3)}</span></div>
                <div className="mr-cell"><span className="k">Risk / R:R</span><span className="v">{fmt(e.risk)} · {e.risk_reward}:1</span></div>
              </div>
              <div className="mr-entry-note">{e.note}</div>
            </section>
          ) : (
            <section className="mr-noentry">No entry — {d.tradeable ? 'factors not aligned enough.' : 'not a prime institutional window (stand aside).'}</section>
          )}

          <div className="mr-reason">{d.reason}</div>
        </>
      )}
    </div>
  );
}
