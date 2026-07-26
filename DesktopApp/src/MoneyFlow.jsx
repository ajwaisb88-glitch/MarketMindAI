import React, { useState, useEffect, useRef, useCallback } from 'react';
import './MoneyFlow.css';

const GREEN = '#00d474', RED = '#ff4d4d', GOLD = '#e3b341', DIM = '#8b949e', BG = '#05080c';
const ICO = { high: '▲', watch: '◆', info: '●' };

const fmtB = (v) => {
  if (v === null || v === undefined) return '—';
  const s = v >= 0 ? '+$' : '-$', a = Math.abs(v);
  return a < 0.095 ? `${s}${(a * 1000).toFixed(0)}M` : `${s}${a.toFixed(1)}B`;
};
const fmtP = (p) => (p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 0 })
  : p >= 1 ? p.toFixed(2) : p.toFixed(4));
const fc = (v) => (v >= 0 ? GREEN : RED);

/** Global Money Flow — liquidity → currencies → asset classes → instruments. */
export default function MoneyFlow({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const canvasRef = useRef(null);
  const stateRef = useRef({ nodes: [], edges: [], particles: [], W: 0, H: 530 });
  const rafRef = useRef(0);

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null);
    try {
      const res = await fetch(`${apiBase}/moneyflow${refresh ? '?refresh=1' : ''}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  }, [apiBase]);

  // On mount, keep retrying until the backend is up — it can take ~15-30s to
  // boot and warm the money-flow data, and we never want the panel stuck on
  // "Failed to fetch" just because it loaded a few seconds too early.
  useEffect(() => {
    let alive = true, tries = 0;
    const attempt = async () => {
      if (!alive) return;
      try {
        const res = await fetch(`${apiBase}/moneyflow`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!alive) return;
        setData(await res.json()); setError(null); setLoading(false);
      } catch (e) {
        tries += 1;
        if (!alive) return;
        setLoading(true);
        setError(tries >= 15 ? String(e.message || e) : null);   // give up after ~45s
        setTimeout(attempt, 3000);
      }
    };
    attempt();
    return () => { alive = false; };
  }, [apiBase]);

  // ── build the node/edge layout ──
  const layout = useCallback(() => {
    const cv = canvasRef.current; if (!cv || !data) return;
    const S = stateRef.current;
    const nodes = [], edges = [];
    const W = Math.max((cv.parentElement?.clientWidth || 1240) - 2, 1240);
    cv.style.width = `${W}px`;
    const cx = W / 2;

    const L = data.liquidity || {};
    const liq = { x: cx - 130, y: 18, w: 260, h: 64, kind: 'liq', title: L.label, sub: L.sub,
      flow: L.flow_b, dir: L.dir, evidence: L.evidence || [] };
    nodes.push(liq);

    const ccy = data.currencies || [];
    const ccyW = 170, gap = 24, tot = ccy.length * ccyW + (ccy.length - 1) * gap;
    ccy.forEach((c, i) => {
      const n = { x: cx - tot / 2 + i * (ccyW + gap), y: 120, w: ccyW, h: 56, kind: 'ccy',
        title: c.label, price: c.price, chg: c.chg_pct, state: c.state,
        evidence: [`${c.label} ${fmtP(c.price)} (${c.chg_pct >= 0 ? '+' : ''}${c.chg_pct}%) — ${c.state}`,
          'Source: Yahoo Finance daily'] };
      nodes.push(n);
      edges.push({ from: liq, to: n, flow: L.dir === 'up' ? 1 : -1, mag: 1.5 });
    });

    const classes = data.classes || [];
    const clsY = 250, clsH = 92, k = classes.length || 1;
    const clsW = Math.min(215, (W - 40 - (k - 1) * gap) / k), cTot = k * clsW + (k - 1) * gap;
    const bus = nodes.filter((n) => n.kind === 'ccy');
    classes.forEach((c, i) => {
      const n = { x: cx - cTot / 2 + i * (clsW + gap), y: clsY, w: clsW, h: clsH, kind: 'class',
        title: c.label, flow: c.flow_1d_b, flow5: c.flow_5d_b,
        evidence: [`${c.label}: 1d ${fmtB(c.flow_1d_b)}, 5d ${fmtB(c.flow_5d_b)}`, c.evidence, data.caveat] };
      nodes.push(n);
      bus.forEach((b) => edges.push({ from: b, to: n, flow: c.flow_1d_b, mag: Math.abs(c.flow_1d_b), thin: true }));
      const kids = c.children || [];
      const tAbs = kids.reduce((s, x) => s + Math.abs(x.flow_1d_b), 0) || 1;
      const kw = (clsW - (kids.length - 1) * 6) / Math.max(kids.length, 1);
      kids.forEach((kid, j) => {
        const alloc = Math.round((Math.abs(kid.flow_1d_b) / tAbs) * 100);
        const kn = { x: n.x + j * (kw + 6), y: clsY + clsH + 62, w: kw, h: 96, kind: 'child',
          title: kid.label, price: kid.price, chg: kid.chg_pct, flow: kid.flow_1d_b, alloc,
          evidence: [`${kid.label}: 1d ${fmtB(kid.flow_1d_b)}, 5d ${fmtB(kid.flow_5d_b)}`,
            `Share of class activity: ${alloc}%`,
            `Price ${fmtP(kid.price)} (${kid.chg_pct >= 0 ? '+' : ''}${kid.chg_pct}%)`, data.caveat] };
        nodes.push(kn);
        edges.push({ from: n, to: kn, flow: kid.flow_1d_b, mag: Math.abs(kid.flow_1d_b) });
      });
    });

    const H = 250 + clsH + 62 + 96 + 30;
    cv.style.height = `${H}px`;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);

    const particles = [];
    edges.forEach((e) => {
      const n = Math.max(1, Math.min(6, Math.round(Math.abs(e.mag) / 3) + 1));
      for (let i = 0; i < n; i++) {
        particles.push({ e, t: Math.random(), speed: 0.002 + Math.min(0.006, Math.abs(e.mag) / 4000 + 0.002) });
      }
    });
    Object.assign(S, { nodes, edges, particles, W, H });
  }, [data]);

  // ── draw loop ──
  useEffect(() => {
    if (!data) return;
    layout();
    const cv = canvasRef.current; if (!cv) return;
    const ctx = cv.getContext('2d');
    const S = stateRef.current;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const anchor = (n, o) => {
      if (o.y > n.y + n.h) return { x: n.x + n.w / 2, y: n.y + n.h };
      if (o.y + o.h < n.y) return { x: n.x + n.w / 2, y: n.y };
      return { x: o.x > n.x ? n.x + n.w : n.x, y: n.y + n.h / 2 };
    };
    const bez = (e) => {
      const a = anchor(e.from, e.to), b = anchor(e.to, e.from);
      return { a, b, my: (a.y + b.y) / 2 };
    };
    const rr = (x, y, w, h, r) => {
      ctx.beginPath(); ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    };
    const drawNode = (n) => {
      const cx = n.x + n.w / 2;
      const col = n.kind === 'liq' ? (n.dir === 'up' ? GOLD : RED)
        : n.kind === 'ccy' ? '#58a6ff' : fc(n.flow === undefined ? 0 : n.flow);
      rr(n.x, n.y, n.w, n.h, 8); ctx.fillStyle = '#0d1117'; ctx.fill();
      ctx.strokeStyle = `${col}55`; ctx.lineWidth = 1; ctx.stroke();
      ctx.textAlign = 'center';
      if (n.kind === 'liq') {
        ctx.fillStyle = col; ctx.font = '700 12px ui-monospace,Consolas,monospace';
        ctx.fillText(n.title, cx, n.y + 24);
        ctx.fillStyle = DIM; ctx.font = '10px ui-monospace,Consolas,monospace';
        ctx.fillText(n.sub || '', cx, n.y + 41);
        ctx.fillStyle = n.dir === 'up' ? GREEN : RED; ctx.font = '700 11px ui-monospace,Consolas,monospace';
        ctx.fillText(n.flow != null ? `${fmtB(n.flow)} wk` : (n.dir === 'up' ? '▲ EASING' : '▼ TIGHTENING'), cx, n.y + 57);
      } else if (n.kind === 'ccy') {
        ctx.fillStyle = '#58a6ff'; ctx.font = '700 11px ui-monospace,Consolas,monospace';
        ctx.fillText(n.title, cx, n.y + 20);
        ctx.fillStyle = '#d6dde6'; ctx.font = '11px ui-monospace,Consolas,monospace';
        ctx.fillText(`${fmtP(n.price)}  (${n.chg >= 0 ? '+' : ''}${n.chg}%)`, cx, n.y + 36);
        ctx.fillStyle = n.chg >= 0 ? GREEN : RED; ctx.font = '9px ui-monospace,Consolas,monospace';
        ctx.fillText(String(n.state || '').toUpperCase(), cx, n.y + 50);
      } else if (n.kind === 'class') {
        ctx.fillStyle = '#d6dde6'; ctx.font = '700 12px ui-monospace,Consolas,monospace';
        ctx.fillText(n.title, cx, n.y + 22);
        ctx.fillStyle = fc(n.flow); ctx.font = '700 17px ui-monospace,Consolas,monospace';
        ctx.fillText(fmtB(n.flow), cx, n.y + 46);
        ctx.fillStyle = n.flow >= 0 ? GREEN : RED; ctx.font = '9px ui-monospace,Consolas,monospace';
        ctx.fillText(n.flow >= 0 ? 'MONEY IN' : 'MONEY OUT', cx, n.y + 64);
        ctx.fillStyle = DIM; ctx.font = '10px ui-monospace,Consolas,monospace';
        ctx.fillText(`5d ${fmtB(n.flow5)}`, cx, n.y + 80);
      } else {
        ctx.fillStyle = '#d6dde6'; ctx.font = '700 10px ui-monospace,Consolas,monospace';
        ctx.fillText(String(n.title).split(' · ')[0].slice(0, Math.floor(n.w / 7)), cx, n.y + 15);
        ctx.fillStyle = GOLD; ctx.font = '9px ui-monospace,Consolas,monospace';
        ctx.fillText(`${n.alloc}%`, cx, n.y + 32);
        ctx.fillStyle = '#d6dde6'; ctx.font = '11px ui-monospace,Consolas,monospace';
        ctx.fillText(fmtP(n.price), cx, n.y + 50);
        ctx.fillStyle = n.chg >= 0 ? GREEN : RED; ctx.font = '10px ui-monospace,Consolas,monospace';
        ctx.fillText(`${n.chg >= 0 ? '+' : ''}${n.chg}%`, cx, n.y + 65);
        ctx.fillStyle = fc(n.flow); ctx.font = '700 11px ui-monospace,Consolas,monospace';
        ctx.fillText(fmtB(n.flow), cx, n.y + 82);
      }
    };

    const frame = () => {
      ctx.fillStyle = BG; ctx.fillRect(0, 0, S.W, S.H);
      S.edges.forEach((e) => {
        const { a, b, my } = bez(e);
        ctx.strokeStyle = fc(e.flow) + (e.thin ? '22' : '44');
        ctx.lineWidth = e.thin ? 0.6 : 1.2;
        ctx.beginPath(); ctx.moveTo(a.x, a.y);
        ctx.bezierCurveTo(a.x, my, b.x, my, b.x, b.y); ctx.stroke();
      });
      S.particles.forEach((p) => {
        if (!reduce) { p.t += p.speed; if (p.t > 1) p.t = 0; }
        const { a, b, my } = bez(p.e), t = p.t, u = 1 - t;
        const x = u * u * u * a.x + 3 * u * u * t * a.x + 3 * u * t * t * b.x + t * t * t * b.x;
        const y = u * u * u * a.y + 3 * u * u * t * my + 3 * u * t * t * my + t * t * t * b.y;
        ctx.fillStyle = fc(p.e.flow); ctx.globalAlpha = 0.85;
        ctx.beginPath(); ctx.arc(x, y, 1.8, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
      });
      S.nodes.forEach(drawNode);
      rafRef.current = requestAnimationFrame(frame);
    };
    frame();
    const onResize = () => layout();
    window.addEventListener('resize', onResize);
    return () => { cancelAnimationFrame(rafRef.current); window.removeEventListener('resize', onResize); };
  }, [data, layout]);

  const onCanvasClick = (ev) => {
    const cv = canvasRef.current; if (!cv) return;
    const r = cv.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    const hit = [...stateRef.current.nodes].reverse()
      .find((n) => x >= n.x && x <= n.x + n.w && y >= n.y && y <= n.y + n.h);
    if (hit) setEvidence({ title: hit.title, lines: hit.evidence || [] });
  };

  if (!data && error) return (
    <section className="card error">⚠ Money flow unavailable — {error}
      {' '}<button className="mf-refresh" onClick={() => load(true)}>Retry</button>
    </section>
  );
  if (!data) return (
    <section className="card mf-loading">Loading money flow… (first read pulls live Fed, Yahoo &amp; Binance data — up to ~15s)</section>
  );

  const L = data.liquidity || {};
  const draining = L.dir === 'down';
  const warns = data.warnings || [];
  const nHigh = warns.filter((w) => w.level === 'high').length;
  const riskTot = Math.abs(data.risk_in_b) + Math.abs(data.safe_in_b) || 1;
  const riskPct = (Math.abs(data.risk_in_b) / riskTot) * 100;

  return (
    <div className="mf">
      <div className="mf-bar">
        <div className="mf-brand"><span className="mf-logo">◆</span>GLOBAL <b>MONEY FLOW</b></div>
        <div className="mf-stats">
          <div className={`mf-hs${draining ? ' drain' : ''}`}>
            <span className="k">FED LIQUIDITY · WK</span>
            <span className={`v ${draining ? 'out' : 'in'}`}>
              {L.flow_b != null ? fmtB(L.flow_b) : (draining ? 'TIGHTENING' : 'EASING')}
            </span>
          </div>
          <div className="mf-hs"><span className="k">NET FLOW · 24H</span>
            <span className={`v ${data.net_flow_b >= 0 ? 'in' : 'out'}`}>{fmtB(data.net_flow_b)}</span></div>
          <div className="mf-hs"><span className="k">VIX</span>
            <span className={`v ${data.vix > 20 ? 'out' : ''}`}>{data.vix}</span></div>
          <div className="mf-hs regime"><span className="k">REGIME</span><span className="v">{data.regime}</span></div>
        </div>
        <button className="mf-refresh" onClick={() => load(true)} disabled={loading}>
          {loading ? '…' : '↻ Refresh'}
        </button>
      </div>

      {warns.length > 0 && (
        <section className="card mf-warns">
          <div className="mf-ph"><span className="pt">⚠ WHAT'S GOING ON</span>
            <span className="psub">{warns.length} active · {nHigh} high priority</span></div>
          {warns.map((w, i) => (
            <div key={i} className={`mf-warn ${w.level}`}>
              <span className="w-ico">{ICO[w.level] || '●'}</span>
              <div className="w-body">
                <div className="w-title">{w.title}</div>
                <div className="w-detail">{w.detail}</div>
              </div>
              <span className="w-lvl">{w.level.toUpperCase()}</span>
            </div>
          ))}
          <div className="mf-foot">Warnings describe conditions, not trade instructions.</div>
        </section>
      )}

      <div className="mf-rot">
        <span className="rl">ROTATION</span>
        <span className="rfrom">{data.rotation?.from}</span>
        <span className="rarrow">→</span>
        <span className="rto">{data.rotation?.to}</span>
        <span className="rnote">{data.regime_note}</span>
      </div>

      <section className="card">
        <div className="mf-ph"><span className="pt">FLOW TREE</span>
          <span className="psub">click any node for the evidence</span></div>
        <div className="mf-canvas-box">
          <canvas ref={canvasRef} onClick={onCanvasClick} style={{ display: 'block', cursor: 'pointer' }} />
        </div>
      </section>

      <section className="card">
        <div className="mf-ph"><span className="pt">EVIDENCE</span>
          <span className="psub">{evidence ? evidence.title : 'click a node above'}</span></div>
        <ul className="mf-ev">
          {(evidence?.lines || ['Select any node in the tree to see what the number means and where it came from.'])
            .map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </section>

      <section className="card">
        <div className="mf-ph"><span className="pt">RISK BALANCE</span><span className="psub">risk vs safety</span></div>
        <div className="mf-bwrap">
          <div className="mf-bside risk" style={{ width: `${riskPct}%` }}>{Math.round(riskPct)}%</div>
          <div className="mf-bside safe" style={{ width: `${100 - riskPct}%` }}>{Math.round(100 - riskPct)}%</div>
        </div>
        <div className="mf-blabels"><span className="in">RISK · stocks·crypto·meme</span>
          <span className="dim">SAFE · bonds·metals</span></div>
      </section>
    </div>
  );
}
