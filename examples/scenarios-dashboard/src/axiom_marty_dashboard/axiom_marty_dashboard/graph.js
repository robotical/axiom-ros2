/* Read-only ROS graph. Multiple topics between the same nodes share an arrow. */
(function (root) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const key = (kind, name) => JSON.stringify([kind, name]);

  function model(graph, {scope = 'subscriptions', query = '', reference = false} = {}) {
    const search = query.trim().toLowerCase(), vertices = new Map(), links = new Map();
    const matches = name => name.toLowerCase().includes(search);
    const topics = (graph.topics || []).filter(t =>
      (reference || scope === 'all' || !t.infrastructure) &&
      (reference || scope !== 'subscriptions' || t.subscribers.length) &&
      (!search || matches(t.name) || [...t.publishers, ...t.subscribers].some(matches)));
    const participating = new Set(topics.flatMap(t => [...t.publishers, ...t.subscribers]));
    for (const row of graph.nodes || []) {
      const name = typeof row === 'string' ? row : row.name;
      if (reference && !participating.has(name)) continue;
      if ((!search && (!name.startsWith('/_') || scope === 'all')) ||
          matches(name) && search || participating.has(name)) {
        vertices.set(key('node', name), {id: key('node', name), name, kind: 'node'});
      }
    }
    function addLink(source, target, topic) {
      const id = JSON.stringify([source, target]);
      if (!links.has(id)) links.set(id, {id, source, target, topics: []});
      links.get(id).topics.push(topic);
    }
    for (const t of topics) {
      for (const n of [...t.publishers, ...t.subscribers]) {
        vertices.set(key('node', n), {id: key('node', n), name: n, kind: 'node'});
      }
      if (t.publishers.length && t.subscribers.length) {
        for (const p of t.publishers) for (const s of t.subscribers) {
          addLink(key('node', p), key('node', s), t);
        }
      } else {
        const waiting = !t.publishers.length;
        const id = key('topic', JSON.stringify([waiting, waiting ? t.subscribers : t.publishers]));
        if (!vertices.has(id)) vertices.set(id, {id, name: t.name, kind: 'topic', waiting, topics: []});
        vertices.get(id).topics.push(t.name);
        for (const p of t.publishers) addLink(key('node', p), id, t);
        for (const s of t.subscribers) addLink(id, key('node', s), t);
      }
    }
    return {vertices: [...vertices.values()], links: [...links.values()], topics};
  }

  function layout(data) {
    // Condense cycles before assigning ranks; a ROS node may both publish and subscribe.
    const adjacency = new Map(data.vertices.map(v => [v.id, []]));
    for (const e of data.links) adjacency.get(e.source).push(e.target);
    const indices = new Map(), low = new Map(), stack = [], active = new Set(), components = [];
    function visit(id) {
      indices.set(id, indices.size); low.set(id, indices.get(id)); stack.push(id); active.add(id);
      for (const child of adjacency.get(id)) {
        if (!indices.has(child)) { visit(child); low.set(id, Math.min(low.get(id), low.get(child))); }
        else if (active.has(child)) low.set(id, Math.min(low.get(id), indices.get(child)));
      }
      if (low.get(id) === indices.get(id)) {
        const group = []; let child;
        do { child = stack.pop(); active.delete(child); group.push(child); } while (child !== id);
        components.push(group);
      }
    }
    for (const v of data.vertices) if (!indices.has(v.id)) visit(v.id);
    const component = new Map(components.flatMap((c, i) => c.map(id => [id, i])));
    const outgoing = components.map(() => new Set()), incoming = components.map(() => 0);
    for (const e of data.links) {
      const a = component.get(e.source), b = component.get(e.target);
      if (a !== b && !outgoing[a].has(b)) { outgoing[a].add(b); incoming[b]++; }
    }
    const rank = components.map(() => 0), queue = incoming.flatMap((n, i) => n ? [] : [i]);
    for (let i = 0; i < queue.length; i++) for (const next of outgoing[queue[i]]) {
      rank[next] = Math.max(rank[next], rank[queue[i]] + 1);
      if (--incoming[next] === 0) queue.push(next);
    }
    const layers = [];
    for (const v of data.vertices) (layers[rank[component.get(v.id)]] ||= []).push(v);
    for (const row of layers) row.sort((a, b) => a.name.localeCompare(b.name));
    const columns = Math.max(1, ...layers.map(row => row.length)), width = columns * 210 + 70;
    const height = Math.max(130, (layers.length - 1) * 112 + 104), positions = new Map();
    layers.forEach((row, r) => row.forEach((v, i) => positions.set(v.id, {
      ...v, x: 25 + (columns - row.length) * 105 + i * 210, y: 24 + r * 112,
      width: 180, height: 56, rank: r,
    })));
    // Reserve space for self/cyclic arrows returning along the right-hand side.
    const cyclic = data.links.some(e => positions.get(e.target).rank <= positions.get(e.source).rank);
    const skipping = data.links.some(e => positions.get(e.target).rank > positions.get(e.source).rank + 1);
    if (skipping) for (const v of positions.values()) v.x += 150;
    return {positions, width: width + (cyclic ? 100 : 0) + (skipping ? 150 : 0), height};
  }

  function el(tag, cls = '', value = '') {
    const e = document.createElement(tag); e.className = cls; e.textContent = value; return e;
  }
  function svg(tag, attrs = {}, value = '') {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    e.textContent = value; return e;
  }
  function button(label, action) {
    const b = el('button', '', label); b.type = 'button'; b.onclick = action; return b;
  }
  function shellQuote(value) { return "'" + value.replaceAll("'", "'\\''") + "'"; }
  function command(value, recipe) {
    const box = el('div', 'graph-command'), pre = el('pre', '', value);
    const actions = el('span', 'command-actions');
    actions.append(button('Copy', async event => {
      const target = event.currentTarget;
      try { await navigator.clipboard.writeText(value); target.textContent = 'Copied'; }
      catch { target.textContent = 'Select text'; }
    }), root.CommandInfo.button({...recipe, command: value}));
    box.append(actions, pre);
    return box;
  }
  const widgets = {}, snapshots = {};

  function interfaceTitle(kind, row, context) {
    const head = el('div', 'interface-title');
    head.append(el('span', 'source', row.name), root.InterfaceInfo.button(kind, row, context));
    return head;
  }

  function interfaces(parent, title, rows, direction, context, kind = 'topic') {
    parent.append(el('h3', '', title));
    if (!rows.length) { parent.append(el('p', 'muted', 'None')); return; }
    const table = el('table');
    for (const t of rows) {
      const row = el('tr'), cell = el('td');
      cell.append(interfaceTitle(kind, t, {...context, direction}),
        el('small', '', (t.types || [t.type].filter(Boolean)).join(', ')));
      if (t.note) cell.append(el('div', 'muted', t.note));
      if (t.role) cell.append(el('div', 'muted', t.role));
      const endpoints = t[direction + '_endpoints'] || [];
      const info = endpoints.map(e => e.node + ' · ' + e.reliability + ' · ' + e.durability);
      const peers = t[direction === 'subscriber' ? 'publishers' : 'subscribers'] || [];
      if (info.length) cell.append(el('div', 'endpoint-info', info.join('\n')));
      if (peers.length) cell.append(el('div', 'source',
        (direction === 'subscriber' ? 'From ' : 'To ') + peers.join(', ')));
      row.append(cell); table.append(row);
    }
    parent.append(table);
  }

  function inspect(kind, selected) {
    const w = widgets[kind], graph = snapshots[kind];
    w.selected = selected; w.inspector.replaceChildren();
    w.picker.value = selected?.kind === 'node' ? selected.name : '';
    for (const group of w.viewport.querySelectorAll('[data-selection]')) {
      group.classList.toggle('selected', group.getAttribute('data-selection') === JSON.stringify(selected));
    }
    if (!selected) { w.inspector.append(el('p', 'muted', 'Select a node or arrow for interfaces.')); return; }
    if (selected.kind === 'node') {
      const reference = kind === 'reference';
      const row = reference ? graph.nodes.find(n => n.name === selected.name) : null;
      if (reference && !row || !reference && !graph.nodes.includes(selected.name)) {
        w.selected = null; inspect(kind, null); return;
      }
      w.inspector.append(el('h2', '', row?.title || 'Running node'), el('p', 'source', selected.name));
      if (row?.role) w.inspector.append(el('p', 'muted', row.role));
      const pubs = row?.publications || graph.topics.filter(t => t.publishers.includes(selected.name));
      const subs = row?.subscriptions || graph.topics.filter(t => t.subscribers.includes(selected.name));
      const context = {reference, node: selected.name};
      const contracts = rows => rows.map(t => ({...graph.topics.find(r => r.name === t.name), ...t}));
      interfaces(w.inspector, 'Published topics · ' + pubs.length, contracts(pubs), 'publisher', context);
      interfaces(w.inspector, 'Subscribed topics · ' + subs.length, contracts(subs), 'subscriber', context);
      if (row?.services?.length) interfaces(w.inspector, 'Services · ' + row.services.length,
        row.services, '', context, 'service');
      if (row?.actions?.length) interfaces(w.inspector, 'Actions · ' + row.actions.length,
        row.actions, '', context, 'action');
      const value = row?.command || 'ros2 node info ' + shellQuote(selected.name);
      w.inspector.append(command(value, row?.command ? row :
        root.CommandInfo.inspection('node', selected.name, value)));
      if (reference && row.command.includes('bus_BUS')) w.inspector.append(el('p', 'muted',
        'Replace BUS and ADDRESS using /axiom/devices.'));
    } else {
      const names = selected.topics || [selected.name];
      const rows = graph.topics.filter(t => names.includes(t.name));
      if (!rows.length) { w.selected = null; inspect(kind, null); return; }
      w.inspector.append(el('h2', '', rows.length === 1 ? 'Topic' : 'Topics on this arrow'));
      for (const t of rows) {
        w.inspector.append(interfaceTitle('topic', t, {reference: kind === 'reference'}),
          el('p', 'muted', t.types.join(', ')));
        if (t.note) w.inspector.append(el('p', 'muted', t.note));
        w.inspector.append(el('p', 'muted',
          'Publishers: ' + (t.publishers.join(', ') || 'none · waiting for a source')),
          el('p', 'muted', 'Subscribers: ' + (t.subscribers.join(', ') || 'none')));
        for (const [field, label] of [['publisher_endpoints', 'Publisher'], ['subscriber_endpoints', 'Subscriber']]) {
          for (const e of t[field] || []) w.inspector.append(el('div', 'endpoint-info',
            `${label}: ${e.node} · ${e.reliability} · ${e.durability}`));
        }
        const info = 'ros2 topic info ' + shellQuote(t.name) + ' --verbose';
        w.inspector.append(command(info, root.CommandInfo.inspection('topic', t.name, info)));
        const retained = t.retained || t.publisher_endpoints?.length &&
          t.publisher_endpoints.every(e => e.durability === 'TRANSIENT_LOCAL');
        const echo = 'ros2 topic echo ' + shellQuote(t.name) +
          ' --qos-reliability best_effort' + (retained ? ' --qos-durability transient_local' : '');
        w.inspector.append(command(echo,
          root.CommandInfo.inspection('echo', t.name, echo, retained)));
      }
    }
  }

  function attach(kind) {
    const container = document.getElementById(kind + '-graph');
    const w = {container, zoom: 1, selected: null, signature: '', scope: 'subscriptions', query: ''};
    widgets[kind] = w;
    const bar = el('div', 'graph-toolbar');
    if (kind === 'running') {
      const scope = el('select'); scope.setAttribute('aria-label', 'Graph topics');
      for (const [value, title] of [['subscriptions', 'With subscriptions'], ['application', 'All application topics'], ['all', 'All ROS topics']]) {
        const option = el('option', '', title); option.value = value; scope.append(option);
      }
      scope.onchange = () => { w.scope = scope.value; draw(kind, true); };
      const search = el('input'); search.placeholder = 'Filter node or topic';
      search.setAttribute('aria-label', 'Filter running graph');
      search.oninput = () => { w.query = search.value; draw(kind, true); };
      bar.append(scope, search);
    }
    bar.append(button('−', () => { w.zoom = Math.max(.3, w.zoom / 1.25); scale(w); }),
      button('+', () => { w.zoom = Math.min(2, w.zoom * 1.25); scale(w); }),
      button('Fit', () => { w.zoom = Math.min(1, (w.viewport.clientWidth - 10) / w.width); scale(w); }));
    w.viewport = el('div', 'ros-graph-viewport');
    w.viewport.setAttribute('aria-label', kind === 'running' ? 'Running ROS graph' : 'Available ROS graph');
    w.counts = el('div', 'graph-counts muted');
    w.picker = el('select'); w.picker.setAttribute('aria-label', kind === 'running' ? 'Inspect running node' : 'Inspect available node');
    w.picker.onchange = () => inspect(kind, {kind: 'node', name: w.picker.value});
    w.inspector = el('div', 'graph-inspector');
    container.replaceChildren(bar, w.counts, w.viewport, w.picker, w.inspector);
  }
  function scale(w) {
    if (!w.canvas) return;
    w.canvas.style.width = w.width * w.zoom + 'px';
    w.canvas.style.height = w.height * w.zoom + 'px';
  }
  function labels(name) {
    const at = name.lastIndexOf('/');
    const first = name.slice(0, at) || '/', last = name.slice(at + 1);
    const shorten = s => s.length > 25 ? s.slice(0, 23) + '…' : s;
    return [shorten(first), shorten(last)];
  }
  function selectable(group, action) {
    group.setAttribute('role', 'button'); group.setAttribute('tabindex', '0');
    group.onclick = action; group.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
    };
  }
  function draw(kind, force = false) {
    const w = widgets[kind], graph = snapshots[kind], reference = kind === 'reference';
    const signature = JSON.stringify([graph, w.scope, w.query]);
    if (!force && w.signature === signature && (w.initialized || !w.viewport.clientWidth)) return;
    w.signature = signature;
    const data = model(graph, {scope: w.scope, query: w.query, reference});
    const placed = layout(data); w.width = placed.width; w.height = placed.height;
    const canvas = svg('svg', {viewBox: `0 0 ${w.width} ${w.height}`, role: 'img',
      'aria-label': reference ? 'Possible node connections' : 'Discovered publisher and subscriber connections'});
    const defs = svg('defs'), marker = svg('marker', {id: kind + '-arrow', viewBox: '0 0 10 10',
      refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
    marker.append(svg('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: '#588b87'})); defs.append(marker); canvas.append(defs);
    for (const e of data.links) {
      const a = placed.positions.get(e.source), b = placed.positions.get(e.target);
      const ax = a.x + a.width / 2, ay = a.y + a.height, bx = b.x + b.width / 2, by = b.y;
      let path, lx, ly;
      if (b.rank > a.rank + 1) {
        // Go around intermediate rows instead of drawing through unrelated nodes.
        path = `M ${ax} ${ay} C ${ax} ${ay + 25} 30 ${ay + 25} 30 ${ay + 40}` +
          ` L 30 ${by - 40} Q 30 ${by - 20} 50 ${by - 20} L ${bx - 20} ${by - 20}` +
          ` Q ${bx} ${by - 20} ${bx} ${by}`;
        lx = 77; ly = (ay + by) / 2;
      } else if (b.rank > a.rank) {
        const middle = (ay + by) / 2;
        path = `M ${ax} ${ay} C ${ax} ${middle} ${bx} ${middle} ${bx} ${by}`;
        lx = (ax + bx) / 2; ly = middle;
      } else {
        const bend = placed.width - 30;
        path = `M ${a.x + a.width} ${a.y + 20} C ${bend} ${a.y + 20} ${bend} ${b.y + 42} ${b.x + b.width} ${b.y + 42}`;
        lx = bend - 25; ly = (a.y + b.y) / 2 + 30;
      }
      const g = svg('g', {class: 'ros-edge' + (a.waiting ? ' waiting' : '')});
      g.append(svg('title', {}, e.topics.map(t => t.name).join('\n')),
        svg('path', {d: path, 'marker-end': `url(#${kind}-arrow)`}));
      const label = e.topics.length > 1 ? `${e.topics.length} topics` :
        e.topics[0].name.split('/').slice(-2).join('/');
      g.append(svg('rect', {x: lx - 66, y: ly - 9, width: 132, height: 18, rx: 3}),
        svg('text', {x: lx, y: ly + 3, 'text-anchor': 'middle'}, label.length > 24 ? label.slice(0, 22) + '…' : label));
      const selection = {kind: 'edge', topics: e.topics.map(t => t.name)};
      g.setAttribute('data-selection', JSON.stringify(selection));
      selectable(g, () => inspect(kind, selection));
      canvas.append(g);
    }
    for (const v of placed.positions.values()) {
      const g = svg('g', {class: 'ros-vertex ' + v.kind + (v.waiting ? ' waiting' : ''),
        'aria-label': (v.kind === 'node' ? 'Node ' : 'Topic ') + v.name});
      g.append(svg('title', {}, (v.topics || [v.name]).join('\n') +
        (v.waiting ? '\nNo publisher discovered' : '')));
      g.append(v.kind === 'node' ? svg('ellipse', {cx: v.x + 90, cy: v.y + 28, rx: 90, ry: 28}) :
        svg('rect', {x: v.x, y: v.y, width: 180, height: 56, rx: 4}));
      const lines = v.topics?.length > 1 ?
        [v.waiting ? 'Waiting for publishers' : 'No subscribers', v.topics.length + ' topics'] : labels(v.name);
      lines.forEach((line, i) => g.append(svg('text', {x: v.x + 90,
        y: v.y + 24 + i * 15, 'text-anchor': 'middle'}, line)));
      const selection = v.topics ? {kind: 'edge', topics: v.topics} : {kind: v.kind, name: v.name};
      g.setAttribute('data-selection', JSON.stringify(selection));
      selectable(g, () => inspect(kind, selection)); canvas.append(g);
    }
    w.canvas = canvas; w.viewport.replaceChildren(canvas);
    if (!w.initialized && w.viewport.clientWidth) { w.zoom = Math.min(1, (w.viewport.clientWidth - 10) / w.width); w.initialized = true; }
    scale(w);
    if (!reference && graph.available === false) {
      w.viewport.replaceChildren(el('p', 'empty', 'Graph discovery unavailable'));
    } else if (!data.vertices.length) w.viewport.replaceChildren(el('p', 'empty',
      w.query ? 'No matching nodes or topics' : 'No nodes discovered'));
    w.counts.textContent = `${graph.nodes.length} ${reference ? 'available' : 'discovered'} nodes · ` +
      `${data.topics.length} topics shown · arrows group shared topics`;
    const old = w.picker.value;
    const placeholder = el('option', '', 'Inspect a node…'); placeholder.value = '';
    w.picker.replaceChildren(placeholder, ...graph.nodes.map(row => {
      const option = el('option', '', typeof row === 'string' ? row : row.title);
      option.value = typeof row === 'string' ? row : row.name; return option;
    }));
    if ([...w.picker.options].some(o => o.value === old)) w.picker.value = old;
    if (!w.selected && reference && graph.nodes.length) w.selected = {kind: 'node', name: graph.nodes[0].name};
    inspect(kind, w.selected);
  }
  function update(graph, catalogue) {
    if (!widgets.running) { attach('running'); attach('reference'); }
    snapshots.running = graph; snapshots.reference = catalogue;
    draw('running'); draw('reference');
  }
  const api = {model, layout, update};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RosGraph = api;
})(typeof window === 'undefined' ? null : window);
