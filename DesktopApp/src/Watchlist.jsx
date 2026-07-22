import React, { useState, useCallback, useEffect } from 'react';

const GRADE_COLORS = {
  'A+': '#3fb950', A1: '#4cc266', A: '#6bd07f', B: '#e3b341',
  C: '#e08c3a', D: '#f85149', F: '#8b949e', 'NO-TRADE': '#6e7681',
};
const GRADE_RANK = { 'A+': 6, A1: 5, A: 4, B: 3, C: 2, D: 1, F: 0, 'NO-TRADE': -1 };

// The filter chips: label -> minimum rank to show.
const FILTERS = [
  { key: 'all', label: 'All', min: -99 },
  { key: 'B', label: '≥ B', min: 3 },
  { key: 'A', label: '≥ A', min: 4 },
  { key: 'top', label: 'A+ / A1', min: 5 },
];

function GradePill({ grade }) {
  const c = GRADE_COLORS[grade] ?? '#8b949e';
  return (
    <span style={{
      background: c, color: '#0d1117', fontWeight: 800,
      fontSize: grade === 'NO-TRADE' ? 10 : 13, padding: '2px 8px',
      borderRadius: 6, display: 'inline-block', minWidth: 34, textAlign: 'center',
    }}>{grade}</span>
  );
}

function Dir({ d }) {
  if (d === 'long') return <span style={{ color: '#3fb950', fontWeight: 700 }}>▲ LONG</span>;
  if (d === 'short') return <span style={{ color: '#f85149', fontWeight: 700 }}>▼ SHORT</span>;
  return <span className="sub">—</span>;
}

export default function Watchlist({ apiBase }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('A');
  const [sortKey, setSortKey] = useState('score');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/manipulation/scan?seed=${Math.floor(Math.random() * 100000)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      setRows(d.scan || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);

  const minRank = FILTERS.find(f => f.key === filter)?.min ?? -99;
  const shown = rows
    .filter(r => (GRADE_RANK[r.grade] ?? -1) >= minRank)
    .sort((a, b) => {
      if (sortKey === 'score') return b.score - a.score;
      if (sortKey === 'conviction') return b.conviction - a.conviction;
      if (sortKey === 'tradability') return b.tradability - a.tradability;
      return 0;
    });

  const actionable = rows.filter(r => (GRADE_RANK[r.grade] ?? -1) >= 4).length;

  return (
    <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="history-header" style={{ marginBottom: 0 }}>
        <h3>📋 Signal Watchlist — all assets</h3>
        <button className="btn-sm" disabled={loading} onClick={load}>
          {loading ? 'Scanning…' : 'Rescan all'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {FILTERS.map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className="btn-sm"
            style={{
              borderColor: filter === f.key ? 'var(--accent, #58a6ff)' : undefined,
              color: filter === f.key ? 'var(--accent, #58a6ff)' : undefined,
              marginLeft: 0,
            }}>{f.label}</button>
        ))}
        <span className="sub" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {actionable} of {rows.length} assets ≥ A
        </span>
      </div>

      {error && <div className="sub" style={{ color: '#f85149' }}>⚠ {error}</div>}

      <div className="history-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Grade</th>
              <th>Asset</th>
              <th>Bias</th>
              <th style={{ cursor: 'pointer' }} onClick={() => setSortKey('score')}>Score{sortKey === 'score' ? ' ↓' : ''}</th>
              <th style={{ cursor: 'pointer' }} onClick={() => setSortKey('conviction')}>Conv{sortKey === 'conviction' ? ' ↓' : ''}</th>
              <th style={{ cursor: 'pointer' }} onClick={() => setSortKey('tradability')}>Trad{sortKey === 'tradability' ? ' ↓' : ''}</th>
              <th>Entry</th>
              <th>SL</th>
              <th>TP</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(r => {
              const p = r.trade_plan;
              return (
                <tr key={r.asset}>
                  <td><GradePill grade={r.grade} /></td>
                  <td style={{ fontWeight: 700 }}>{r.asset.toUpperCase()}</td>
                  <td><Dir d={r.direction} /></td>
                  <td>{r.score}</td>
                  <td>{r.conviction}</td>
                  <td>{r.tradability}</td>
                  <td>{p ? p.entry : '—'}</td>
                  <td style={{ color: p ? '#f85149' : undefined }}>{p ? p.stop_loss : '—'}</td>
                  <td style={{ color: p ? '#3fb950' : undefined }}>{p ? p.take_profit : '—'}</td>
                </tr>
              );
            })}
            {shown.length === 0 && !loading && (
              <tr><td colSpan={9} className="sub" style={{ textAlign: 'center', padding: 16 }}>
                No setups at this grade in the current scan — try a lower filter or rescan.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="sub" style={{ fontSize: 12 }}>
        Simulated snapshot · grade = conviction × tradability · not financial advice
      </div>
    </section>
  );
}
