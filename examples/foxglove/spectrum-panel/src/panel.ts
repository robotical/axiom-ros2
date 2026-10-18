import type { PanelExtensionContext, SettingsTreeAction } from "@foxglove/extension";
import { bandColor, barFraction, parseSample, readConfig } from "./spectrum.ts";
import type { Result } from "./spectrum.ts";
import { CSS } from "./style.ts";

const SVG = "http://www.w3.org/2000/svg";

export function initSpectrumPanel(context: PanelExtensionContext): () => void {
  const doc = context.panelElement.ownerDocument;
  const element = (tag: string, className: string, text?: string): HTMLElement => {
    const node = doc.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const root = element("div", "axiom-spectrum");
  const style = element("style", "");
  style.textContent = CSS;
  const top = element("div", "top");
  const title = element("div", "heading");
  const eyebrow = element("div", "eyebrow");
  eyebrow.append(element("span", "brand", "AXIOM"), element("span", "divider"),
    element("span", "", "SOUND SENSOR"));
  title.append(eyebrow, element("h2", "", "Sound spectrum"));
  const badge = element("span", "badge", "Waiting for samples");
  badge.setAttribute("role", "status");
  top.append(title, badge);
  const source = element("label", "source", "Source");
  const select = doc.createElement("select");
  select.setAttribute("aria-label", "DeviceSample topic");
  source.append(select);
  const chart = doc.createElementNS(SVG, "svg");
  chart.classList.add("chart");
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", "Sound band levels in dB by frequency in Hz");
  const message = element("div", "message", "Waiting for a sound sample. Select its DeviceSample topic above.");
  const plot = element("div", "plot");
  plot.append(message, chart);
  const footer = element("div", "footer");
  const summary = element("span", "", "Frequency labels come from the sensor descriptor");
  const frame = element("span", "", "");
  footer.append(summary, frame);
  root.append(style, top, source, plot, footer);
  context.panelElement.append(root);

  let config = readConfig(context.initialState);
  let result: Result | undefined;
  let lastReceived: number | undefined;
  let currentTime: number | undefined;
  let disposed = false;
  let topicNames = "";

  function svg(tag: string, attributes: Record<string, string | number>, text?: string): SVGElement {
    const node = doc.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    chart.append(node);
    return node;
  }

  function draw(): void {
    const spectrum = result?.spectrum;
    chart.replaceChildren();
    chart.style.display = spectrum ? "block" : "none";
    message.style.display = spectrum ? "none" : "grid";
    const stale = spectrum !== undefined && currentTime !== undefined && lastReceived !== undefined
      && currentTime - lastReceived > 5;
    root.classList.toggle("stale", stale);
    if (!spectrum) {
      root.dataset.state = result?.error ? "invalid" : "waiting";
      message.textContent = result?.error ?? "Waiting for a sound sample. Select its DeviceSample topic above.";
      badge.textContent = result?.error ? "Invalid sample" : "Waiting for samples";
      summary.textContent = "Frequency labels come from the sensor descriptor";
      frame.textContent = "";
      return;
    }
    const invalid = spectrum.bands.filter((band) => band.db === null).length;
    root.dataset.state = invalid === spectrum.bands.length ? "invalid" : invalid > 0 ? "partial" : "ready";
    badge.textContent = stale ? "Stale · no recent samples" : invalid === spectrum.bands.length
      ? "No valid bands" : invalid > 0 ? `${invalid} invalid band${invalid === 1 ? "" : "s"}` : "Latest sample";
    summary.textContent = `${spectrum.bands.length} bands · scale ${config.minDb} to ${config.maxDb} dB`;
    frame.textContent = spectrum.frame;
    frame.title = spectrum.frame;
    const width = Math.max(320, plot.clientWidth || root.clientWidth - 32);
    const height = Math.max(160, plot.clientHeight || root.clientHeight - 150);
    const left = 48, right = width - 20, topY = 32, bottom = height - 48;
    const plotHeight = bottom - topY;
    chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
    for (let i = 0; i <= 6; i++) {
      const y = bottom - (i / 6) * plotHeight;
      svg("line", { class: "grid", x1: left, x2: right, y1: y, y2: y });
      svg("text", { class: "tick", x: left - 10, y: y + 4, "text-anchor": "end" },
        ((i / 6) * (config.maxDb - config.minDb) + config.minDb).toFixed(0));
    }
    svg("text", { class: "axis", x: 8, y: 14 }, "dB");
    const step = (right - left) / spectrum.bands.length;
    const barWidth = Math.min(80, step * .6);
    spectrum.bands.forEach((band, index) => {
      const center = left + step * (index + .5);
      const x = center - barWidth / 2;
      const barHeight = band.db === null ? 0 : barFraction(band.db, config) * plotHeight;
      svg("rect", { class: "track", x, y: topY, width: barWidth, height: plotHeight, rx: 5 });
      if (band.db !== null) {
        const bar = svg("rect", { class: "bar", x, y: bottom - barHeight, width: barWidth,
          height: barHeight, rx: 5, fill: bandColor(index, spectrum.bands.length) });
        const tooltip = doc.createElementNS(SVG, "title");
        tooltip.textContent = `${band.label} Hz: ${band.db} dB`;
        bar.append(tooltip);
      }
      svg("text", { class: "value", x: center, y: Math.max(16, bottom - barHeight - 10),
        "text-anchor": "middle" }, band.db === null ? "—" : band.db.toFixed(1));
      svg("text", { class: "label", x: center, y: bottom + 24, "text-anchor": "middle" }, band.label);
    });
    svg("text", { class: "axis", x: (left + right) / 2, y: height - 4, "text-anchor": "middle" }, "Frequency (Hz)");
  }

  function updateSettings(): void {
    context.updatePanelSettingsEditor({
      nodes: { spectrum: { label: "Spectrum scale", fields: {
        minDb: { label: "Minimum dB", input: "number", value: config.minDb },
        maxDb: { label: "Maximum dB", input: "number", value: config.maxDb },
      } } },
      actionHandler: (action: SettingsTreeAction) => {
        if (action.action !== "update" || action.payload.path[0] !== "spectrum") return;
        const field = action.payload.path[1];
        const value = action.payload.value;
        if ((field !== "minDb" && field !== "maxDb") || typeof value !== "number" || !Number.isFinite(value)) return;
        const next = { ...config, [field]: value };
        if (next.maxDb <= next.minDb) return;
        config = next;
        context.saveState(config);
        updateSettings();
        draw();
      },
    });
  }

  function changeTopic(): void {
    config = { ...config, topic: select.value };
    result = undefined;
    lastReceived = undefined;
    context.saveState(config);
    context.subscribe([{ topic: config.topic }]);
    draw();
  }
  select.addEventListener("change", changeTopic);
  context.watch("topics");
  context.watch("currentFrame");
  context.watch("currentTime");
  context.watch("colorScheme");
  context.subscribe([{ topic: config.topic }]);
  updateSettings();
  context.onRender = (state, done) => {
    try {
      if (disposed) return;
      root.dataset.theme = state.colorScheme ?? "light";
      const available = (state.topics ?? []).filter((topic) => /(?:\/msg)?\/DeviceSample$/.test(topic.schemaName))
        .map((topic) => topic.name);
      const names = [...new Set([config.topic, ...available])].sort();
      if (names.join("\n") !== topicNames) {
        topicNames = names.join("\n");
        select.replaceChildren(...names.map((name) => {
          const option = doc.createElement("option");
          option.value = name;
          option.textContent = name;
          option.selected = name === config.topic;
          return option;
        }));
      }
      currentTime = state.currentTime ? state.currentTime.sec + state.currentTime.nsec / 1e9 : undefined;
      if (state.didSeek || (lastReceived !== undefined && currentTime !== undefined && currentTime < lastReceived)) {
        result = undefined;
        lastReceived = undefined;
      }
      for (const event of state.currentFrame ?? []) {
        if (event.topic !== config.topic) continue;
        result = parseSample(event.message);
        lastReceived = event.receiveTime.sec + event.receiveTime.nsec / 1e9;
      }
      draw();
    } finally {
      done();
    }
  };
  const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(() => draw());
  observer?.observe(plot);
  draw();
  return () => {
    disposed = true;
    observer?.disconnect();
    select.removeEventListener("change", changeTopic);
    context.onRender = undefined;
    context.subscribe([]);
    root.remove();
  };
}
