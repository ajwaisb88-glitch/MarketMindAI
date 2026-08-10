import React, { useState } from 'react';
import './License.css';

/** Activation gate — shown when the app requires a license and none is active. */
export default function License({ apiBase, status, onActivated }) {
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const activate = async () => {
    if (!key.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`${apiBase}/license/activate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key.trim() }),
      });
      const d = await r.json();
      if (d.valid) onActivated(d);
      else setErr(d.reason || 'That key was not accepted.');
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };

  const expired = status?.reason === 'license expired';
  return (
    <div className="lic">
      <div className="lic-card">
        <div className="lic-logo">📈</div>
        <h1>MarketMind AI</h1>
        <p className="lic-tag">Activate your copy to unlock the app.</p>

        {expired && <div className="lic-warn">⚠ Your license has expired. Enter a renewed key to continue.</div>}
        {status?.customer && <div className="lic-prev">Previous: {status.customer} · {status.tier}</div>}

        <label className="lic-label">License key</label>
        <textarea className="lic-input" rows={3} spellCheck={false}
          placeholder="Paste the license key you were given…"
          value={key} onChange={(e) => setKey(e.target.value)} />

        {err && <div className="lic-err">✕ {err}</div>}

        <button className="lic-btn" onClick={activate} disabled={busy || !key.trim()}>
          {busy ? 'Activating…' : 'Activate'}
        </button>

        <div className="lic-machine">
          <span>This machine ID</span>
          <code>{status?.machine_id || '—'}</code>
          <span className="lic-hint">Give this to the seller if your key is machine-locked.</span>
        </div>
        <div className="lic-foot">
          Need a key? Contact the author:<br />
          <b>Malik Muhammad Naveed</b><br />
          +92 343 3333344 &nbsp;·&nbsp; +92 300 5009379
        </div>
      </div>
    </div>
  );
}
