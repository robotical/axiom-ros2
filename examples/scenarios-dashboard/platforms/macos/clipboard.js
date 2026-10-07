// Clipboard and lock-key handling belong to the optional browser transport.
export function attachDesktopInput({client, screen, toggle, panel, area, paste, copy, close, message, caps, document, navigator}) {
  let connected = false, remoteText = '', pendingCopyUntil = 0;
  const editable = target => panel.contains(target);
  const show = value => { panel.hidden = !value; toggle.setAttribute('aria-expanded', String(value)); };
  const note = value => { message.textContent = value; };
  const releaseModifiers = () => {
    for (const [symbol, code] of [[0xffe1, 'ShiftLeft'], [0xffe2, 'ShiftRight'],
      [0xffe3, 'ControlLeft'], [0xffe4, 'ControlRight'], [0xffe9, 'AltLeft'],
      [0xffea, 'AltRight'], [0xffeb, 'MetaLeft'], [0xffec, 'MetaRight']]) {
      client.sendKey(symbol, code, false);
    }
  };
  async function copyRemote() {
    if (!remoteText) {
      show(true); note('Select text in the terminal, or use Copy inside Linux first.');
      return;
    }
    try {
      await navigator.clipboard.writeText(remoteText);
      note('Copied from Linux.');
    } catch {
      show(true); area.value = remoteText; area.focus(); area.select();
      note('Press ⌘C or Ctrl+C to copy the selected text.');
    }
  }
  function pasteRemote(value) {
    if (!connected) { show(true); note('Linux desktop is disconnected.'); return false; }
    if (!value) { show(true); note('Paste command text here first.'); area.focus(); return false; }
    // The installed x11vnc uses legacy Latin-1 clipboard messages. Never truncate
    // characters into a different command if a caller supplies unsupported text.
    if (/[^\u0000-\u00ff]/u.test(value)) {
      show(true); note('This clipboard transport supports Latin-1 text. Use plain command text.');
      area.value = value; return false;
    }
    pendingCopyUntil = 0;
    releaseModifiers();
    remoteText = value; area.value = value;
    client.clipboardPasteFrom(value);
    show(false);
    client.focus();
    // Clipboard transfer precedes the paste key on the same ordered RFB stream.
    // The terminal's Shift+Insert binding explicitly uses CLIPBOARD.
    client.sendKey(0xffe1, 'ShiftLeft', true);
    client.sendKey(0xff63, 'Insert', true);
    client.sendKey(0xff63, 'Insert', false);
    client.sendKey(0xffe1, 'ShiftLeft', false);
    note('Pasted to Linux. Press Enter in the terminal to run the command.');
    return true;
  }
  const onPaste = event => {
    if (editable(event.target)) return;
    const value = event.clipboardData?.getData('text/plain');
    if (value === undefined) return;
    event.preventDefault(); event.stopImmediatePropagation();
    pasteRemote(value);
  };
  const onCopy = event => {
    if (editable(event.target) || !remoteText) return;
    event.clipboardData.setData('text/plain', remoteText);
    event.preventDefault(); note('Copied from Linux.');
  };
  const onKey = event => {
    if (editable(event.target)) return;
    // Caps Lock changes the browser's event.key casing. Keep Linux lock state
    // untouched; noVNC's macOS key-down/key-up toggles otherwise cancel each other.
    if (event.getModifierState) caps.hidden = !event.getModifierState('CapsLock');
    if (event.code === 'CapsLock') {
      event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if (event.type !== 'keydown') return;
    if (event.metaKey && event.code === 'KeyV') {
      // Keep the native paste action so clipboardData is supplied by the user's
      // gesture. There is no background clipboard reading or permission prompt.
      event.stopImmediatePropagation();
      releaseModifiers();
    } else if (event.metaKey && event.code === 'KeyC') {
      event.preventDefault(); event.stopImmediatePropagation();
      pendingCopyUntil = 0; releaseModifiers(); copyRemote();
    } else if (event.ctrlKey && event.shiftKey && event.code === 'KeyC') {
      // Let the terminal perform its normal copy. Mirror that explicit operation
      // only; merely selecting text must not overwrite the Mac clipboard.
      pendingCopyUntil = Date.now() + 1000;
      if (remoteText) copyRemote();
    }
  };
  client.addEventListener('connect', () => {
    connected = true; toggle.disabled = false; note('⌘V: from Mac · Ctrl+Shift+V: Linux clipboard · ⌘C: to Mac');
  });
  client.addEventListener('disconnect', () => {
    connected = false; remoteText = ''; pendingCopyUntil = 0; area.value = '';
    toggle.disabled = true; note('Linux desktop is disconnected.');
  });
  client.addEventListener('clipboard', event => {
    remoteText = event.detail.text;
    area.value = remoteText;
    note('Linux clipboard updated. Ctrl+Shift+V pastes in the terminal.');
    if (Date.now() < pendingCopyUntil) { pendingCopyUntil = 0; copyRemote(); }
  });
  toggle.onclick = () => { show(panel.hidden); if (!panel.hidden) area.focus(); };
  close.onclick = () => { show(false); client.focus(); };
  paste.onclick = () => pasteRemote(area.value);
  copy.onclick = copyRemote;
  document.addEventListener('paste', onPaste, true);
  document.addEventListener('copy', onCopy, true);
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('keyup', onKey, true);
  return () => {
    for (const [name, handler] of [['paste', onPaste], ['copy', onCopy], ['keydown', onKey], ['keyup', onKey]]) {
      document.removeEventListener(name, handler, true);
    }
  };
}
