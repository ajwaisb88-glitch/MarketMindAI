// Minimal React renderer using UMD builds from unpkg (offline installs recommended later)
const injectReact = () => {
  const scriptReact = document.createElement('script');
  scriptReact.src = 'https://unpkg.com/react@18/umd/react.development.js';
  const scriptReactDOM = document.createElement('script');
  scriptReactDOM.src = 'https://unpkg.com/react-dom@18/umd/react-dom.development.js';

  document.head.appendChild(scriptReact);
  document.head.appendChild(scriptReactDOM);

  scriptReactDOM.onload = () => {
    const e = React.createElement;
    const { useState, useEffect, useRef } = React;

    function App() {
      const [loading, setLoading] = useState(false);
      const [result, setResult] = useState(null);
      const [asset, setAsset] = useState('gold');
      const [autoPoll, setAutoPoll] = useState(false);
      const [intervalSec, setIntervalSec] = useState(10);
      const [status, setStatus] = useState('idle');
      const [lastUpdated, setLastUpdated] = useState(null);
      const [history, setHistory] = useState(() => {
        try {
          const raw = localStorage.getItem('mm_history_v1');
          return raw ? JSON.parse(raw) : [];
        } catch (e) { return []; }
      });
      const pollRef = useRef(null);

      const addHistory = (entry) => {
        setHistory((prev) => [entry, ...prev].slice(0, 50));
      };

      // persist history to localStorage
      useEffect(() => {
        try { localStorage.setItem('mm_history_v1', JSON.stringify(history)); } catch (e) {}
      }, [history]);

      const exportHistoryCSV = () => {
        if (!history || history.length === 0) return null;
        const rows = [['timestamp','asset','prediction','confidence','error','raw']];
        history.slice().reverse().forEach(h => {
          const pred = h.data && h.data.prediction ? h.data.prediction : '';
          const conf = h.data && typeof h.data.confidence !== 'undefined' ? String(h.data.confidence) : '';
          const err = h.data && h.data.error ? String(h.data.error) : '';
          rows.push([h.timestamp, h.asset, pred, conf, err, JSON.stringify(h.data).replace(/"/g,'""')]);
        });
        const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(',')).join('\n');
        // expose for tests
        try { window.__lastExportCSV = csv; } catch (e) {}
        // trigger download
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'marketmind_history.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        return csv;
      };

      const fetchPrediction = async (assetParam = asset) => {
        setLoading(true);
        setStatus('loading');
        try {
          const res = await fetch(`http://127.0.0.1:8000/predict?asset=${assetParam}`);
          const data = await res.json();
          const ts = new Date().toISOString();
          setResult(data);
          setLastUpdated(ts);
          setStatus('idle');
          addHistory({ timestamp: ts, asset: assetParam, data });
        } catch (err) {
          const ts = new Date().toISOString();
          const errObj = { error: err.message };
          setResult(errObj);
          setLastUpdated(ts);
          setStatus('error');
          addHistory({ timestamp: ts, asset: assetParam, data: errObj });
        } finally {
          setLoading(false);
        }
      };

      useEffect(() => {
        if (autoPoll) {
        // If React/ReactDOM fail to load (offline or blocked), provide a plain DOM fallback
        const renderFallback = () => {
          const root = document.getElementById('root');
          root.innerHTML = '';
          const container = document.createElement('div');
          container.style.fontFamily = 'sans-serif';
          container.style.padding = '20px';

          const h1 = document.createElement('h1');
          h1.innerText = 'MarketMind AI - Desktop (Fallback)';
          container.appendChild(h1);

          const controls = document.createElement('div');
          controls.style.display = 'flex';
          controls.style.gap = '8px';
          controls.style.alignItems = 'center';

          const selLabel = document.createElement('label');
          selLabel.innerText = 'Asset: ';
          const sel = document.createElement('select');
          ['gold','silver','oil','btc'].forEach(v => {
            const o = document.createElement('option'); o.value = v; o.innerText = v.charAt(0).toUpperCase()+v.slice(1); sel.appendChild(o);
          });
          sel.value = 'gold';
          selLabel.appendChild(sel);
          controls.appendChild(selLabel);

          const btn = document.createElement('button'); btn.innerText = 'Get Prediction'; controls.appendChild(btn);

          const chk = document.createElement('input'); chk.type = 'checkbox'; controls.appendChild(chk); const chkLabel = document.createElement('span'); chkLabel.innerText = 'Auto-poll'; controls.appendChild(chkLabel);

          const interval = document.createElement('input'); interval.type = 'number'; interval.value = 10; interval.min = 1; interval.style.width = '70px'; controls.appendChild(interval);

          const clearBtn = document.createElement('button'); clearBtn.innerText = 'Clear History'; clearBtn.style.marginLeft = 'auto'; controls.appendChild(clearBtn);

          container.appendChild(controls);

          const status = document.createElement('div'); status.style.marginTop = '8px'; status.innerText = 'Status: Idle'; container.appendChild(status);
          const last = document.createElement('div'); last.style.color = '#666'; last.innerText = 'Last: —'; container.appendChild(last);

          const pre = document.createElement('pre'); pre.style.marginTop = '8px'; pre.style.background = '#f6f8fa'; pre.style.padding = '10px'; pre.innerText = 'No result yet'; container.appendChild(pre);

          const histWrap = document.createElement('div'); histWrap.style.marginTop = '8px'; histWrap.style.border = '1px solid #eee'; histWrap.style.padding = '8px'; histWrap.style.height = '300px'; histWrap.style.overflow = 'auto';
          const histTitle = document.createElement('h4'); histTitle.innerText = 'History'; histWrap.appendChild(histTitle);
          const ul = document.createElement('ul'); ul.id = 'history'; ul.style.listStyle = 'none'; ul.style.padding = '0'; ul.style.margin = '0'; histWrap.appendChild(ul);
          container.appendChild(histWrap);

          root.appendChild(container);

          let pollId = null;

          const addHistory = (entry) => {
            const li = document.createElement('li');
            li.style.padding = '8px 6px'; li.style.borderBottom = '1px solid #f0f0f0';
            li.innerText = `${entry.asset} — ${new Date(entry.timestamp).toLocaleString()} — ${JSON.stringify(entry.data)}`;
            ul.insertBefore(li, ul.firstChild);
            while (ul.children.length > 50) ul.removeChild(ul.lastChild);
          };

          const doFetch = async () => {
            const a = sel.value;
            status.innerText = 'Status: Loading…';
            try {
              const r = await fetch(`http://127.0.0.1:8000/predict?asset=${a}`);
              const data = await r.json();
              const ts = new Date().toISOString();
              pre.innerText = JSON.stringify(data, null, 2);
              last.innerText = `Last: ${new Date(ts).toLocaleString()}`;
              status.innerText = 'Status: Idle';
              addHistory({ timestamp: ts, asset: a, data });
            } catch (err) {
              const ts = new Date().toISOString();
              pre.innerText = err.message;
              last.innerText = `Last: ${new Date(ts).toLocaleString()}`;
              status.innerText = 'Status: Error';
              addHistory({ timestamp: ts, asset: a, data: { error: err.message } });
            }
          };

          btn.addEventListener('click', doFetch);
          clearBtn.addEventListener('click', () => { ul.innerHTML = ''; });
          chk.addEventListener('change', () => {
            if (chk.checked) {
              doFetch();
              pollId = setInterval(doFetch, Math.max(1, Number(interval.value)) * 1000);
            } else {
              if (pollId) { clearInterval(pollId); pollId = null; }
            }
          });
        };

        scriptReact.onerror = scriptReactDOM.onerror = () => {
          // short delay then fallback
          setTimeout(() => {
            if (typeof window.React === 'undefined' || typeof window.ReactDOM === 'undefined') {
              renderFallback();
            }
          }, 300);
        };
          fetchPrediction(asset);
          pollRef.current = setInterval(() => fetchPrediction(asset), Math.max(1, Number(intervalSec)) * 1000);
        } else {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
        return () => {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        };
      }, [autoPoll, asset, intervalSec]);

      const clearHistory = () => setHistory([]);

      const statusColor = status === 'loading' ? '#f59e0b' : status === 'error' ? '#ef4444' : '#10b981';

      return e('div', { style: { padding: 20, fontFamily: 'sans-serif', maxWidth: 900 } }, [
        e('h1', { key: 'h' }, 'MarketMind AI - Desktop Prototype'),
        e('p', { key: 'p' }, 'Request predictions from the backend. Select asset and enable auto-polling if desired.'),

        e('div', { key: 'meta', style: { marginTop: 8, display: 'flex', gap: 12, alignItems: 'center' } }, [
          e('div', { key: 'status', style: { display: 'flex', alignItems: 'center', gap: 8 } }, [
            e('span', { key: 'dot', style: { width: 12, height: 12, borderRadius: 6, background: statusColor, display: 'inline-block' } }),
            e('span', { key: 'stext' }, status === 'loading' ? 'Loading…' : status === 'error' ? 'Error' : 'Idle'),
          ]),
          e('div', { key: 'last', style: { color: '#666' } }, lastUpdated ? `Last: ${new Date(lastUpdated).toLocaleString()}` : 'Last: —'),
        ]),

        e('div', { key: 'controls', style: { marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' } }, [
          e('label', { key: 'la', style: { display: 'flex', alignItems: 'center', gap: 8 } }, [
            'Asset:',
            e('select', { key: 'sel', value: asset, onChange: (ev) => setAsset(ev.target.value) }, [
              e('option', { key: 'gold', value: 'gold' }, 'Gold'),
              e('option', { key: 'silver', value: 'silver' }, 'Silver'),
              e('option', { key: 'oil', value: 'oil' }, 'Oil'),
              e('option', { key: 'btc', value: 'btc' }, 'BTC'),
            ]),
          ]),

          e('button', { key: 'btn', onClick: () => fetchPrediction(asset) }, loading ? 'Loading…' : 'Get Prediction'),

          e('label', { key: 'poll', style: { display: 'flex', alignItems: 'center', gap: 6 } }, [
            e('input', { key: 'chk', type: 'checkbox', checked: autoPoll, onChange: (ev) => setAutoPoll(ev.target.checked) }),
            'Auto-poll',
          ]),

          e('label', { key: 'int', style: { display: 'flex', alignItems: 'center', gap: 6 } }, [
            'Interval(s):',
            e('input', { key: 'num', type: 'number', min: 1, value: intervalSec, onChange: (ev) => setIntervalSec(ev.target.value) , style: { width: 70 } }),
          ]),

          e('button', { key: 'clear', onClick: clearHistory, style: { marginLeft: 'auto' } }, 'Clear History'),
          e('button', { key: 'export', onClick: exportHistoryCSV }, 'Export CSV'),
        ]),

        e('div', { key: 'main', style: { marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16 } }, [
          e('div', { key: 'left' }, [
            e('h3', { key: 'lh' }, 'Latest Result'),
            e('pre', { key: 'out', style: { marginTop: 4, background: '#f6f8fa', padding: 10, whiteSpace: 'pre-wrap' } }, result ? JSON.stringify(result, null, 2) : 'No result yet'),
          ]),

          e('div', { key: 'right', style: { border: '1px solid #eee', padding: 8, borderRadius: 6, height: 360, overflow: 'auto', fontSize: 12 } }, [
            e('h4', { key: 'rh' }, 'History'),
            e('ul', { key: 'hist', id: 'history', style: { listStyle: 'none', padding: 0, margin: 0 } }, history.length === 0 ? e('li', { key: 'empty', style: { color: '#666' } }, 'No history yet') : history.map((h, idx) => e('li', { key: h.timestamp + idx, style: { padding: '6px 4px', borderBottom: '1px solid #f0f0f0', lineHeight: '1.25' } }, [
              e('div', { key: 'row', style: { display: 'flex', justifyContent: 'space-between', gap: 8 } }, [
                e('div', { key: 'leftcol' }, [
                  e('div', { key: 'asset', style: { fontWeight: 600 } }, `${h.asset} — ${new Date(h.timestamp).toLocaleString()}`),
                  e('div', { key: 'data', style: { color: '#333', fontSize: 12 } }, JSON.stringify(h.data)),
                ]),
              ])
            ))),
          ]),
        ]),
      ]);
    }

    ReactDOM.createRoot(document.getElementById('root')).render(e(App));
  };
};

injectReact();
