/* Command help is local to the guide. Opening it never sends a ROS command. */
(() => {
  const dialog = document.getElementById('command-dialog');
  const title = document.getElementById('command-info-title');
  const description = document.getElementById('command-info-description');
  const command = document.getElementById('command-info-command');
  const argumentsList = document.getElementById('command-info-arguments');
  const note = document.getElementById('command-info-note');

  function open(recipe) {
    title.textContent = recipe.title;
    description.textContent = recipe.help.description;
    command.textContent = recipe.command || '';
    command.hidden = !recipe.command;
    document.getElementById('command-info-section').textContent = recipe.help.section || 'Arguments';
    argumentsList.replaceChildren(...recipe.help.arguments.flatMap(argument => {
      const name = document.createElement('dt');
      const detail = document.createElement('dd');
      name.textContent = argument.name;
      detail.textContent = argument.description;
      return [name, detail];
    }));
    note.textContent = recipe.note || '';
    note.hidden = !recipe.note;
    dialog.showModal();
    dialog.scrollTop = 0;
  }

  document.getElementById('command-info-close').onclick = () => dialog.close();
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });

  window.CommandInfo = {
    inspection(kind, name, value, retained = false) {
      const argument = (name, description) => ({name, description});
      const help = {arguments: []};
      const recipe = {command: value, help};
      if (kind === 'node') {
        recipe.title = 'Node details';
        help.description = 'Shows this running node’s publishers, subscriptions, services and ' +
          'actions without changing its state.';
        help.arguments.push(argument(name, 'Fully qualified node name, including its namespace.'));
      } else if (kind === 'topic') {
        recipe.title = 'Topic details';
        help.description = 'Inspects the topic’s discovered publishers, subscribers and QoS. ' +
          'It does not subscribe to messages or start any publisher.';
        help.arguments.push(argument(name, 'Topic name to inspect.'),
          argument('--verbose', 'Includes endpoint node names, message types and QoS settings.'));
      } else {
        recipe.title = 'Topic messages';
        help.description = 'Creates a ROS subscription and prints messages until Ctrl+C. ' +
          'It does not start the publisher or request firmware acquisition. Replace BUS and ' +
          'ADDRESS placeholders with an actual device identity from /axiom/devices.';
        help.arguments.push(argument(name, 'Topic name to subscribe to.'),
          argument('--qos-reliability best_effort', 'Matches best-effort sensor publishers as well ' +
            'as reliable publishers. Messages may be dropped rather than retried.'));
        if (retained) help.arguments.push(argument('--qos-durability transient_local',
          'Also requests retained messages from a compatible transient-local publisher.'));
      }
      return recipe;
    },
    button(recipe) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'command-info';
      button.textContent = 'i';
      button.title = recipe.help.section === 'Details' ? 'About this interface' : 'About this command';
      button.setAttribute('aria-label', 'About ' + recipe.title);
      button.setAttribute('aria-haspopup', 'dialog');
      button.onclick = () => open(recipe);
      return button;
    },
  };
})();
