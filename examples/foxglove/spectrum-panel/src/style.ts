export const CSS = `
.axiom-spectrum {
  --bg:#f7f9fc; --card:#fff; --text:#172035; --muted:#637188; --grid:#dce3ef;
  box-sizing:border-box; height:100%; min-height:220px; overflow:auto;
  padding:20px 24px 16px; background:var(--bg); color:var(--text);
  font:13px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
.axiom-spectrum[data-theme="dark"] {
  --bg:#101625; --card:#172033; --text:#eef3fc; --muted:#97a7bf; --grid:#2b3850;
}
.axiom-spectrum * { box-sizing:border-box }
.axiom-spectrum .top { display:flex; align-items:center; justify-content:space-between; gap:12px }
.axiom-spectrum h2 { margin:0; font-size:20px; font-weight:650; letter-spacing:-.4px }
.axiom-spectrum .eyebrow { color:var(--muted); font-size:10px; letter-spacing:1.7px; margin-bottom:5px }
.axiom-spectrum .badge { border:1px solid var(--grid); padding:6px 10px; border-radius:20px;
  font-size:11px; color:var(--muted); white-space:nowrap; background:var(--card) }
.axiom-spectrum .source { display:flex; gap:8px; align-items:center; margin:14px 0 12px; color:var(--muted) }
.axiom-spectrum select { min-width:0; flex:1; padding:7px 10px; border:1px solid var(--grid);
  border-radius:7px; color:var(--text); background:var(--card); font:inherit; font-size:11px }
.axiom-spectrum .chart { width:100%; min-height:170px; height:calc(100% - 150px); display:block }
.axiom-spectrum .grid { stroke:var(--grid); stroke-width:1; stroke-dasharray:3 5 }
.axiom-spectrum .tick,.axiom-spectrum .axis { fill:var(--muted); font-size:12px }
.axiom-spectrum .label { fill:var(--text); font-size:14px; font-weight:550 }
.axiom-spectrum .value { fill:var(--text); font-size:14px; font-weight:650; font-variant-numeric:tabular-nums }
.axiom-spectrum .track { fill:var(--grid); opacity:.25 }
.axiom-spectrum .bar { opacity:.95 }
.axiom-spectrum .footer { display:flex; justify-content:space-between; gap:12px; color:var(--muted);
  font-size:11px; padding-top:9px; border-top:1px solid var(--grid) }
.axiom-spectrum .message { min-height:160px; display:grid; place-content:center; text-align:center;
  color:var(--muted); padding:30px; line-height:1.7 }
.axiom-spectrum.stale .bar { opacity:.35 }
.axiom-spectrum.stale .badge { color:#bd790e }
.axiom-spectrum .footer span { overflow:hidden; white-space:nowrap; text-overflow:ellipsis }
@media (max-width:460px) {
 .axiom-spectrum { padding:12px }
 .axiom-spectrum h2 { font-size:16px }
 .axiom-spectrum .source { margin:10px 0 }
 .axiom-spectrum .footer { font-size:10px }
}
`;
