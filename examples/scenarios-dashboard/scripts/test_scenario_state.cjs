const assert = require('node:assert/strict');
const {observe, isPresent} = require('../src/axiom_marty_dashboard/axiom_marty_dashboard/scenario-state.js');
const driver = '/axiom/front/axiom_bridge_node';
const state = {
  graph: {available: true, nodes: [driver], topics: [], services: []},
  boards: [{namespace: '/axiom/front', available: true, connected: true}],
};
const check = {kind: 'topic', topic: '/axiom/front/range', console: true, terminal: 3};
state.graph.topics = [{name: check.topic, types: ['sensor_msgs/msg/Range'],
  publishers: [], subscribers: ['/_ros2cli_123']}];
assert.equal(observe(check, state).tone, 'pending', 'A lingering subscriber cannot prove publishing');
assert.match(observe(check, state).text, /0 publishers/);
assert.equal(isPresent({kind: 'topic', name: check.topic}, state), false);
state.graph.topics[0].publishers = [driver];
assert.equal(observe(check, state).tone, 'observed');
assert.match(observe(check, state).detail, /Endpoints only/);
assert.equal(observe({kind: 'acquisition', namespace: '/axiom/front', terminal: 2}, state).tone,
  'pending', 'Connected plus publisher endpoints cannot prove acquisition');
assert.match(observe({kind: 'acquisition', namespace: '/axiom/front', terminal: 2}, state).detail,
  /cannot verify acquisition/);
assert.equal(observe({kind: 'connection', namespace: '/axiom/rear', connected: true}, state).tone,
  'pending', 'Another board being connected cannot satisfy this board');
assert.equal(observe({kind: 'driver', nodes: [driver, '/axiom/rear/axiom_bridge_node']}, state).tone,
  'pending');
const range = {kind: 'range', namespace: '/axiom/front', present: false};
assert.equal(observe(range, state).tone, 'pending');
state.graph.topics[0].publishers = [];
assert.equal(observe(range, state).tone, 'observed', 'Unplug checks publishers, not topic names');
state.boards[0].available = false;
state.boards[0].state = 'status unavailable';
assert.equal(observe(range, state).tone, 'pending', 'Unknown board state cannot verify hot unplug');
assert.equal(observe({kind: 'connection', namespace: '/axiom/front', connected: true}, state).tone,
  'pending', 'Stale connection data cannot verify connection');
state.graph.available = false;
assert.equal(observe(check, state).text, 'ROS state unavailable');
assert.equal(isPresent({kind: 'node', name: driver}, state), false);
console.log('Scenario evidence: endpoint limits, unplugging, namespace isolation, stale status and outages passed');
