import React, { useState, useEffect, useCallback, useRef } from 'react';
import './NewsRadar.css';

const BIAS = {
  BEARISH: { label: '🐻 Gold down', color: '#ff7b72' },
  BULLISH: { label: '🐂 Gold up', color: '#3fb950' },
  MIXED: { label: '↔ Depends', color: '#e3b341' },
};
const impactColor = (i) => (i >= 9 ? '#ff4d4d' : i >= 7 ? '#e3b341' : i >= 5 ? '#58a6ff' : '#8b949e');

function countdown(whenUtc) {
  const ms = new Date(whenUtc).getTime() - Date.now();
  if (ms <= 0) return 'now / passed';
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s % 60}s`;
  return `${m}m ${s % 60}s`;
}

export default function NewsRadar({ apiBase }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [, tick] = useState(0);
  const timer = useRef(0);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/news`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
    setLoading(false);
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);
  // 1s tick for the live countdown
  useEffect(() => {
    timer.current = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer.current);
  }, []);

  const nx = data?.next_high_impact;
  const leanColor = data?.week_lean === 'GOLD HEADWIND' ? '#ff7b72'
    : data?.week_lean === 'GOLD TAILWIND' ? '#3fb950' : '#e3b341';

  return (
    <div className="nr">
      <div className="nr-bar">
        <div className="nr-brand"><span>📰</span>NEWS <b>RADAR</b></div>
        <div className="nr-sub">High-impact US events &amp; their gold impact</div>
        {data && <span className="nr-lean" style={{ color: leanColor, borderColor: leanColor + '66' }}>{data.week_lean}</span>}
        <button className="nr-refresh" onClick={load} disabled={loading}>{loading ? '…' : '↻'}</button>
      </div>

      {err && <div className="nr-err">⚠ News unavailable — {err}</div>}

      {nx && (
        <section className="nr-next">
          <div className="nr-next-l">
            <div className="nr-next-k">⏱ NEXT HIGH-IMPACT EVENT</div>
            <div className="nr-next-name">{nx.event}</div>
            <div className="nr-next-when">{nx.day} · {nx.et_time}
              {' · '}{new Date(nx.when_utc).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })} your time</div>
          </div>
          <div className="nr-next-r">
            <div className="nr-count">{countdown(nx.when_utc)}</div>
            <div className="nr-next-impact" style={{ color: impactColor(nx.impact) }}>IMPACT {nx.impact}/10</div>
          </div>
        </section>
      )}

      {data && <div className="nr-note" style={{ borderColor: leanColor + '44' }}>{data.week_note}</div>}

      <section className="nr-table-card">
        <div className="nr-ph"><span className="pt">UPCOMING EVENTS</span>
          <span className="psub">{data ? `${data.events.length} in the next 3 weeks` : ''}</span></div>
        <div className="nr-table-wrap">
          <table className="nr-table">
            <thead>
              <tr><th>When</th><th>Time</th><th>Event</th><th>Impact</th><th>Gold bias</th><th>Typical</th><th>Hist. win</th><th>Why it moves gold</th></tr>
            </thead>
            <tbody>
              {(data?.events || []).map((e, i) => {
                const b = BIAS[e.bias] || BIAS.MIXED;
                return (
                  <tr key={i} className={e.impact >= 9 ? 'hot' : ''}>
                    <td className="nr-when">{e.day}{e.days_away === 0 ? ' · TODAY' : e.days_away === 1 ? ' · tmrw' : ''}</td>
                    <td className="mono">{e.et_time}</td>
                    <td className="nr-ev">{e.event}</td>
                    <td><span className="nr-imp" style={{ color: impactColor(e.impact), borderColor: impactColor(e.impact) + '66' }}>{e.impact}</span></td>
                    <td style={{ color: b.color, fontWeight: 700 }}>{b.label}</td>
                    <td className="mono">±{e.avg_move_pips}p</td>
                    <td className="mono">{e.win_rate}%</td>
                    <td className="nr-mech">{e.mechanism}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {data && <div className="nr-foot">{data.caveat} Spreads widen around releases — mind slippage; the first spike can whipsaw.</div>}
    </div>
  );
}
