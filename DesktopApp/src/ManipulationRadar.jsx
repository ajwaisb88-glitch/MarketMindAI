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

  const scan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/manipulation`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  return (
    <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="history-header" style={{ marginBottom: 0 }}>
        <h3>🛰 Manipulation Radar</h3>
        <button className="btn-sm" disabled={loading} onClick={scan}>
          {loading ? 'Scanning…' : 'Scan order book'}
        </button>
      </div>

      {error && <div className="sub" style={{ color: 'var(--bear)' }}>⚠ {error}</div>}

      {!data && !error && (
        <div className="sub">Scan a simulated L2 order-book window for spoofing / layering.</div>
      )}

      {data && (
        <>
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
