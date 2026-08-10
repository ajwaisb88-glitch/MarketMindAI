import React, { useState, useCallback } from 'react';

// Colours for the SPOOF / SHEEP / WHALE sentiment triangle.
const SENTIMENT_COLORS = { SPOOF: '#f85149', SHEEP: '#e3b341', WHALE: '#58a6ff' };

// Signal grade → colour. A-tier green, B/C amber, D/F/NO-TRADE muted red/grey.
const GRADE_COLORS = {
  'A+': '#3fb950', A1: '#4cc266', A: '#6bd07f', B: '#e3b341',
  C: '#e08c3a', D: '#f85149', F: '#8b949e', 'NO-TRADE': '#6e7681',
};

function GradeBadge({ grade, score }) {
  const color = GRADE_COLORS[grade] ?? '#8b949e';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{
        minWidth: 58, textAlign: 'center', background: color, color: '#0d1117',
        fontWeight: 800, fontSize: grade === 'NO-TRADE' ? 12 : 22, padding: '6px 10px',
        borderRadius: 10, letterSpacing: 0.5,
      }}>{grade}</div>
      <div>
        <div style={{ fontWeight: 700 }}>Signal grade</div>
        <div className="sub">{grade === 'NO-TRADE' ? 'no actionable signal' : `score ${score}/100`}</div>
      </div>
    </div>
  );
}

function TradePlan({ plan }) {
  if (!plan) return null;
  const isLong = plan.direction === 'long';
  const dirColor = isLong ? '#3fb950' : '#f85149';
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 700 }}>Trade plan</span>
        <span style={{ color: dirColor, fontWeight: 700, fontSize: 13 }}>
          {isLong ? '▲ LONG' : '▼ SHORT'} · {plan.implied_leverage}× · RR {plan.risk_reward}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, textAlign: 'center' }}>
        <LevelBox label="Entry" value={plan.entry} color="var(--text)" />
        <LevelBox label="Stop loss" value={plan.stop_loss} color="#f85149" sub={`${plan.stop_pct}%`} />
        <LevelBox label="Take profit" value={plan.take_profit} color="#3fb950" sub={`+${plan.take_profit_pct}%`} />
      </div>
      <div className="sub" style={{ fontSize: 12 }}>
        ⤴ Trailing TP: arms at {plan.trailing_tp.arms_at} (+{plan.trailing_tp.arms_at_r}R), then trails {plan.trailing_tp.trail_distance_pct}% behind the peak
      </div>
    </div>
  );
}

function LevelBox({ label, value, color, sub }) {
  return (
    <div style={{ background: '#0d1117', borderRadius: 6, padding: '8px 6px' }}>
      <div className="sub" style={{ fontSize: 11 }}>{label}</div>
      <div style={{ color, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div className="sub" style={{ fontSize: 11 }}>{sub}</div>}
    </div>
  );
}

function Gauge({ value, label }) {
  const pct = Math.max(0, Math.min(100, value ?? 0));
  const color = pct >= 70 ? '#f85149' : pct >= 40 ? '#e3b341' : '#3fb950';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div style={{ fontSize: 46, fontWeight: 800, color, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
        {pct}<span style={{ fontSize: 22, color: 'var(--sub)' }}>/100</span>
      </div>
      <div>
        <div style={{ color, fontWeight: 700, letterSpacing: 1 }}>● {label}</div>
        <div className="sub">spoofing probability</div>
      </div>
    </div>
  );
}

function SentimentTriangle({ sentiment }) {
  if (!sentiment) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {Object.entries(sentiment).map(([k, v]) => (
        <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 60, color: SENTIMENT_COLORS[k], fontWeight: 700, fontSize: 12 }}>{k}</span>
          <div style={{ flex: 1, background: '#21262d', borderRadius: 6, height: 10, overflow: 'hidden' }}>
            <div style={{ width: `${Math.round(v * 100)}%`, height: '100%', background: SENTIMENT_COLORS[k], transition: 'width .4s' }} />
          </div>
          <span className="sub" style={{ width: 40, textAlign: 'right' }}>{Math.round(v * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

// Mini bid/ask depth bars, echoing the order-book visual in the brief.
function DepthBars({ book }) {
  if (!book) return null;
  const max = Math.max(...book.bid_sizes, ...book.ask_sizes, 1);
  const Col = ({ sizes, color }) => (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 48 }}>
      {sizes.slice(0, 8).map((s, i) => (
        <div key={i} title={s.toFixed(2)} style={{ width: 10, height: `${(s / max) * 100}%`, background: color, borderRadius: 2, opacity: 0.85 }} />
      ))}
    </div>
  );
  return (
    <div style={{ display: 'flex', gap: 18, alignItems: 'flex-end' }}>
      <div><Col sizes={[...book.bid_sizes].reverse()} color="#3fb950" /><div className="sub">bids</div></div>
      <div><Col sizes={book.ask_sizes} color="#f85149" /><div className="sub">asks</div></div>
    </div>
  );
}

export default function ManipulationRadar({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [freq, setFreq] = useState(null);
  const [minGrade, setMinGrade] = useState('');   // '' = show any setup

  const scan = useCallback(async () => {
    setLoading(true);
    setError(null);
    setFreq(null);
    try {
      const q = minGrade ? `?min_grade=${encodeURIComponent(minGrade)}` : '';
      const res = await fetch(`${apiBase}/manipulation${q}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      setData(d);
      // how often would a setup like this appear for that asset?
      fetch(`${apiBase}/signals/frequency?asset=${d.asset}&min_grade=A`)
        .then(r => r.ok ? r.json() : null).then(setFreq).catch(() => {});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase, minGrade]);

  return (
    <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="history-header" style={{ marginBottom: 0 }}>
        <h3>🛰 Manipulation Radar</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={minGrade} onChange={e => setMinGrade(e.target.value)}
            title="Only surface setups at this grade or better"
            style={{ fontSize: 12 }}>
            <option value="">Any grade</option>
            <option value="B">≥ B</option>
            <option value="A">≥ A</option>
            <option value="A1">A+ / A1 only</option>
            <option value="A+">A+ only</option>
          </select>
          <button className="btn-sm" disabled={loading} onClick={scan}>
            {loading ? 'Scanning…' : 'Scan order book'}
          </button>
        </div>
      </div>

      {error && <div className="sub" style={{ color: 'var(--bear)' }}>⚠ {error}</div>}

      {!data && !error && (
        <div className="sub">Scan a simulated L2 order-book window for spoofing / layering.</div>
      )}

      {data && (
        <>
          {data.filtered && (
            <div className="sub" style={{ fontSize: 12, color: data.filtered.found ? 'var(--bull, #3fb950)' : 'var(--sub)' }}>
              {data.filtered.found
                ? `✓ Found a ≥${data.filtered.min_grade} setup in ${data.filtered.scans} scan${data.filtered.scans > 1 ? 's' : ''}`
                : `No ≥${data.filtered.min_grade} setup in ${data.filtered.scans} scans — showing the best found (${data.grade})`}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <GradeBadge grade={data.grade} score={data.score} />
            {data.grade !== 'NO-TRADE' && data.direction !== 'flat' && (
              <div style={{
                fontWeight: 700, fontSize: 13, padding: '4px 12px', borderRadius: 8,
                border: `1px solid ${data.direction === 'long' ? '#3fb950' : '#f85149'}`,
                color: data.direction === 'long' ? '#3fb950' : '#f85149',
              }}>
                {data.direction === 'long' ? '▲ LONG' : '▼ SHORT'} bias
              </div>
            )}
          </div>
          <Gauge value={data.probability} label={data.label} />
          {data.grade !== 'NO-TRADE' && (
            <div style={{ display: 'flex', gap: 20, fontSize: 13 }}>
              <Row label="Conviction" value={`${data.conviction}/100`} />
              <Row label="Tradability" value={`${data.tradability}/100`} />
            </div>
          )}
          {data.trade_plan && <TradePlan plan={data.trade_plan} />}
          {freq && (
            <div className="sub" style={{ fontSize: 12 }}>
              📆 Est. for {freq.asset.toUpperCase()}: ~<b style={{ color: 'var(--text)' }}>{freq.real_signals_per_day}</b> real ≥A signals/day
              {' '}(+{freq.false_alarms_per_day} false alarms · precision {Math.round(freq.precision * 100)}%),
              {' '}scanning every {freq.scan_interval_sec}s at {Math.round(freq.spoof_base_rate * 100)}% base rate
            </div>
          )}
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div className="sub" style={{ marginBottom: 6 }}>Sentiment triangle</div>
              <SentimentTriangle sentiment={data.sentiment} />
            </div>
            <div>
              <div className="sub" style={{ marginBottom: 6 }}>Order-book depth</div>
              <DepthBars book={data.order_book} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px 24px', fontSize: 13 }}>
            <Row label="Imbalance" value={data.features?.imbalance} />
            <Row label="Cancel/Trade" value={data.features?.cancel_trade_ratio} />
            <Row label="Phantom liq." value={data.features?.phantom_liquidity} />
            <Row label="Cancel burst" value={data.features?.cancel_burst} />
            <Row label="Funding (8h)" value={data.funding_rate != null ? `${(data.funding_rate * 100).toFixed(4)}%` : '-'} />
            <Row label="Mid" value={data.mid} />
          </div>
          <div className="sub">scenario: {data.scenario} · grade = conviction × tradability · not financial advice</div>
        </>
      )}
    </section>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span className="sub">{label}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{value ?? '-'}</span>
    </div>
  );
}
