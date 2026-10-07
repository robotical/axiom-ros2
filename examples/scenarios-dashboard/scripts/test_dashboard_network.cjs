// Exercise the dashboard's actual poll function with deterministic network failures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname,
  '../src/axiom_marty_dashboard/axiom_marty_dashboard/dashboard.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const poll = script.slice(script.indexOf('async function poll()'), script.indexOf("showView('scenarios');poll();"));
let clock = 100, failing = false;
const fresh = {boards:[{namespace:'/axiom',connected:true}],connections:{marty:{connected:true}},commands:[],graph:{available:true,nodes:['/axiom/axiom_bridge_node'],topics:[],services:[]}};
const fields = {}, renders = [];
const context = vm.createContext({
  performance: {now: () => clock},
  AbortSignal: {timeout: () => undefined},
  setTimeout: () => {},
  fetch: async () => {
    if (failing) throw new TypeError('Failed to fetch');
    return {ok: true, json: async () => fresh};
  },
  text: (id, value) => { fields[id] = value; },
  $: id => fields[id] || (fields[id] = {}),
  record: state => renders.push(state),
});
vm.runInContext(`
  let payload = null, busy = false, lastSuccess = -Infinity;
  function render(s) { payload = s; record(s); }
  ${poll}
`, context);

(async () => {
  await vm.runInContext('poll()', context);
  assert.equal(renders.length, 1);

  failing = true;
  clock = 350;
  await vm.runInContext('poll()', context);
  assert.equal(renders.length, 1, 'A single missed poll must not redraw devices as disconnected');
  assert.equal(fields.notice, 'Dashboard reconnecting…');

  clock = 2000;
  await vm.runInContext('poll()', context);
  const unavailable = renders.at(-1);
  assert.equal(unavailable.graph.available, false, 'A sustained outage invalidates ROS state');
  assert.deepEqual(Array.from(unavailable.boards), [], 'A sustained outage clears board status');
  assert.deepEqual(Array.from(unavailable.graph.nodes), [], 'A sustained outage clears the graph');
  assert.equal(Object.keys(unavailable.connections).length, 0,
    'A sustained outage must clear previously connected driver badges');

  failing = false;
  clock = 2300;
  await vm.runInContext('poll()', context);
  assert.equal(renders.at(-1).boards[0].connected, true);
  assert.equal(vm.runInContext('busy', context), false);
  console.log('Dashboard transient failure, sustained outage, and recovery checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
