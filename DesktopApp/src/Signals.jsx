import React, { useState, useEffect, useCallback, useRef } from 'react';
import './Signals.css';

const ASSETS = ['gold', 'xauusd', 'btc', 'eth', 'sol', 'xrp', 'doge', 'silver', 'oil', 'eurusd', 'gbpusd'];
const MODES = ['off', 'manual', 'auto'];
const MODE_HELP = {
  off: 'Ignored — this system produces nothing.',
  manual: 'Shows the signal here; you decide. Nothing is sent to MT5.',
  auto: 'Sends the signal straight to MT4/MT5 (needs AutoTrading ON).',
};
// The three engines are kept SEPARATE on purpose — never blended into one score.
const META = {
  monster: { icon: '👹', tag: 'GOLD CONFLUENCE', color: '#e3b341' },
  whale: { icon: '🐋', tag: 'BETTER VOLUME', color: '#58a6ff' },
  marketmind: { icon: '🧠', tag: '15m → 4h CONFLUENCE', color: '#3fb950' },
};
const ORDER = ['monster', 'whale', 'marketmind'];

const gradeColor = (g) => {
  if (!g || g === '-') return '#6b7480';
  if (g.startsWith('A')) return '#3fb950';
  if (g.startsWith('B')) return '#e3b341';
  return '#f0883e';
};
const fmtP = (p) => (p == null ? '—' : p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 2 })
  : p >= 1 ? p.toFixed(2) : p.toFixed(5));

export default function Signals({ apiBase }) {
  const [asset, setAsset] = useState('gold');
  const [sources, setSources] = useState([]);
  const [feed, setFeed] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busyMode, setBusyMode] = useState(null);
  const timer = useRef(0);

  const loadSources = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/signals/sources`);
      const d = await r.json();
      setSources(d.sources || []);
    } catch (e) { /* leave prior */ }
  }, [apiBase]);

  const loadFeed = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/signals/feed?asset=${asset}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setFeed(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
    setLoading(false);
  }, [apiBase, asset]);

  useEffect(() => { loadSources(); }, [loadSources]);
  useEffect(() => { loadFeed(); }, [loadFeed]);

  // gentle auto-refresh so signals stay live
  useEffect(() => {
    clearInterval(timer.current);
    timer.current = setInterval(loadFeed, 20000);
    return () => clearInterval(timer.current);
  }, [loadFeed]);

  const setMode = async (source, mode) => {
    setBusyMode(`${source}:${mode}`);
    try {
      await fetch(`${apiBase}/signals/sources/mode?source=${source}&mode=${mode}`, { method: 'POST' });
      await loadSources();
    } catch (e) { /* ignore */ }
    setBusyMode(null);
  };

  const modeOf = (key) => sources.find((s) => s.key === key)?.mode || 'manual';
  const sig = (key) => (feed?.signals || {})[key] || {};

  return (
    <div className="sg">
      <div className="sg-bar">
        <div className="sg-brand"><span className="sg-logo">🚨</span>TRADING <b>SIGNALS</b></div>
        <div className="sg-asset">
          <label>Asset</label>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {ASSETS.map((a) => <option key={a} value={a}>{a.toUpperCase()}</option>)}
          </select>
        </div>
        <button className="sg-refresh" onClick={loadFeed} disabled={loading}>
          {loading ? '…' : '↻ Refresh'}
        </button>
      </div>

      <div className="sg-note">
        <span className="sg-elite">★ A+ ONLY</span>
        Three independent systems — <b>never blended</b>. Only <b>elite A+</b> setups are
        actionable; anything weaker shows as “no A+ setup”. Pick a mode per system:
        <span className="sg-chip off">Off</span><span className="sg-chip man">Manual</span>
        <span className="sg-chip auto">Auto → MT5</span>
      </div>

      {err && <div className="sg-err">⚠ Signals unavailable — {err}</div>}

      <div className="sg-grid">
        {ORDER.map((key) => {
          const src = sources.find((s) => s.key === key) || {};
          const m = META[key];
          const s = sig(key);
          const mode = modeOf(key);
          const isBuy = s.direction === 'BUY';
          const isSell = s.direction === 'SELL';
          const active = isBuy || isSell;
          const rr = s.risk_reward;
          return (
            <section key={key} className={`sg-card ${active ? (isBuy ? 'buy' : 'sell') : 'idle'}`}
              style={{ '--accent': m.color }}>
              <div className="sg-head">
                <div className="sg-name"><span className="sg-ico">{m.icon}</span>
                  <div><div className="sg-title">{src.name || key}</div>
                    <div className="sg-tag">{m.tag}</div></div>
                </div>
                {s.grade && s.grade !== '-' && (
                  <span className="sg-grade" style={{ color: gradeColor(s.grade), borderColor: gradeColor(s.grade) }}>
                    {s.grade}
                  </span>
                )}
              </div>

              <div className="sg-modes">
                {MODES.map((mo) => (
                  <button key={mo}
                    className={`sg-mode ${mode === mo ? 'on ' + mo : ''}`}
                    title={MODE_HELP[mo]}
                    disabled={busyMode === `${key}:${mo}`}
                    onClick={() => setMode(key, mo)}>
                    {mo === 'off' ? 'Off' : mo === 'manual' ? 'Manual' : 'Auto → MT5'}
                  </button>
                ))}
              </div>

              {mode === 'off' ? (
                <div className="sg-idle">This system is <b>Off</b>. Turn it Manual or Auto to see signals.</div>
              ) : active ? (
                <>
                  <div className={`sg-dir ${isBuy ? 'buy' : 'sell'}`}>
                    {isBuy ? '🟢 BUY' : '🔴 SELL'} {asset.toUpperCase()}
                  </div>
                  <div className="sg-levels">
                    <div className="lv"><span className="lk">Entry</span><span className="lvv">{fmtP(s.entry)}</span></div>
                    <div className="lv"><span className="lk">Stop</span><span className="lvv sl">{fmtP(s.stop_loss)}</span></div>
                    <div className="lv"><span className="lk">Target</span><span className="lvv tp">{fmtP(s.take_profit)}</span></div>
                    <div className="lv"><span className="lk">R:R</span><span className="lvv">{rr ? `${rr}:1` : '—'}</span></div>
                  </div>
                  {s.tier && <div className="sg-tier">Tier: {s.tier}</div>}
                  {s.story && <div className="sg-story">📖 {s.story}</div>}
                  {mode === 'auto' && <div className="sg-auto-note">⚡ Auto — routed to MT5 when a setup fires (AutoTrading must be ON).</div>}
                </>
              ) : (
                <div className="sg-idle">
                  <div className="sg-flat">No setup right now</div>
                  <div className="sg-engine">Engine: {src.engine || m.tag}</div>
                  {s.story && <div className="sg-story soft">{s.story}</div>}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <div className="sg-foot">
        Signals are analysis, not financial advice. Nothing trades unless a system is set to <b>Auto</b> and MT5 AutoTrading is ON.
      </div>
    </div>
  );
}
