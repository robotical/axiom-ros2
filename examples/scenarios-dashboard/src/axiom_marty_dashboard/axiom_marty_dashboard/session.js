/* The optional workstation reset is the only lifecycle action in the guide. */
(function (root) {
  'use strict';
  const button = document.getElementById('session-reset');
  const status = document.getElementById('session-status');
  let session = {}, working = false, pending = null, error = '';
  function update(value) {
    session = value || {};
    if (pending && session.request_id === pending && session.phase !== 'resetting') pending = null;
    button.hidden = !session.enabled;
    button.disabled = working || !!pending || session.phase === 'resetting';
    if (working || pending || session.phase === 'resetting') {
      status.textContent = 'Restarting workspace…';
    } else if (session.phase === 'error') {
      status.textContent = 'Reset failed · ' + session.error;
    } else if (error) {
      status.textContent = error;
    } else if (session.completed_at && Date.now() / 1000 - session.completed_at < 30) {
      status.textContent = 'Fresh session · start nodes from the console.';
    } else status.textContent = '';
  }
  button.onclick = async () => {
    if (button.disabled || !session.enabled) return;
    working = true; error = ''; update(session);
    try {
      const response = await fetch('/api/session/reset', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': session.token},
        body: '{}', signal: AbortSignal.timeout(5000),
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.message || 'Reset unavailable');
      pending = result.id;
    } catch (failure) {
      error = 'Reset request not confirmed · ' + failure.message;
    } finally { working = false; update(session); }
  };
  root.SessionReset = {update};
})(window);
