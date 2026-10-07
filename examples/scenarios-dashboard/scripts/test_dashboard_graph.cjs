const assert = require('node:assert/strict');
const graph = require('../src/axiom_marty_dashboard/axiom_marty_dashboard/graph.js');
const topic = (name, publishers, subscribers, infrastructure = false) =>
  ({name, types: ['std_msgs/msg/String'], publishers, subscribers, infrastructure});
const source = {nodes: ['/driver', '/consumer', '/other', '/idle'], topics: [
  topic('/sensor/imu', ['/driver'], ['/consumer', '/other']),
  topic('/sensor/sample', ['/driver'], ['/consumer']),
  topic('/sensor/missing_range', [], ['/consumer']),
  topic('/sensor/missing_thermal', [], ['/consumer']),
  topic('/rosout', ['/driver'], [], true),
  topic('/unused', ['/driver'], []),
]};
const data = graph.model(source);
assert.equal(new Set(data.vertices.map(v => v.id)).size, data.vertices.length);
assert.equal(data.vertices.filter(v => v.kind === 'node').length, 4,
  'A running node with no subscriptions must still be visible');
assert.equal(data.links.find(e => e.source.includes('/driver') && e.target.includes('/consumer')).topics.length, 2);
assert.equal(data.vertices.filter(v => v.waiting).length, 1,
  'Waiting inputs to the same subscriber are grouped without inventing a publisher');
assert.equal(data.vertices.find(v => v.waiting).topics.length, 2);
assert.equal(data.topics.length, 4);
assert.equal(graph.model(source, {scope: 'application'}).topics.length, 5);
assert.equal(graph.model(source, {scope: 'all'}).topics.length, 6);
assert.equal(graph.model(source, {query: 'missing_range'}).topics.length, 1);
const echo = {...source, nodes: [...source.nodes, '/_ros2cli_echo'], topics: [
  topic('/sensor/imu', ['/driver'], ['/_ros2cli_echo']),
]};
assert(graph.model(echo).vertices.some(v => v.name === '/_ros2cli_echo'),
  'Anonymous console subscribers must appear on the live graph');
const cyclic = graph.model({nodes: ['/a', '/b'], topics: [
  topic('/a_to_b', ['/a'], ['/b']), topic('/b_to_a', ['/b'], ['/a']), topic('/self', ['/a'], ['/a']),
]});
for (const model of [data, cyclic, graph.model({nodes: [], topics: []})]) {
  const placed = graph.layout(model);
  assert(Number.isFinite(placed.width) && Number.isFinite(placed.height));
  assert.equal(placed.positions.size, model.vertices.length);
  for (const p of placed.positions.values()) {
    assert(p.x >= 0 && p.y >= 0 && p.x + p.width <= placed.width && p.y + p.height <= placed.height);
  }
}
const gone = graph.model({nodes: ['/driver'], topics: [topic('/sensor/imu', ['/driver'], [])]});
assert(!gone.links.some(e => e.target.includes('/consumer')),
  'Removed consumers cannot leave stale arrows');
console.log('Graph fan-out, waiting inputs, filters, console consumers, cycles and removal passed');
