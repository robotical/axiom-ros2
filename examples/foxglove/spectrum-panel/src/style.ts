// Brand colours and surfaces follow Axiom-Experiment-App/src/styles/styles.css.
export const CSS = `
.axiom-spectrum {
  --axiom-teal:#27788c; --axiom-cyan:#37abc8; --axiom-sky:#73c4d9;
  --axiom-ink:#133c46; --axiom-cream:#f9eebe; --axiom-yellow:#ffda61; --axiom-orange:#ffa000;
  --bg:#f7fafc; --card:#fff; --text:var(--axiom-ink); --muted:#386676;
  --border:#d0e3e8; --grid:#e2edf0; --track:#edf5f7; --accent:var(--axiom-teal);
  --badge-bg:#eaf5f7; --warning:#8a5200; --warning-bg:#fff5d9;
  box-sizing:border-box; position:relative; display:flex; flex-direction:column; gap:10px;
  height:100%; min-height:0; overflow:auto; padding:16px;
  background:var(--bg); color:var(--text);
  font:13px "Segoe UI",Roboto,Oxygen,Ubuntu,Cantarell,"Helvetica Neue",sans-serif;
  container:axiom-spectrum / inline-size;
}
.axiom-spectrum::before {
  content:""; position:absolute; top:0; left:0; right:0; height:3px;
  background:linear-gradient(90deg,var(--axiom-teal),var(--axiom-cyan) 45%,var(--axiom-yellow) 80%,var(--axiom-orange));
}
.axiom-spectrum[data-theme="dark"] {
  color-scheme:dark;
  --bg:var(--axiom-ink); --card:#174550; --text:#fff; --muted:#a5d7e3;
  --border:#32616c; --grid:#2b5661; --track:#1d4d59; --accent:var(--axiom-sky);
  --badge-bg:#1c515e; --warning:var(--axiom-yellow); --warning-bg:#51472c;
}
.axiom-spectrum * { box-sizing:border-box }
.axiom-spectrum .top { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px 16px }
.axiom-spectrum .heading { min-width:0 }
.axiom-spectrum .eyebrow { display:flex; align-items:center; gap:9px; margin-bottom:6px;
  color:var(--muted); font-size:10px; letter-spacing:1.4px; line-height:1.2 }
.axiom-spectrum .brand { color:var(--accent); font-weight:800; letter-spacing:2px }
.axiom-spectrum .eyebrow .divider { width:1px; height:10px; background:var(--border) }
.axiom-spectrum h2 { margin:0; font-size:23px; font-weight:650; letter-spacing:-.6px; line-height:1.2 }
.axiom-spectrum .badge { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--border);
  padding:6px 10px; border-radius:20px; font-size:11px; color:var(--accent);
  white-space:nowrap; background:var(--badge-bg); line-height:1.3 }
.axiom-spectrum .badge::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor }
.axiom-spectrum[data-state="waiting"] .badge { color:var(--muted); background:var(--card) }
.axiom-spectrum[data-state="invalid"] .badge,
.axiom-spectrum[data-state="partial"] .badge,
.axiom-spectrum.stale .badge { color:var(--warning); background:var(--warning-bg) }
.axiom-spectrum .source { display:flex; gap:12px; align-items:center; color:var(--muted);
  font-size:11px; font-weight:600; flex-shrink:0 }
.axiom-spectrum select { min-width:0; flex:1; padding:8px 10px; border:1px solid var(--border);
  border-radius:6px; color:var(--text); background:var(--card); font:inherit; font-weight:400 }
.axiom-spectrum select:focus-visible { outline:2px solid var(--axiom-cyan); outline-offset:2px }
.axiom-spectrum .plot { flex:1 0 160px; min-height:160px; min-width:0; overflow:hidden;
  border:1px solid var(--border); border-radius:8px; background:var(--card) }
.axiom-spectrum .chart { width:100%; height:100%; display:block }
.axiom-spectrum .grid { stroke:var(--grid); stroke-width:1 }
.axiom-spectrum .tick,.axiom-spectrum .axis { fill:var(--muted); font-size:11px }
.axiom-spectrum .label { fill:var(--text); font-size:12px; font-weight:600 }
.axiom-spectrum .value { fill:var(--text); font-size:13px; font-weight:650; font-variant-numeric:tabular-nums }
.axiom-spectrum .track { fill:var(--track) }
.axiom-spectrum .bar { opacity:1; transition:opacity .15s ease }
.axiom-spectrum .bar:hover { opacity:.8 }
.axiom-spectrum .footer { display:flex; justify-content:space-between; flex-shrink:0; gap:12px;
  color:var(--muted); font-size:10px; line-height:1.4 }
.axiom-spectrum .footer span { min-width:0; overflow:hidden; white-space:nowrap; text-overflow:ellipsis }
.axiom-spectrum .message { height:100%; min-height:160px; display:grid; place-content:center;
  text-align:center; color:var(--muted); padding:24px; line-height:1.7 }
.axiom-spectrum.stale .bar { opacity:.35 }
@container axiom-spectrum (max-width:440px) {
 .axiom-spectrum h2 { font-size:20px }
 .axiom-spectrum .eyebrow { font-size:9px; gap:7px }
 .axiom-spectrum .badge { font-size:10px; padding:5px 8px }
 .axiom-spectrum .source { gap:8px }
}
@media (prefers-reduced-motion:reduce) { .axiom-spectrum .bar { transition:none } }
`;
