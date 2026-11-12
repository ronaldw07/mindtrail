  // ---------- project page parts: composer, chat list, instructions/context/memory ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.

  const PIN_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round"><path d="M12 17v5"/>' +
    '<path d="M9 3h6l1 5 3 2-1 3H6l-1-3 3-2 1-5Z"/></svg>';
  const SEND_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" ' +
    'stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
  const memoryRefreshing = new Set();

  // Typing here and pressing Enter starts a chat in the project and sends
  // the message, the same as the main composer would.
  function projectComposer(id, name) {
    const box = tEl('div', 'proj-composer');
    const field = document.createElement('textarea');
    field.rows = 2;
    field.placeholder = 'New chat in ' + name;
    field.setAttribute('aria-label', 'New chat in ' + name);
    const bar = tEl('div', 'proj-composer-bar');
    const add = tEl('button', 'icon-btn', '+');
    add.type = 'button';
    add.title = 'Add a file to this project';
    add.setAttribute('aria-label', 'Add a file to this project');
    add.onclick = () => uploadInto(id);
    const go = tEl('button', 'proj-send');
    go.type = 'button';
    go.innerHTML = SEND_SVG;
    go.setAttribute('aria-label', 'Start chat');
    go.disabled = true;
    const start = () => {
      const text = field.value.trim();
      if (!text) return;
      newChatInProject(id, name);
      input.value = text;
      $('form').requestSubmit();
    };
    field.oninput = () => { go.disabled = !field.value.trim(); };
    field.onkeydown = e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); start(); }
    };
    go.onclick = start;
    bar.append(add, tEl('span', 'spacer'), go);
    box.append(field, bar);
    box.onclick = e => { if (e.target === box) field.focus(); };
    return box;
  }

  function projectChatRow(c) {
    const row = tEl('div', 'proj-chat');
    row.dataset.chat = c.id;
    if (c.pinned) {
      const pin = tEl('span', 'pin');
      pin.innerHTML = PIN_SVG;
      row.appendChild(pin);
    }
    row.appendChild(tEl('span', 'proj-chat-title', c.title));
    row.appendChild(tEl('span', 'when', relTime(c.updated_at)));
    const more = tEl('button', 'menu-btn', '⋯');
    more.title = 'Chat options';
    more.setAttribute('aria-label', 'Chat options');
    more.onclick = e => { e.stopPropagation(); openChatMenu(e, c); };
    row.appendChild(more);
    onRightClick(row, e => openChatMenu(e, c));
    makeClickable(row, () => { showChatView(); openConversation(c.id); });
    return row;
  }

  // Pinned chats get their own group above Recents, like the sidebar.
  function projectChatList(conversations) {
    const wrap = tEl('div', 'proj-chats');
    if (!conversations.length) {
      wrap.appendChild(tEl('div', 'muted proj-empty',
        'No chats yet. Start one above, or move a chat here from its ⋯ menu.'));
      return wrap;
    }
    const pinned = conversations.filter(c => c.pinned);
    const rest = conversations.filter(c => !c.pinned);
    if (pinned.length) {
      wrap.appendChild(tEl('div', 'proj-group', 'Pinned'));
      pinned.forEach(c => wrap.appendChild(projectChatRow(c)));
    }
    if (rest.length) {
      wrap.appendChild(tEl('div', 'proj-group', 'Recents'));
      rest.forEach(c => wrap.appendChild(projectChatRow(c)));
    }
    return wrap;
  }

  // One row per setting; clicking it opens its editor underneath, and
  // only one is open at a time.
  function propRow(list, icon, label, action, buildPanel) {
    const item = tEl('div', 'prop');
    const head = tEl('div', 'prop-head');
    const ic = tEl('span', 'prop-icon');
    ic.innerHTML = icon;
    const act = tEl('span', 'prop-action', action);
    head.append(ic, tEl('span', 'prop-label', label), act);
    head.setAttribute('aria-expanded', 'false');
    const panel = tEl('div', 'prop-panel');
    makeClickable(head, () => {
      const opening = !item.classList.contains('open');
      list.querySelectorAll('.prop.open').forEach(o => {
        o.classList.remove('open');
        o.querySelector('.prop-head').setAttribute('aria-expanded', 'false');
      });
      if (!opening) return;
      if (!panel.childElementCount) buildPanel(panel);
      item.classList.add('open');
      head.setAttribute('aria-expanded', 'true');
    });
    item.append(head, panel);
    item.setAction = text => { act.textContent = text; };
    item.resetPanel = () => { panel.replaceChildren(); if (item.classList.contains('open')) buildPanel(panel); };
    return item;
  }

  const ICON = {
    instructions: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 ' +
      '2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 17h5"/></svg>',
    context: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="12" ' +
      'height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h2"/></svg>',
    memory: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.9.8 ' +
      '3 3 0 0 0-1.5 5.3A3 3 0 0 0 7 16a3 3 0 0 0 5 2"/><path d="M12 5a3 3 0 1 1 5.9.8 3 3 0 0 1 1.5 ' +
      '5.3A3 3 0 0 1 17 16a3 3 0 0 1-5 2"/><path d="M12 5v13"/></svg>',
  };

  // A textarea with Save that lights up only when something changed.
  function savedTextEditor(panel, value, placeholder, onSave) {
    const box = document.createElement('textarea');
    box.className = 'instructions-box';
    box.value = value;
    box.placeholder = placeholder;
    const row = tEl('div', 'prop-buttons');
    const save = tEl('button', 'btn-primary', 'Save');
    save.disabled = true;
    box.oninput = () => { save.disabled = box.value.trim() === value.trim(); };
    save.onclick = async () => {
      save.disabled = true;
      if (await onSave(box.value)) value = box.value;
      else save.disabled = false;
    };
    row.appendChild(save);
    panel.append(box, row);
    // Sized to its text so a memory reads in full without scrolling.
    requestAnimationFrame(() => { box.style.height = Math.max(120, box.scrollHeight + 2) + 'px'; });
    box.focus();
    return row;
  }

  function projectProps(id, data) {
    const list = tEl('div', 'proj-props');
    const patch = async body => {
      const res = await jsonSend('/api/projects/' + id, body, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return false; }
      return true;
    };

    let instructions = data.instructions || '';
    const instr = propRow(list, ICON.instructions, 'Instructions', instructions ? 'Edit' : 'Add', panel => {
      panel.appendChild(tEl('div', 'prop-hint', 'Followed in every chat in this project.'));
      savedTextEditor(panel, instructions, 'e.g. Keep answers short. I’m aiming for PM roles.',
        async text => {
          if (!(await patch({instructions: text}))) return false;
          instructions = text.trim();
          instr.setAction(instructions ? 'Edit' : 'Add');
          toast('Instructions saved');
          return true;
        });
    });

    const files = data.files || [];
    const ctx = propRow(list, ICON.context, 'Context', files.length ? String(files.length) : 'Add', panel => {
      panel.appendChild(tEl('div', 'prop-hint', 'Files every chat here can draw on.'));
      files.forEach(f => {
        const chip = tEl('span', 'file-chip', f.name);
        makeClickable(chip, () => { showChatView(); openConversation(f.conversation_id); });
        panel.appendChild(chip);
      });
      const row = tEl('div', 'prop-buttons');
      const up = tEl('button', 'btn-ghost', '+ Add file');
      up.onclick = () => uploadInto(id);
      row.appendChild(up);
      panel.appendChild(row);
    });

    let memory = data.memory || '';
    const mem = propRow(list, ICON.memory, 'Memory', memory ? 'View' : '—', panel => {
      panel.appendChild(tEl('div', 'prop-hint', memoryRefreshing.has(id)
        ? 'Updating from recent chats…'
        : 'What it knows from this project’s chats and files. Edit it, and every new chat here starts from it.'));
      const row = savedTextEditor(panel, memory, 'Nothing yet — it fills in once you’ve chatted here.',
        async text => {
          if (!(await patch({memory: text}))) return false;
          memory = text.trim();
          toast('Memory saved');
          return true;
        });
      const update = tEl('button', 'btn-ghost', 'Update now');
      update.disabled = memoryRefreshing.has(id) || !data.entry_count;
      update.onclick = () => refreshMemory(id, mem, true, text => { memory = text; });
      row.appendChild(update);
    });
    if (data.memory_stale) refreshMemory(id, mem, false, text => { memory = text; });

    list.append(instr, ctx, mem);
    return list;
  }

  // Runs in the background so opening a project never waits on the model.
  async function refreshMemory(id, row, announce, onDone) {
    if (memoryRefreshing.has(id)) return;
    memoryRefreshing.add(id);
    row.setAction('Updating…');
    row.resetPanel();
    const res = await jsonSend('/api/projects/' + id + '/memory', {});
    memoryRefreshing.delete(id);
    if (res.error) {
      row.setAction('View');
      if (announce) toast('Could not update memory: ' + res.error, {error: true});
    } else {
      onDone(res.memory);
      row.setAction('View');
      if (announce) toast('Memory updated');
    }
    row.resetPanel();
  }
