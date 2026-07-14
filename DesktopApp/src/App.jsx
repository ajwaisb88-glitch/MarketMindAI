import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

const API = 'http://127.0.0.1:8000';
const HISTORY_KEY = 'mm_history_v2';
const MAX_HISTORY = 100;

const ASSETS = ['gold', 'silver', 'oil', 'btc', 'eth', 'eurusd', 'gbpusd', 'sp500', 'nasdaq'];

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
  catch { return []; }
}

function saveHistory(h) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(h)); } catch {}
}

function Badge({ prediction }) {
  const map = { bullish: '#3fb950', bearish: '#f85149', neutral: '#8b949e' };
  const color = map[prediction] ?? '#8b949e';
  return (
    <span style={{ background: color, color: '#fff', padding: '2px 10px', borderRadius: 12, fontWeight: 700, fontSize: 13 }}>
      {prediction?.toUpperCase() ?? 'N/A'}
    </span>
  );
}

function ConfBar({ value }) {
  const pct = Math.round((value ?? 0.5) * 100);
  const color = pct >= 70 ? '#3fb950' : pct >= 50 ? '#e3b341' : '#f85149';
  return (
    <div style={{ background: '#21262d', borderRadius: 6, height: 10, width: '100%', overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, background: color, height: '100%', transition: 'width .4s' }} />
    </div>
  );
}

export default function App() {
  const [asset, setAsset] = useState('gold');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autoPoll, setAutoPoll] = useState(false);
  const [intervalSec, setIntervalSec] = useState(30);
  const [history, setHistory] = useState(loadHistory);
  const [backendStatus, setBackendStatus] = useState('unknown');
  const pollRef = useRef(null);

  const addToHistory = useCallback((entry) => {
    setHistory((prev) => {
      const next = [entry, ...prev].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }, []);

  const fetchPrediction = useCallback(async (a) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/predict?asset=${a}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      addToHistory({ ...data, ts: new Date().toISOString() });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [addToHistory]);

  // Check backend health
  useEffect(() => {
    fetch(`${API}/health`)
      .then(r => r.ok ? setBackendStatus('online') : setBackendStatus('error'))
      .catch(() => setBackendStatus('offline'));
  }, []);

  // Auto-poll
  useEffect(() => {
    if (autoPoll) {
      fetchPrediction(asset);
      pollRef.current = setInterval(() => fetchPrediction(asset), intervalSec * 1000);
    } else {
      clearInterval(pollRef.current);
    }
    return () => clearInterval(pollRef.current);
  }, [autoPoll, asset, intervalSec, fetchPrediction]);

  const exportCSV = () => {
    if (!history.length) return;
    const cols = ['ts', 'asset', 'prediction', 'confidence', 'last_price', 'rsi', 'pct_change_5d'];
    const rows = history.map(r => cols.map(c => r[c] ?? '').join(','));
    const csv = [cols.join(','), ...rows].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `marketmind-history-${Date.now()}.csv`;
    a.click();
  };

  const statusColor = { online: '#3fb950', offline: '#f85149', error: '#e3b341', unknown: '#8b949e' }[backendStatus];

  return (
    <div className="app">
      <header className="header">
        <div className="header-title">
          <span className="logo">📈</span>
          <span>MarketMind AI</span>
        </div>
        <div className="backend-badge" style={{ borderColor: statusColor, color: statusColor }}>
          ● Backend {backendStatus}
        </div>
      </header>

      <main className="main">
        {/* ── Controls ── */}
        <section className="card controls">
          <div className="row">
            <label>Asset</label>
            <select value={asset} onChange={e => setAsset(e.target.value)}>
              {ASSETS.map(a => <option key={a} value={a}>{a.toUpperCase()}</option>)}
            </select>
          </div>
          <div className="row">
            <label>Auto-poll every</label>
            <input type="number" min={5} max={300} value={intervalSec}
              onChange={e => setIntervalSec(Number(e.target.value))} style={{ width: 60 }} />
            <span>s</span>
            <button className={`toggle ${autoPoll ? 'active' : ''}`} onClick={() => setAutoPoll(p => !p)}>
              {autoPoll ? 'Stop' : 'Start'}
            </button>
          </div>
          <button className="btn-primary" disabled={loading} onClick={() => fetchPrediction(asset)}>
            {loading ? 'Loading…' : 'Predict now'}
          </button>
        </section>

        {/* ── Result ── */}
        {error && <div className="card error">⚠ {error}</div>}
        {result && (
          <section className="card result">
            <div className="result-row">
              <span className="result-label">Signal</span>
              <Badge prediction={result.prediction} />
            </div>
            <div className="result-row">
              <span className="result-label">Confidence</span>
              <div style={{ flex: 1 }}>
                <ConfBar value={result.confidence} />
                <span className="sub">{Math.round((result.confidence ?? 0.5) * 100)}%</span>
              </div>
            </div>
            {result.last_price != null && (
              <div className="result-row"><span className="result-label">Last price</span><span>{result.last_price}</span></div>
            )}
            {result.rsi != null && (
              <div className="result-row"><span className="result-label">RSI (14)</span><span>{result.rsi}</span></div>
            )}
            {result.pct_change_5d != null && (
              <div className="result-row"><span className="result-label">5d change</span>
                <span style={{ color: result.pct_change_5d >= 0 ? '#3fb950' : '#f85149' }}>
                  {result.pct_change_5d > 0 ? '+' : ''}{result.pct_change_5d}%
                </span>
              </div>
            )}
            {result.note && <div className="sub" style={{ marginTop: 8 }}>ℹ {result.note}</div>}
          </section>
        )}

        {/* ── History ── */}
        {history.length > 0 && (
          <section className="card history">
            <div className="history-header">
              <h3>History ({history.length})</h3>
              <div>
                <button className="btn-sm" onClick={exportCSV}>Export CSV</button>
                <button className="btn-sm danger" onClick={() => { setHistory([]); saveHistory([]); }}>Clear</button>
              </div>
            </div>
            <div className="history-table-wrap">
              <table>
                <thead>
                  <tr><th>Time</th><th>Asset</th><th>Signal</th><th>Conf</th><th>RSI</th><th>Price</th></tr>
                </thead>
                <tbody>
                  {history.slice(0, 30).map((h, i) => (
                    <tr key={i}>
                      <td className="sub">{h.ts ? new Date(h.ts).toLocaleTimeString() : '-'}</td>
                      <td>{h.asset?.toUpperCase()}</td>
                      <td><Badge prediction={h.prediction} /></td>
                      <td>{h.confidence != null ? Math.round(h.confidence * 100) + '%' : '-'}</td>
                      <td>{h.rsi ?? '-'}</td>
                      <td>{h.last_price ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
