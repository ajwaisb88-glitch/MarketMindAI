import React, { useState, useEffect, useCallback } from 'react';
import './Confluence.css';

const ASSETS = ['gold', 'xauusd', 'btc', 'eth', 'sol', 'xrp', 'silver', 'eurusd', 'gbpusd'];
const MODES = [
  { key: 'SCALP', label: 'Scalp' },
  { key: 'INTRADAY', label: 'Intraday' },
  { key: 'SWING', label: 'Swing' },
  { key: 'LONGTERM', label: 'Long-term' },
];
const clean = (s) => String(s || '').replace(/�/g, '→');
const gradeColor = (g) => (g === 'A+' ? '#3fb950' : g === 'A1' ? '#4cc266' : g === 'A' ? '#6bd07f'
  : g === 'B' ? '#e3b341' : '#f0883e');

export default function Confluence({ apiBase }) {
  const [asset, setAsset] = useState('gold');
  const [mode, setMode] = useState('SWING');
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/monster/confluence?asset=${asset}&mode=${mode}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (d.status !== 'ok') throw new Error(d.message || 'no data');
      setData(d);
    } catch (e) { setErr(String(e.message || e)); setData(null); }
    setLoading(false);
  }, [apiBase, asset, mode]);

  useEffect(() => { load(); }, [load]);

  const sc = data?.score || {};
  const best = Math.max(sc.buy || 0, sc.sell || 0);
  const side = data?.side || 'WAIT';
  const isBuy = side.includes('BUY');
  const isSell = side.includes('SELL');
  const sideColor = isBuy ? '#3fb950' : isSell ? '#ff7b72' : '#8b949e';
  const htf = data?.htf || {};

  return (
    <div className="cf">
      <div className="cf-bar">
        <div className="cf-brand"><span>👹</span>MONSTER <b>CONFLUENCE</b></div>
        <div className="cf-pick">
          <label>Asset</label>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {ASSETS.map((a) => <option key={a} value={a}>{a.toUpperCase()}</option>)}
          </select>
        </div>
        <div className="cf-modes">
          {MODES.map((m) => (
            <button key={m.key} className={`cf-mode ${mode === m.key ? 'on' : ''}`}
              onClick={() => setMode(m.key)}>{m.label}</button>
          ))}
        </div>
        <button className="cf-refresh" onClick={load} disabled={loading}>{loading ? '…' : '↻'}</button>
      </div>

      {err && <div className="cf-err">⚠ Confluence unavailable — {err}</div>}

      {data && (
        <>
          <section className="cf-hero" style={{ '--side': sideColor }}>
            <div className="cf-hero-l">
              <div className="cf-side" style={{ color: sideColor }}>{clean(side)}</div>
              <div className="cf-tier">{data.tier}</div>
              <div className="cf-reason">{clean(data.reason)}</div>
            </div>
            <div className="cf-hero-r">
              <div className="cf-score" style={{ color: sideColor }}>{best.toFixed(0)}<span>/100</span></div>
              <div className="cf-grade" style={{ color: gradeColor(data.grade), borderColor: gradeColor(data.grade) }}>{data.grade}</div>
            </div>
          </section>

          <div className="cf-vs">
            <div className="cf-vs-side"><span className="l">BUY</span>
              <div className="cf-vs-bar"><div className="fill buy" style={{ width: `${sc.buy || 0}%` }} /></div>
              <span className="v">{(sc.buy || 0).toFixed(0)}</span></div>
            <div className="cf-vs-side"><span className="l">SELL</span>
              <div className="cf-vs-bar"><div className="fill sell" style={{ width: `${sc.sell || 0}%` }} /></div>
              <span className="v">{(sc.sell || 0).toFixed(0)}</span></div>
            <div className="cf-margin">margin {(sc.margin || 0).toFixed(0)}</div>
          </div>

          <section className="cf-factors-card">
            <div className="cf-ph"><span className="pt">{data.winner} — 5-FACTOR BREAKDOWN</span>
              <span className="psub">{data.mode_label}</span></div>
            {(data.factors || []).map((f, i) => {
              const pct = f.max ? (f.pts / f.max) * 100 : 0;
              const full = f.pts >= f.max && f.max > 0;
              return (
                <div key={i} className="cf-factor">
                  <div className="cf-factor-top">
                    <span className="cf-fname">{full ? '✅ ' : ''}{f.name}</span>
                    <span className="cf-fpts">{f.pts}<span className="dim">/{f.max}</span></span>
                  </div>
                  <div className="cf-fbar"><div className="cf-ffill" style={{ width: `${pct}%`,
                    background: full ? '#3fb950' : pct > 0 ? '#e3b341' : '#30363d' }} /></div>
                  <div className="cf-fdet">{clean(f.det)}</div>
                </div>
              );
            })}
          </section>

          <div className="cf-ctx">
            <div className="cf-ctx-card">
              <div className="cf-ctx-k">HIGHER TIMEFRAME</div>
              <div className="cf-ctx-v">W1 <b className={htf.W1 === 'BULL' ? 'up' : 'down'}>{htf.W1 || '—'}</b>
                {'  '}D1 <b className={htf.D1 === 'BULL' ? 'up' : 'down'}>{htf.D1 || '—'}</b></div>
              <div className="cf-ctx-sub">{htf.permission ? `Permission: ${clean(htf.permission.name)}` : ''}</div>
            </div>
            <div className="cf-ctx-card">
              <div className="cf-ctx-k">SESSION</div>
              <div className="cf-ctx-v">{data.session?.phase || '—'} · {clean(data.session?.state)}</div>
              <div className="cf-ctx-sub">{clean(data.session?.text)}</div>
            </div>
            <div className="cf-ctx-card">
              <div className="cf-ctx-k">BETTER-VOLUME TRIGGER</div>
              <div className="cf-ctx-v">{clean(data.bv_trigger?.side) || '—'}</div>
              <div className="cf-ctx-sub">{clean(data.bv_trigger?.text)}</div>
            </div>
            <div className="cf-ctx-card">
              <div className="cf-ctx-k">AGENT PRESSURE (60)</div>
              <div className="cf-ctx-v" style={{ color: (data.agent_pressure?.pressure || 0) >= 0 ? '#3fb950' : '#ff7b72' }}>
                {(data.agent_pressure?.pressure ?? 0).toFixed(3)}</div>
              <div className="cf-ctx-sub">{(data.agent_pressure?.chop_flag) ? 'Chop detected — stand aside' : 'Directional'}</div>
            </div>
          </div>

          <div className="cf-foot">
            100-point confluence: HTF trend 25 · Better-Volume retest 25 · Session 19 · Agent pressure 19 · Quick trigger 12.
            Actionable needs a strong score, ≥3/5 factors and margin over the other side.
          </div>
        </>
      )}
    </div>
  );
}
