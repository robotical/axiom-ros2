const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fields = {'session-reset': {}, 'session-status': {}};
let posts = 0, fails = false;
const context = vm.createContext({
  window: {}, document: {getElementById: id => fields[id]}, Date,
  AbortSignal: {timeout: () => undefined},
  fetch: async (url, options) => {
    posts++;
    assert.equal(url, '/api/session/reset');
    assert.equal(options.headers['X-Session-Token'], 'token');
    assert.equal(options.body, '{}');
    if (fails) throw Error('Disconnected');
    return {ok: true, json: async () => ({id: 'new-session'})};
  },
});
vm.runInContext(fs.readFileSync('src/axiom_marty_dashboard/axiom_marty_dashboard/session.js', 'utf8'), context);
const ui = context.window.SessionReset, button = fields['session-reset'];
ui.update(undefined);
assert.equal(button.hidden, true, 'Native read-only guide must have no reset action');
const ready = {enabled: true, phase: 'ready', token: 'token'};
(async () => {
  ui.update(ready);
  await button.onclick();
  assert.equal(button.disabled, true);
  await button.onclick();
  assert.equal(posts, 1, 'Repeated clicks cannot queue another reset');
  ui.update({...ready, request_id: 'new-session', phase: 'resetting'});
  assert.equal(button.disabled, true);
  ui.update({...ready, request_id: 'new-session', completed_at: Date.now()/1000});
  assert.equal(button.disabled, false);
  assert.match(fields['session-status'].textContent, /Fresh session/);
  fails = true;
  await button.onclick();
  assert.match(fields['session-status'].textContent, /not confirmed/);
  assert.equal(button.disabled, false);
  console.log('Reset visibility, duplicate-click prevention, completion and network failure passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
