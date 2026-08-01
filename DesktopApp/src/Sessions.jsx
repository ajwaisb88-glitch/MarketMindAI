import React, { useState, useEffect, useCallback, useRef } from 'react';
import './Sessions.css';

const dubaiNow = () => {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Dubai', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date());
  } catch { return '--:--:--'; }
};

function countdown(whenUtc) {
  if (!whenUtc) return '—';
  const ms = new Date(whenUtc).getTime() - Date.now();
  if (ms <= 0) return 'now';
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s % 60}s`;
  return `${m}m ${s % 60}s`;
}

export default function Sessions({ apiBase }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [clock, setClock] = useState(dubaiNow());
  const [, tick] = useState(0);
  const t = useRef(0);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await fetch(`${apiBase}/sessions`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
  }, [apiBase]);

  useEffect(() => { load(); const iv = setInterval(load, 60000); return () => clearInterval(iv); }, [load]);
  useEffect(() => {
    t.current = setInterval(() => { setClock(dubaiNow()); tick((n) => n + 1); }, 1000);
    return () => clearInterval(t.current);
  }, []);

  const nf = data?.next_fix, ng = data?.next_gold_fix;
  const events = data?.events || [];
  const nextIdx = events.findIndex((e) => !e.past);

  return (
    <div className="ss">
      <div className="ss-bar">
        <div className="ss-brand"><span>🕐</span>SESSION <b>TIMING</b> · Dubai</div>
        <div className="ss-clock">{clock}<span className="ss-tz">GST · UTC+4</span></div>
        {data && (
          <>
            <span className={`ss-badge ${data.market_open ? 'open' : 'closed'}`}>
              {data.market_open ? '● Market open' : '○ Weekend / closed'}</span>
            <span className="ss-badge season">{data.is_summer ? '☀ Summer' : '❄ Winter'}</span>
          </>
        )}
      </div>

      {err && <div className="ss-err">⚠ Sessions unavailable — {err}</div>}

      {data && (
        <>
          <div className="ss-now">
            Active now: <b>{data.current_sessions.length ? data.current_sessions.join(' · ') : data.primary_session}</b>
          </div>

          <div className="ss-cd-row">
            <section className="ss-cd">
              <div className="ss-cd-k">⏱ NEXT SCHEDULED FIX</div>
              <div className="ss-cd-name">{nf ? nf.event : '—'}</div>
              <div className="ss-cd-when">{nf ? `${nf.dubai_time} Dubai${nf.note ? ' · ' + nf.note : ''}` : ''}</div>
              <div className="ss-cd-timer">{countdown(nf?.when_utc)}</div>
            </section>
            <section className="ss-cd gold">
              <div className="ss-cd-k">🟡 NEXT GOLD FIX</div>
              <div className="ss-cd-name">{ng ? ng.event : '—'}</div>
              <div className="ss-cd-when">{ng ? `${ng.dubai_time} Dubai${ng.note ? ' · ' + ng.note : ''}` : ''}</div>
              <div className="ss-cd-timer gold">{countdown(ng?.when_utc)}</div>
            </section>
          </div>

          {data.gold_slabs.length > 0 && (
            <div className="ss-slabs">
              <span className="ss-slabs-k">🟡 GOLD SLABS TODAY</span>
              {data.gold_slabs.map((s, i) => (
                <span key={i} className={`ss-slab ${s.past ? 'past' : ''}`}>{s.start}–{s.end} <em>{s.event}</em></span>
              ))}
            </div>
          )}

          <section className="ss-table-card">
            <div className="ss-ph"><span className="pt">TODAY · {data.weekday.toUpperCase()} {data.dubai_date}</span>
              <span className="psub">{events.length} events · Dubai time</span></div>
            <div className="ss-table-wrap">
              <table className="ss-table">
                <thead><tr><th>Dubai</th><th>Type</th><th>Event</th><th>Session</th><th>In</th></tr></thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={i} className={`${e.past ? 'past' : ''} ${i === nextIdx ? 'next' : ''} ${e.gold ? 'gold' : ''}`}>
                      <td className="mono ss-t">{e.dubai_time}{e.gold ? ' 🟡' : ''}</td>
                      <td><span className={`ss-type ${e.type.toLowerCase()}`}>{e.type}</span></td>
                      <td className="ss-ev">{e.event}{e.note && <span className="ss-note">{e.note}</span>}</td>
                      <td className="ss-sess">{e.session}</td>
                      <td className="mono ss-in">{e.past ? '—' : countdown(e.when_utc)}</td>
                    </tr>
                  ))}
                  {events.length === 0 && <tr><td colSpan={5} className="ss-empty">No events on this Dubai date (weekend). Next FIX: {nf?.event} {nf?.dubai_time}.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <div className="ss-foot">
            <b>FIX</b> = scheduled/mechanical (auction, settlement, data) — reliable. <b>FLOW</b> = behavioural (desks, stop-runs) — softer.
            {' '}{data.note} {data.caveat}
          </div>
        </>
      )}
    </div>
  );
}
