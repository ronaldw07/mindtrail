  // ---------- journey: the assistant dock ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Pinned to the bottom right of a journey. Each journey has its own saved
  // chats; the model only proposes changes, and nothing happens to the
  // timeline until Accept. Proposals can be edited before accepting.

  const DOCK_EXAMPLES = ['Plan my next term', 'Make a backup path', 'What am I behind on?'];
  // Which fields of a proposal can be edited, by proposal type.
  const DOCK_EDITABLE = {
    add_step: [['title', 'Step'], ['detail', 'Why / details']],
    set_note: [['note', 'Note']],
    create_track: [['name', 'Path name']],
    duplicate_track: [['name', 'New path name']],
    rename_track: [['name', 'New name']],
  };
  let dockChat = null;      // the open chat, kept across timeline redraws
  let dockDraft = '';
  let dockBusy = false;

  const dockChatFor = () => prefs.get('journeyDockChat', {})[journeyData.project_id] || '';
  function rememberDockChat(id) {
    prefs.set('journeyDockChat', {...prefs.get('journeyDockChat', {}), [journeyData.project_id]: id || ''});
  }

  // One dock for the whole app, mounted outside #journey-view. The journey
  // page redraws itself on every edit; if the dock were part of that
  // redraw it would replay its open animation (a flicker) and lose its
  // scroll position each time.
  let dockRoot = null;
  let dockProject = null;   // the journey the dock is drawn for

  function showJourneyDock() {
    if (!dockRoot) dockRoot = buildJourneyDock();
    if (dockProject !== journeyData.project_id) {
      dockProject = journeyData.project_id;
      if (dockChat && dockChat.project_id !== dockProject) dockChat = null;
      drawDock(dockRoot);
      if (dockRoot.classList.contains('open')) loadDockChat(dockRoot);
    }
    dockRoot.hidden = false;
  }

  function hideJourneyDock() {
    if (dockRoot) dockRoot.hidden = true;
  }

  function buildJourneyDock() {
    const root = tEl('div', 'jdock' + (prefs.get('journeyDockOpen', false) ? ' open' : ''));
    const launch = tEl('button', 'jdock-launch');
    launch.type = 'button';
    launch.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 ' +
      '2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span>Assistant</span>';
    launch.setAttribute('aria-label', 'Open the assistant');
    launch.onclick = () => setDockOpen(root, true);

    const panel = tEl('div', 'jdock-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Journey assistant');
    root.append(launch, panel);
    root.hidden = true;
    document.body.appendChild(root);
    return root;
  }

  // The panel only animates when you open it, never on a redraw.
  function setDockOpen(root, open) {
    prefs.set('journeyDockOpen', open);
    root.classList.toggle('open', open);
    if (!open) return;
    if (!reducedMotion()) {
      root.querySelector('.jdock-panel').animate(
        [{opacity: 0, transform: 'scale(0.96) translateY(6px)'}, {opacity: 1, transform: 'none'}],
        {duration: 200, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
    }
    const log = root.querySelector('.jdock-log');
    if (log) log.scrollTop = log.scrollHeight;
    loadDockChat(root);
    setTimeout(() => { const f = root.querySelector('.jdock-input'); if (f) f.focus(); });
  }

  // Reopens the chat last used in this journey (or its newest one).
  async function loadDockChat(root) {
    if (dockChat) return;
    const list = await api('/api/journey/chats');
    const chats = list.chats || [];
    const id = chats.some(c => c.id === dockChatFor()) ? dockChatFor() : (chats[0] || {}).id;
    if (!id) return;
    const res = await api('/api/journey/chats/' + id);
    if (res.chat) { dockChat = res.chat; drawDock(root); }
  }

  function drawDock(root) {
    const panel = root.querySelector('.jdock-panel');
    panel.replaceChildren(dockHeader(root), dockLog(root), dockForm(root));
    const log = panel.querySelector('.jdock-log');
    log.scrollTop = log.scrollHeight;
  }

  function dockHeader(root) {
    const head = tEl('div', 'jdock-head');
    const pick = tEl('button', 'jdock-pick');
    pick.type = 'button';
    pick.appendChild(tEl('span', 'jdock-title', dockChat ? dockChat.title : 'New chat'));
    pick.appendChild(tEl('span', 'jdock-caret', '▾'));
    pick.title = 'Switch chat';
    pick.onclick = () => openDockMenu(root, pick);
    const fresh = tEl('button', 'jdock-icon', '+');
    fresh.type = 'button';
    fresh.title = 'New chat';
    fresh.setAttribute('aria-label', 'New chat');
    fresh.onclick = () => startDockChat(root);
    const hide = tEl('button', 'jdock-icon', '–');
    hide.type = 'button';
    hide.title = 'Minimize';
    hide.setAttribute('aria-label', 'Minimize the assistant');
    hide.onclick = () => setDockOpen(root, false);
    head.append(pick, fresh, hide);
    return head;
  }

  function startDockChat(root) {
    dockChat = null;
    rememberDockChat('');
    drawDock(root);
    root.querySelector('.jdock-input').focus();
  }

  async function openDockMenu(root, button) {
    const chats = (await api('/api/journey/chats')).chats || [];
    const items = chats.map(c => ({
      label: (dockChat && c.id === dockChat.id ? '✓ ' : '') + c.title,
      run: async () => {
        const res = await api('/api/journey/chats/' + c.id);
        if (res.error) { toast(res.error, {error: true}); return; }
        dockChat = res.chat;
        rememberDockChat(c.id);
        drawDock(root);
      },
    }));
    if (items.length) items.push({divider: true});
    items.push({label: 'New chat', run: () => startDockChat(root)});
    if (dockChat) {
      items.push({label: 'Delete this chat', danger: true, run: async () => {
        const ok = await askConfirm('Delete chat', '"' + dockChat.title + '" will be removed.', 'Delete');
        if (!ok) return;
        await api('/api/journey/chats/' + dockChat.id, {method: 'DELETE'});
        startDockChat(root);
        toast('Chat deleted');
      }});
    }
    showMenuFrom(button, items);
  }

  function dockLog(root) {
    const log = tEl('div', 'jdock-log');
    const messages = dockChat ? dockChat.messages : [];
    if (!messages.length && !dockBusy) {
      const empty = tEl('div', 'jdock-empty');
      empty.appendChild(tEl('div', 'jdock-empty-title', 'Change ' + journeyData.name + ' by asking'));
      empty.appendChild(tEl('div', 'jdock-empty-sub',
        'It proposes changes; nothing moves until you accept. You can edit a proposal first.'));
      const chips = tEl('div', 'jdock-examples');
      DOCK_EXAMPLES.forEach(text => {
        const chip = tEl('button', 'jdock-example', text);
        chip.type = 'button';
        chip.onclick = () => { dockDraft = text; drawDock(root); sendDock(root); };
        chips.appendChild(chip);
      });
      empty.appendChild(chips);
      log.appendChild(empty);
    }
    messages.forEach((m, mi) => {
      const bubble = tEl('div', 'rc-msg ' + m.role);
      // renderMarkdown escapes first, so model text can't inject HTML.
      if (m.role === 'assistant') bubble.innerHTML = renderMarkdown(m.content);
      else bubble.textContent = m.content;
      log.appendChild(bubble);
      (m.actions || []).forEach((a, ai) => log.appendChild(dockAction(root, a, mi, ai)));
    });
    if (dockBusy) log.appendChild(tEl('div', 'rc-msg assistant jdock-thinking', 'Thinking…'));
    return log;
  }

  async function saveDockAction(root, mi, ai, body) {
    const res = await jsonSend('/api/journey/chats/' + dockChat.id + '/action', {message: mi, action: ai, ...body});
    if (res.error) { toast(res.error, {error: true}); return false; }
    dockChat = res.chat;
    drawDock(root);
    return true;
  }

  function dockAction(root, action, mi, ai) {
    const card = tEl('div', 'rc-action' + (action.resolved ? ' resolved' : ''));
    card.appendChild(tEl('div', 'rc-action-label', action.label));
    if (action.resolved) {
      card.appendChild(tEl('div', 'rc-action-resolved-note',
        action.resolved === 'accepted' ? '✓ Applied' : '✗ Dismissed'));
      return card;
    }
    const buttons = tEl('div', 'rc-action-buttons');
    const accept = tEl('button', 'rc-accept', 'Accept');
    accept.onclick = async () => {
      accept.disabled = true;
      const res = await jsonSend('/api/journey/apply', {action});
      if (res.error) { accept.disabled = false; toast(res.error, {error: true}); return; }
      await saveDockAction(root, mi, ai, {resolved: 'accepted'});
      await renderJourney(res.changed);
    };
    buttons.appendChild(accept);
    if (DOCK_EDITABLE[action.type]) {
      const edit = tEl('button', '', 'Edit');
      edit.onclick = () => card.replaceWith(dockActionEditor(root, action, mi, ai));
      buttons.appendChild(edit);
    }
    const dismiss = tEl('button', 'rc-reject', 'Dismiss');
    dismiss.onclick = () => saveDockAction(root, mi, ai, {resolved: 'rejected'});
    buttons.appendChild(dismiss);
    card.appendChild(buttons);
    onRightClick(card, e => showMenu(e, [...buttons.children].map(b => ({label: b.textContent, run: () => b.click()}))));
    return card;
  }

  function dockActionEditor(root, action, mi, ai) {
    const form = tEl('form', 'rc-action jdock-edit');
    const inputs = DOCK_EDITABLE[action.type].map(([key, label]) => {
      const field = key === 'detail' || key === 'note' ? tEl('textarea') : tEl('input');
      field.value = action[key] || '';
      field.setAttribute('aria-label', label);
      field.placeholder = label;
      form.appendChild(field);
      return [key, field];
    });
    const buttons = tEl('div', 'rc-action-buttons');
    const save = tEl('button', 'rc-accept', 'Save');
    save.type = 'submit';
    const cancel = tEl('button', '', 'Cancel');
    cancel.type = 'button';
    cancel.onclick = () => drawDock(root);
    buttons.append(save, cancel);
    form.appendChild(buttons);
    form.onsubmit = async e => {
      e.preventDefault();
      save.disabled = true;
      const fields = Object.fromEntries(inputs.map(([k, f]) => [k, f.value.trim()]));
      if (!(await saveDockAction(root, mi, ai, {fields}))) save.disabled = false;
    };
    setTimeout(() => inputs[0][1].focus());
    return form;
  }

  function dockForm(root) {
    const form = tEl('form', 'jdock-form');
    const field = tEl('textarea', 'jdock-input');
    field.rows = 1;
    field.placeholder = 'Ask or change something…';
    field.setAttribute('aria-label', 'Message the assistant');
    field.value = dockDraft;
    field.disabled = dockBusy;
    const send = tEl('button', 'proj-send');
    send.type = 'submit';
    send.innerHTML = SEND_SVG;
    send.setAttribute('aria-label', 'Send');
    send.disabled = dockBusy || !dockDraft.trim();
    field.oninput = () => {
      dockDraft = field.value;
      send.disabled = !field.value.trim();
      field.style.height = 'auto';
      field.style.height = Math.min(field.scrollHeight, 140) + 'px';
    };
    field.onkeydown = e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendDock(root); }
    };
    form.onsubmit = e => { e.preventDefault(); sendDock(root); };
    form.append(field, send);
    return form;
  }

  async function sendDock(root) {
    const message = dockDraft.trim();
    if (!message || dockBusy) return;
    const pid = journeyData.project_id;
    dockBusy = true;
    dockDraft = '';
    const before = dockChat;
    dockChat = {...(dockChat || {title: 'New chat', project_id: pid}),
                messages: [...(dockChat ? dockChat.messages : []), {role: 'user', content: message}]};
    drawDock(root);
    const res = await jsonSend('/api/journey/chat', {message, chat_id: before ? before.id : ''});
    dockBusy = false;
    if (res.error) {
      dockChat = before;
      dockDraft = message;
      toast(res.error, {error: true});
    } else {
      dockChat = res.chat;
      rememberDockChat(res.chat.id);
    }
    if (dockProject === pid) {
      drawDock(root);
      root.querySelector('.jdock-input').focus();
    }
  }
