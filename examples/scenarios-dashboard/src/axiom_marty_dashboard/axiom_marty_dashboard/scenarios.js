/* Guide navigation is manual and never executes commands or marks them complete. */
(() => {
  const picker = document.getElementById('scenario-picker');
  const content = document.getElementById('scenario-content');
  let items = [], signature = '', commandRow, state = {}, context = '', active = 0, expanded = false;
  let sessionToken = '', evidence = [];

  function element(tag, className, value = '') {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = value;
    return node;
  }
  const scenario = () => items.find(item => item.id === picker.value);

  function move(index) {
    const current = scenario();
    active = Math.max(0, Math.min(index, current.steps.length + current.cleanup.length - 1));
    draw();
    content.querySelector('[aria-current="step"]')?.focus({preventScroll: true});
    content.querySelector('.scenario-step.active')?.scrollIntoView({block: 'nearest'});
  }

  function updateEvidence() {
    for (const row of evidence) {
      const observed = ScenarioState.observe(row.step.check || {kind: 'console'}, state);
      const flowState = (row.step.flow || []).map(item => ScenarioState.isPresent(item, state));
      const next = JSON.stringify([observed, flowState]);
      if (row.signature === next) continue;
      row.signature = next;
      row.value.textContent = observed.text;
      row.value.className = 'scenario-observed ' + observed.tone;
      row.detail.textContent = observed.detail;
      row.flow.querySelectorAll('.scenario-flow-item').forEach((item, i) =>
        item.classList.toggle('present', flowState[i]));
    }
  }

  function steps(rows, offset = 0) {
    const list = element('div', 'scenario-steps');
    rows.forEach((step, index) => {
      const number = offset + index;
      const open = expanded || number === active;
      const row = element('article', 'scenario-step' + (number === active ? ' active' : ''));
      const head = element('div', 'scenario-step-head');
      const toggle = element('button', 'scenario-step-toggle');
      toggle.type = 'button';
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-controls', 'scenario-step-' + number);
      if (number === active) toggle.setAttribute('aria-current', 'step');
      toggle.append(element('span', 'scenario-number', String(number + 1)),
        element('span', 'scenario-step-name', step.title),
        element('span', 'scenario-terminal', step.terminal == null ? 'Hardware' : 'T' + step.terminal));
      toggle.onclick = () => move(number);
      const body = element('div', 'scenario-step-body');
      body.id = 'scenario-step-' + number;
      body.hidden = !open;
      let actions;
      if (step.recipe) {
        const command = commandRow({...step.recipe, note: ''});
        actions = command.querySelector('.command-actions');
        command.querySelector('.command-title').remove();
        command.className = 'scenario-command';
        body.append(command);
      } else {
        actions = element('span', 'command-actions');
        actions.append(CommandInfo.button({
          title: step.title, command: '', help: {section: 'Details',
            description: step.instruction,
            arguments: [{name: 'Expected result', description: step.expected}]},
        }));
        body.append(element('p', 'scenario-instruction', step.instruction));
      }
      actions.hidden = !open;
      head.append(toggle, actions);
      const results = element('dl', 'scenario-results');
      const value = element('dd', 'scenario-observed');
      results.append(element('dt', '', 'Expected'), element('dd', '', step.expected),
        element('dt', '', 'Observed'), value);
      const detail = element('p', 'scenario-evidence');
      const relationship = element('div', 'scenario-relationship');
      const parallel = step.flow?.length > 1 && step.flow.every(item => item.kind === 'node');
      relationship.append(element('span', 'scenario-flow-caption',
        (parallel ? 'Parallel nodes' : 'ROS relationship') + ' · teal = discovered'));
      const flow = element('div', 'scenario-flow');
      for (const [i, item] of (step.flow || []).entries()) {
        if (i) {
          const arrow = element('span', 'scenario-flow-arrow', parallel ? '+' : '→');
          arrow.setAttribute('aria-hidden', 'true');
          flow.append(arrow);
        }
        const box = element('span', 'scenario-flow-item ' + item.kind);
        box.append(element('small', '', item.kind), element('span', '', item.name));
        flow.append(box);
      }
      flow.setAttribute('aria-label', (step.flow || []).map(item => item.name).join(parallel ? ' + ' : ' → '));
      relationship.append(flow);
      body.append(results, detail, relationship);
      row.append(head, body);
      list.append(row);
      if (open) evidence.push({step, value, detail, flow});
    });
    return list;
  }

  function draw() {
    const current = scenario();
    if (!current) return;
    const oldOpen = new Set([...content.querySelectorAll('details[open]')].map(d => d.dataset.section));
    evidence = [];
    const prerequisites = element('div', 'scenario-prerequisites');
    prerequisites.append(element('span', 'scenario-mode', current.mode || 'Manual console'),
      ...(current.prerequisites || []).map(text => element('span', 'scenario-prerequisite', text)));
    const toolbar = element('div', 'scenario-toolbar');
    const previous = element('button', '', '← Previous');
    previous.type = 'button';
    previous.disabled = active === 0;
    previous.onclick = () => move(active - 1);
    const inCleanup = active >= current.steps.length;
    const count = inCleanup ? 'Clean up · ' + (active - current.steps.length + 1) + ' / ' +
      current.cleanup.length : 'Step ' + (active + 1) + ' / ' + current.steps.length;
    const next = element('button', '', active === current.steps.length - 1 ? 'Clean up →' : 'Next →');
    next.type = 'button';
    next.disabled = active === current.steps.length + current.cleanup.length - 1;
    next.onclick = () => move(active + 1);
    const expand = element('button', 'scenario-expand', expanded ? 'Collapse others' : 'Expand all');
    expand.type = 'button';
    expand.setAttribute('aria-pressed', String(expanded));
    expand.onclick = () => {
      expanded = !expanded;
      if (!expanded) content.querySelector('[data-section="cleanup"]').open = false;
      draw();
    };
    toolbar.append(previous, element('span', 'scenario-position', count), next, expand);
    const cleanup = element('details', 'scenario-detail');
    cleanup.dataset.section = 'cleanup';
    cleanup.open = inCleanup || expanded || oldOpen.has('cleanup');
    cleanup.append(element('summary', '', 'Finish & clean up'),
      steps(current.cleanup, current.steps.length));
    const help = element('details', 'scenario-detail');
    help.dataset.section = 'help';
    help.open = oldOpen.has('help');
    const setup = element('div', 'scenario-help');
    setup.append(element('p', '', current.requires),
      element('p', '', 'Run commands in the indicated terminal. Next only changes the guide.'),
      element('p', 'scenario-shortcuts',
        'tmux: Ctrl+b, then arrow · Paste: Ctrl+Shift+V · Stop process: Ctrl+C'),
      element('p', '', 'Use Start from scratch to stop session commands and reopen empty terminals.'));
    if (current.topics?.length) setup.append(element('p', 'source',
      'Discovered: ' + current.topics.join(' · ')));
    help.append(element('summary', '', 'Setup & shortcuts'), setup);
    const troubleshooting = element('details', 'scenario-detail');
    troubleshooting.dataset.section = 'troubleshooting';
    troubleshooting.open = oldOpen.has('troubleshooting');
    const hints = element('ul', 'scenario-hints');
    for (const hint of current.troubleshooting) hints.append(element('li', '', hint));
    troubleshooting.append(element('summary', '', 'Troubleshooting'), hints);
    content.replaceChildren(prerequisites, toolbar, steps(current.steps), cleanup, help, troubleshooting);
    updateEvidence();
  }

  picker.onchange = () => { active = 0; expanded = false; content.replaceChildren(); draw(); };
  window.ScenarioGuide = {
    update(scenarios, rowFactory, snapshot = {}) {
      state = snapshot;
      commandRow = rowFactory;
      const changedContext = context !== snapshot.namespace ||
        (sessionToken && snapshot.session?.token && sessionToken !== snapshot.session.token);
      context = snapshot.namespace;
      sessionToken = snapshot.session?.token || sessionToken;
      const next = JSON.stringify(scenarios || []);
      if (next === signature && !changedContext) { updateEvidence(); return; }
      signature = next;
      items = scenarios || [];
      if (changedContext) { active = 0; expanded = false; content.replaceChildren(); }
      const selected = picker.value;
      picker.replaceChildren(...items.map(item => {
        const option = element('option', '', item.title);
        option.value = item.id;
        return option;
      }));
      picker.value = items.some(item => item.id === selected) ? selected : items[0]?.id || '';
      if (!items.length) content.replaceChildren(element('p', 'empty', 'Waiting for scenarios…'));
      else draw();
    },
  };
})();
