import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';
import ManipulationRadar from './ManipulationRadar';
import Watchlist from './Watchlist';
import MoneyFlow from './MoneyFlow';
import Signals from './Signals';
import Performance from './Performance';
import NewsRadar from './NewsRadar';
import Confluence from './Confluence';
import Sessions from './Sessions';
import MarketRead from './MarketRead';
import License from './License';

const TABS = [
  { key: 'signals', label: '🚨 Signals' },
  { key: 'read', label: '📐 Read' },
  { key: 'confluence', label: '👹 Confluence' },
  { key: 'sessions', label: '🕐 Sessions' },
  { key: 'performance', label: '📊 Performance' },
  { key: 'news', label: '📰 News' },
  { key: 'predict', label: '📈 Predict' },
  { key: 'moneyflow', label: '💧 Money Flow' },
  { key: 'watchlist', label: '📋 Watchlist' },
  { key: 'radar', label: '📡 Radar' },
];
const TAB_KEY = 'mm_tab_v1';

const LOCAL_API = 'http://127.0.0.1:8000';
const API_SETTINGS_KEY = 'mm_api_settings_v1';
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

function loadApiSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(API_SETTINGS_KEY) || '{}');
    return { useLocal: saved.useLocal !== false, remoteUrl: saved.remoteUrl || '' };
  } catch { return { useLocal: true, remoteUrl: '' }; }
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
  const [license, setLicense] = useState(null);   // null = checking
  const [apiSettings, setApiSettings] = useState(loadApiSettings);
  const [showSettings, setShowSettings] = useState(false);
  const [backendInfo, setBackendInfo] = useState(null);
  const [tab, setTab] = useState(() => localStorage.getItem(TAB_KEY) || 'signals');
  const pollRef = useRef(null);

  useEffect(() => { try { localStorage.setItem(TAB_KEY, tab); } catch {} }, [tab]);
  const apiBase = apiSettings.useLocal || !apiSettings.remoteUrl.trim()
    ? LOCAL_API
    : apiSettings.remoteUrl.trim().replace(/\/$/, '');

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
      const res = await fetch(`${apiBase}/predict?asset=${a}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      addToHistory({ ...data, ts: new Date().toISOString() });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [addToHistory, apiBase]);

  const refreshBackendHealth = useCallback(() => {
    setBackendStatus('checking');
    fetch(`${apiBase}/health`)
      .then(r => r.ok ? setBackendStatus('online') : setBackendStatus('error'))
      .catch(() => setBackendStatus('offline'));
  }, [apiBase]);

  // The packaged backend can take a few seconds to start, so keep checking it.
  useEffect(() => {
    refreshBackendHealth();
    const timer = setInterval(refreshBackendHealth, 5000);
    return () => clearInterval(timer);
  }, [refreshBackendHealth]);

  // License check — retry until the backend answers, then gate the app if a key
  // is required and not yet active.
  useEffect(() => {
    let alive = true;
    const check = async () => {
      if (!alive) return;
      try {
        const r = await fetch(`${apiBase}/license`);
        if (r.ok && alive) { setLicense(await r.json()); return; }
      } catch { /* backend not up yet */ }
      if (alive) setTimeout(check, 2500);
    };
    check();
    return () => { alive = false; };
  }, [apiBase]);

  useEffect(() => {
    window.marketmind?.getBackendInfo?.().then(setBackendInfo).catch(() => {});
  }, []);

  const saveApiSettings = (next) => {
    setApiSettings(next);
    localStorage.setItem(API_SETTINGS_KEY, JSON.stringify(next));
  };

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

  const statusColor = { online: '#3fb950', offline: '#f85149', error: '#e3b341', checking: '#e3b341', unknown: '#8b949e' }[backendStatus];

  // License gate — block the whole app until a required key is activated.
  if (license && license.required && !license.valid) {
    return <License apiBase={apiBase} status={license}
      onActivated={(d) => setLicense({ ...license, ...d })} />;
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-title">
          <span className="logo">📈</span>
          <span>MarketMind AI</span>
          <span className="header-author">by Malik Muhammad Naveed</span>
        </div>
        <div className="backend-badge" style={{ borderColor: statusColor, color: statusColor }}>
          ● Backend {backendStatus}
        </div>
        <button className="btn-sm" onClick={() => setShowSettings((visible) => !visible)}>Settings</button>
      </header>

      <nav className="tabnav">
        {TABS.map((t) => (
          <button key={t.key} className={`tabnav-btn ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </nav>

      <main className="main">
        {showSettings && (
          <section className="card settings">
            <h3>API connection</h3>
            <label className="settings-option">
              <input type="radio" checked={apiSettings.useLocal}
                onChange={() => saveApiSettings({ ...apiSettings, useLocal: true })} />
              Use bundled local API ({LOCAL_API})
            </label>
            <label className="settings-option">
              <input type="radio" checked={!apiSettings.useLocal}
                onChange={() => saveApiSettings({ ...apiSettings, useLocal: false })} />
              Use remote API
            </label>
            {!apiSettings.useLocal && (
              <input aria-label="Remote API URL" placeholder="https://api.example.com"
                value={apiSettings.remoteUrl}
                onChange={(event) => saveApiSettings({ ...apiSettings, remoteUrl: event.target.value })} />
            )}
            <div className="sub">Active endpoint: {apiBase}</div>
            {backendInfo?.bundled && <div className="sub">Bundled API: {backendInfo.running ? 'started' : 'starting'}</div>}
          </section>
        )}
        {/* ── Signals / Money Flow / Watchlist / Radar pages ── */}
        {tab === 'signals' && <Signals apiBase={apiBase} />}
        {tab === 'read' && <MarketRead apiBase={apiBase} />}
        {tab === 'confluence' && <Confluence apiBase={apiBase} />}
        {tab === 'sessions' && <Sessions apiBase={apiBase} />}
        {tab === 'performance' && <Performance apiBase={apiBase} />}
        {tab === 'news' && <NewsRadar apiBase={apiBase} />}
        {tab === 'moneyflow' && <MoneyFlow apiBase={apiBase} />}
        {tab === 'watchlist' && <Watchlist apiBase={apiBase} />}
        {tab === 'radar' && <ManipulationRadar apiBase={apiBase} />}

        {/* ── Predict page ── */}
        {tab === 'predict' && (
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
        )}

        {/* ── Result ── */}
        {tab === 'predict' && error && <div className="card error">⚠ {error}</div>}
        {tab === 'predict' && result && (
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
        {tab === 'predict' && history.length > 0 && (
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
