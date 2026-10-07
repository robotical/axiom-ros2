/* Read-only evidence for a teaching step. Endpoints do not prove message delivery. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ScenarioState = api;
})(typeof window === 'undefined' ? this : window, () => {
  function observe(check, state) {
    const graph = state.graph || {};
    const result = (text, detail = '', tone = 'pending') => ({text, detail, tone});
    if (!graph.available) return result('ROS state unavailable', 'Waiting for fresh discovery.');
    const board = namespace => namespace === '/marty' ? state.connections?.marty :
      (state.boards || []).find(b => b.namespace === namespace);
    const status = namespace => {
      const b = board(namespace);
      if (!b) return 'Driver offline';
      if (!b.available) return b.state || 'Status unavailable';
      return b.connected ? 'Connected' : 'Disconnected';
    };
    if (check.kind === 'driver') {
      const found = check.nodes.filter(n => (graph.nodes || []).includes(n));
      return result(found.length === check.nodes.length ?
        (found.length === 1 ? 'Node discovered' : 'Nodes discovered') :
        found.length ? `${found.length} / ${check.nodes.length} nodes discovered` : 'Node not discovered',
      '', found.length === check.nodes.length ? 'observed' : 'pending');
    }
    if (check.kind === 'connection') {
      const b = board(check.namespace);
      return result(status(check.namespace), b?.error || '',
        b?.available && b.connected === check.connected ? 'observed' : 'pending');
    }
    if (check.kind === 'acquisition') {
      return result(status(check.namespace),
        `Confirm success: true in Terminal ${check.terminal}. Discovery cannot verify acquisition.`);
    }
    if (check.kind === 'topic') {
      const topic = (graph.topics || []).find(t => t.name === check.topic);
      const publishers = topic?.publishers?.length || 0;
      const consoles = (topic?.subscribers || []).filter(n => /(?:^|\/)_(?:ros2cli)/.test(n)).length;
      return result(`${publishers} publisher${publishers === 1 ? '' : 's'}` +
        (check.console ? ` · ${consoles} console subscriber${consoles === 1 ? '' : 's'}` : ''),
      check.console ? `Endpoints only; confirm readings in Terminal ${check.terminal}.` :
        'Compare publisher count and QoS with the console output.',
      publishers && (!check.console || consoles) ? 'observed' : 'pending');
    }
    if (check.kind === 'range') {
      const b = board(check.namespace);
      const topics = (graph.topics || []).filter(t => t.name.startsWith(check.namespace + '/') &&
        t.types?.includes('sensor_msgs/msg/Range') && t.publishers?.length);
      return result(`${topics.length} distance publisher topic${topics.length === 1 ? '' : 's'}`,
        b?.connected ? 'Endpoint discovery; confirm sensor identity in the inventory.' :
          status(check.namespace),
        b?.available && b.connected && Boolean(topics.length) === check.present ?
          'observed' : 'pending');
    }
    if (check.kind === 'device') {
      const b = board(check.namespace);
      const found = (b?.devices || []).filter(d => d.online && !d.stale &&
        check.commands.every(name => (d.commands || []).some(c => c.name === name)));
      return result(`${found.length} matching module${found.length === 1 ? '' : 's'} online`,
        b?.connected ? 'Live device inventory and descriptor commands.' : status(check.namespace),
        b?.available && b.connected && Boolean(found.length) === check.present ? 'observed' : 'pending');
    }
    if (check.kind === 'discovery') {
      const entries = (graph[check.collection] || []).filter(e =>
        e.name.startsWith(check.namespace + '/') &&
        (check.collection !== 'topics' || e.publishers?.length));
      return result(`${entries.length} ${check.collection} discovered`, check.namespace);
    }
    if (check.kind === 'hardware') return result('Check the hardware',
      'Compare the expected result with the inventory and console.');
    return result('Check the console', `Verify this step in Terminal ${check.terminal || 'shown'}.`);
  }
  function isPresent(item, state) {
    if (!state.graph?.available) return false;
    if (item.kind === 'node') return state.graph.nodes?.includes(item.name) || false;
    if (item.kind === 'topic') return state.graph.topics?.some(t =>
      t.name === item.name && t.publishers?.length) || false;
    if (item.kind === 'service') return state.graph.services?.some(s =>
      s.name === item.name) || false;
    return false;
  }
  return {observe, isPresent};
});
