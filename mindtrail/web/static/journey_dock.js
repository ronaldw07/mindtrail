  // ---------- journey: the assistant dock ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Pinned to the bottom right of a journey. Each journey has its own saved
  // chats; the model only proposes changes, and nothing happens to the
  // timeline until Accept. Proposals can be edited before accepting.

  const DOCK_EXAMPLES = ['Plan my next term', 'Make a backup path', 'What am I behind on?'];
  const DOCK_STEP_EXAMPLES = ['Plan this step', 'What should I do first?', 'Is this doable by then?'];
  const DOCK_HOME_EXAMPLES = ['Start a new journey', 'What should I focus on this week?', 'Sort my journeys into folders'];
  // Which fields of a proposal can be edited, by proposal type.
  const DOCK_EDITABLE = {
    add_step: [['title', 'Step'], ['detail', 'Why / details']],
    set_note: [['note', 'Note']],
    create_track: [['name', 'Path name']],
    duplicate_track: [['name', 'New path name']],
    rename_track: [['name', 'New name']],
    add_daily_goal: [['name', 'Goal']],
    edit_step: [['title', 'Step'], ['detail', 'Why / details']],
    edit_track: [['name', 'Path name'], ['goal', 'What it aims at']],
    edit_journey: [['name', 'Journey name'], ['purpose', 'What it’s for']],
    edit_sub_step: [['title', 'Sub-step'], ['detail', 'How']],
    edit_daily_goal: [['name', 'Goal']],
    create_journey: [['name', 'Journey name'], ['purpose', 'What it’s for']],
    remember: [['fact', 'Fact about you']],
    edit_fact: [['fact', 'Fact about you']],
    set_term_note: [['note', 'Note']],
    set_folder: [['folder', 'Folder']],
  };
  // Proposals that change the journey list, so the sidebar redraws too.
  const DOCK_JOURNEY_LEVEL = ['create_journey', 'set_folder', 'edit_journey', 'delete_journey'];
  // Deletions always wait for Accept; with auto-apply on, everything else
  // is made as soon as the assistant answers.
  const DOCK_ASKS_FIRST = ['delete_step', 'delete_track', 'delete_journey', 'delete_sub_step',
                           'delete_daily_goal', 'forget'];
  // A reply that just says yes to the cards above applies them, rather
  // than going to the model (which would only propose them again).
  const DOCK_CONFIRM = /^(yes|yep|yeah|sure|ok|okay|do it|go ahead|go for it|sounds good|accept|apply|add)( (it|all|them|those|that|these|everything|all of (it|them|those|these)))?( please)?[.!]*$/i;
  const dockAutoApply = () => prefs.get('journeyDockAuto', true);
  const dockUnticked = new Set();   // "chat:message:action:index" of plan sub-steps left out
  const dockPending = m => (m.actions || []).map((a, ai) => [a, ai]).filter(([a]) => !a.resolved);
  let dockChat = null;      // the open chat, kept across timeline redraws
  let dockDraft = '';
  let dockBusy = false;
  let dockTitle = '';       // a name for the next new chat, e.g. "Plan: Long run"
  let dockFiles = [];       // files to send with the next message: {id, name, status: reading|ready|error, text}
  let dockQueued = null;    // a message sent while it was thinking: {message, files}, sent next
  let dockFresh = -1;       // index of a just-arrived message, faded in once
  let dockHint = '';        // guidance for the next message only, sent but not shown
  const dockReady = () => dockFiles.filter(f => f.status === 'ready');
  const DOCK_FILE_TYPES = 'image/*,.pdf,.txt,.md,.csv,.json';
  const CLIP_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49' +
    'l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';

  // The dock talks about the open journey, or on the Journeys page
  // ('home') about every journey at once, with chats of its own.
  let dockScope = 'journey';
  const dockKey = () => dockScope === 'home' ? 'home' : journeyData.project_id;
  const dockQuery = () => dockScope === 'home' ? '?scope=home' : '';
  const dockChatFor = () => prefs.get('journeyDockChat', {})[dockKey()] || '';
  function rememberDockChat(id) {
    prefs.set('journeyDockChat', {...prefs.get('journeyDockChat', {}), [dockKey()]: id || ''});
  }

  // One dock for the whole app, mounted outside #journey-view. The journey
  // page redraws itself on every edit; if the dock were part of that
  // redraw it would replay its open animation (a flicker) and lose its
  // scroll position each time.
  let dockRoot = null;
  let dockProject = null;   // the journey the dock is drawn for
  let dockFocus = null;     // the step page it was drawn on, if any

  function showJourneyDock(scope) {
    if (!dockRoot) dockRoot = buildJourneyDock();
    dockScope = scope === 'home' ? 'home' : 'journey';
    if (dockProject !== dockKey()) {
      dockProject = dockKey();
      dockFocus = journeyFocus;
      if (dockChat && dockChat.project_id !== dockProject) dockChat = null;
      drawDock(dockRoot);
      if (dockRoot.classList.contains('open')) loadDockChat(dockRoot);
    } else if (dockFocus !== journeyFocus && dockScope === 'journey') {
      dockFocus = journeyFocus;   // its empty-state examples follow the open step
      drawDock(dockRoot);
    }
    dockRoot.hidden = false;
  }

  // Open the dock and send a message for you, e.g. from a step's "Plan"
  // button. fresh starts a new chat so a plan doesn't land in an old one.
  function askJourneyAssistant(text, opts) {
    showJourneyDock(opts && opts.scope);
    if (opts && opts.fresh) { dockChat = null; rememberDockChat(''); }
    dockTitle = (opts && opts.title) || '';
    dockHint = (opts && opts.hint) || '';
    if (!dockRoot.classList.contains('open')) setDockOpen(dockRoot, true);
    dockDraft = text;
    drawDock(dockRoot);
    sendDock(dockRoot);
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
    // Drop files anywhere on the panel to attach them.
    panel.ondragover = e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); panel.classList.add('dropping'); } };
    panel.ondragleave = e => { if (!panel.contains(e.relatedTarget)) panel.classList.remove('dropping'); };
    panel.ondrop = e => {
      if (!e.dataTransfer.files.length) return;
      e.preventDefault();
      panel.classList.remove('dropping');
      attachDockFiles(root, e.dataTransfer.files);
    };
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
    const list = await api('/api/journey/chats' + dockQuery());
    const chats = list.chats || [];
    const id = chats.some(c => c.id === dockChatFor()) ? dockChatFor() : (chats[0] || {}).id;
    if (!id) return;
    const res = await api('/api/journey/chats/' + id + dockQuery());
    if (res.chat && !dockChat) { dockChat = res.chat; drawDock(root); }
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
    const chats = (await api('/api/journey/chats' + dockQuery())).chats || [];
    const items = chats.map(c => ({
      label: (dockChat && c.id === dockChat.id ? '✓ ' : '') + c.title,
      run: async () => {
        const res = await api('/api/journey/chats/' + c.id + dockQuery());
        if (res.error) { toast(res.error, {error: true}); return; }
        dockChat = res.chat;
        rememberDockChat(c.id);
        drawDock(root);
      },
    }));
    if (items.length) items.push({divider: true});
    items.push({label: 'New chat', run: () => startDockChat(root)});
    items.push({label: (dockAutoApply() ? '✓ ' : '') + 'Apply changes automatically', run: () => {
      prefs.set('journeyDockAuto', !dockAutoApply());
      toast(dockAutoApply() ? 'Changes now apply as soon as it makes them. Deletions still ask.'
                            : 'Changes now wait for you to accept them.');
      drawDock(root);
    }});
    if (dockChat) {
      items.push({label: 'Delete this chat', danger: true, run: async () => {
        const ok = await askConfirm('Delete chat', '"' + dockChat.title + '" will be removed.', 'Delete');
        if (!ok) return;
        await api('/api/journey/chats/' + dockChat.id + dockQuery(), {method: 'DELETE'});
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
      const home = dockScope === 'home';
      empty.appendChild(tEl('div', 'jdock-empty-title',
        home ? 'Ask about any journey' : 'Change ' + journeyData.name + ' by asking'));
      empty.appendChild(tEl('div', 'jdock-empty-sub', (home
        ? 'Start, rename, file or delete journeys, or change any step, sub-step or daily goal in them. '
        : '') + (dockAutoApply()
          ? 'Ask and it makes the change. Deletions wait for your OK.'
          : 'It proposes changes; nothing moves until you accept. You can edit a proposal first.')));
      const chips = tEl('div', 'jdock-examples');
      (home ? DOCK_HOME_EXAMPLES : journeyFocus ? DOCK_STEP_EXAMPLES : DOCK_EXAMPLES).forEach(text => {
        const chip = tEl('button', 'jdock-example', text);
        chip.type = 'button';
        chip.onclick = () => { dockDraft = text; drawDock(root); sendDock(root); };
        chips.appendChild(chip);
      });
      empty.appendChild(chips);
      log.appendChild(empty);
    }
    messages.forEach((m, mi) => {
      const bubble = tEl('div', 'rc-msg ' + m.role + (mi === dockFresh ? ' jdock-new' : ''));
      // renderMarkdown escapes first, so model text can't inject HTML.
      if (m.role === 'assistant') bubble.innerHTML = renderMarkdown(m.content);
      else bubble.textContent = m.content;
      log.appendChild(bubble);
      (m.actions || []).forEach((a, ai) => log.appendChild(dockAction(root, a, mi, ai)));
      // Only the latest question can be answered; older ones were.
      if (m.ask && mi === messages.length - 1) log.appendChild(dockAsk(root, m.ask));
      const pending = dockPending(m);
      if (pending.length > 1) {
        const all = tEl('button', 'rc-accept jdock-accept-all', 'Accept all ' + pending.length);
        all.type = 'button';
        all.onclick = async () => {
          all.disabled = true;
          const n = await applyDockMany(root, mi, pending.map(([, ai]) => ai));
          if (n) toast('Applied ' + n + ' change' + (n === 1 ? '' : 's'));
          else all.disabled = false;
        };
        log.appendChild(all);
      }
    });
    if (dockBusy) {
      const dots = tEl('div', 'rc-msg assistant jdock-thinking');
      dots.setAttribute('role', 'status');
      dots.setAttribute('aria-label', 'Thinking');
      dots.append(tEl('span'), tEl('span'), tEl('span'));
      log.appendChild(dots);
    }
    if (dockQueued) log.appendChild(tEl('div', 'rc-msg user jdock-queued', dockQueued.saved));
    dockFresh = -1;
    return log;
  }

  // A question from the assistant: tap an answer, or type your own.
  function dockAsk(root, ask) {
    const card = tEl('div', 'jdock-ask');
    card.appendChild(tEl('div', 'jdock-ask-q', ask.question));
    const answer = text => { if (dockBusy) return; dockDraft = text; sendDock(root); };
    if (ask.choices.length) {
      const row = tEl('div', 'jdock-ask-choices');
      ask.choices.forEach(c => {
        const b = tEl('button', 'jdock-ask-choice', c);
        b.type = 'button';
        b.disabled = dockBusy;
        b.onclick = () => answer(c);
        row.appendChild(b);
      });
      card.appendChild(row);
    }
    if (ask.input) {
      const form = tEl('form', 'jdock-ask-form');
      const input = tEl('input', 'jdock-ask-input');
      input.type = ask.input;
      if (ask.input === 'number') { input.step = 'any'; input.inputMode = 'decimal'; }
      input.placeholder = ask.input === 'number' ? 'Type a number' : 'Type your answer';
      input.setAttribute('aria-label', ask.question);
      form.appendChild(input);
      if (ask.unit) form.appendChild(tEl('span', 'jdock-ask-unit', ask.unit));
      const send = tEl('button', 'jdock-ask-send', 'Send');
      send.type = 'submit';
      form.appendChild(send);
      form.onsubmit = e => {
        e.preventDefault();
        const value = input.value.trim();
        if (value) answer(value + (ask.unit ? ' ' + ask.unit : ''));
      };
      card.appendChild(form);
    }
    return card;
  }

  async function saveDockAction(root, mi, ai, body) {
    const res = await jsonSend('/api/journey/chats/' + dockChat.id + '/action',
      {message: mi, action: ai, scope: dockScope, ...body});
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
    dockPlanList(card, action, mi, ai);
    const buttons = tEl('div', 'rc-action-buttons');
    const accept = tEl('button', 'rc-accept', 'Accept');
    accept.onclick = async () => {
      accept.disabled = true;
      if (!(await applyDockMany(root, mi, [ai]))) accept.disabled = false;
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

  // Make one proposal: the plan's ticked sub-steps only. Returns the
  // server's answer, or null if it failed (with a toast saying why).
  async function applyDockAction(root, mi, ai) {
    const action = dockChat.messages[mi].actions[ai];
    let chosen = action;
    if (action.type === 'plan_step') {
      const key = dockChat.id + ':' + mi + ':' + ai + ':';
      const subs = action.sub_steps.filter((_, i) => !dockUnticked.has(key + i));
      if (!subs.length) { toast('Tick at least one sub-step'); return null; }
      chosen = {...action, sub_steps: subs};
      // Save the ticked part first, so the card says what was really added.
      if (subs.length < action.sub_steps.length &&
          !(await saveDockAction(root, mi, ai, {fields: {sub_steps: subs}}))) return null;
    }
    const res = await jsonSend('/api/journey/apply', {action: chosen});
    if (res.error) { toast(res.error, {error: true}); return null; }
    await saveDockAction(root, mi, ai, {resolved: 'accepted'});
    return res;
  }

  // Make several in order (Accept all, a typed "yes", auto-apply), then
  // redraw once. Stops at the first that fails. Returns how many were made.
  async function applyDockMany(root, mi, ais) {
    const done = [];
    for (const ai of ais) {
      const res = await applyDockAction(root, mi, ai);
      if (!res) break;
      done.push([dockChat.messages[mi].actions[ai], res]);
    }
    if (!done.length) return 0;
    const lead = (done.find(([a]) => DOCK_JOURNEY_LEVEL.includes(a.type)) || done[done.length - 1])[0];
    const made = done.find(([, r]) => r.journey_id);
    if (made && dockScope !== 'home') toast('New journey made. It’s on the Journeys page.');
    const filed = done.find(([a]) => a.type === 'set_folder');
    if (filed && done.length === 1) toast(filed[0].folder ? 'Filed in ' + filed[0].folder : 'Taken out of its folder');
    await refreshAfterDock(lead, {changed: done.flatMap(([, r]) => r.changed || []),
                                  deleted_journey: (done.find(([, r]) => r.deleted_journey) || [])[1]?.deleted_journey});
    return done.length;
  }

  // Redraw whatever the accepted change touched.
  async function refreshAfterDock(action, res) {
    if (DOCK_JOURNEY_LEVEL.includes(action.type)) loadSidebar();
    if (dockScope === 'home') { await renderJourneyHome(); return; }
    if (res.deleted_journey && res.deleted_journey === journeyData.project_id) {
      hideJourneyDock();
      await openJourneyView();
      return;
    }
    await renderJourney(res.changed);
  }

  // A plan lists its sub-steps, each with a box: Accept adds the ticked ones.
  function dockPlanList(card, action, mi, ai) {
    if (action.type !== 'plan_step' || !(action.sub_steps || []).length) return null;
    const list = tEl('div', 'jdock-plan');
    const boxes = action.sub_steps.map((sub, i) => {
      const row = tEl('label', 'jdock-plan-row');
      const box = tEl('input');
      box.type = 'checkbox';
      const key = dockChat.id + ':' + mi + ':' + ai + ':' + i;
      box.checked = !dockUnticked.has(key);
      box.onchange = () => { if (box.checked) dockUnticked.delete(key); else dockUnticked.add(key); };
      row.appendChild(box);
      row.appendChild(tEl('span', 'jdock-plan-title', sub.title));
      if (sub.due) row.appendChild(tEl('span', 'jdock-plan-due', shortDay(sub.due)));
      list.appendChild(row);
      return box;
    });
    card.appendChild(list);
    return boxes;
  }

  function dockActionEditor(root, action, mi, ai) {
    const form = tEl('form', 'rc-action jdock-edit');
    const inputs = DOCK_EDITABLE[action.type].map(([key, label]) => {
      const field = ['detail', 'note', 'purpose'].includes(key) ? tEl('textarea') : tEl('input');
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
    const send = tEl('button', 'proj-send');
    send.type = 'submit';
    send.innerHTML = SEND_SVG;
    send.setAttribute('aria-label', 'Send');
    send.disabled = !dockDraft.trim() && !dockReady().length;
    const picker = tEl('input');
    picker.type = 'file';
    picker.multiple = true;
    picker.accept = DOCK_FILE_TYPES;
    picker.hidden = true;
    picker.onchange = () => { attachDockFiles(root, picker.files); picker.value = ''; };
    const clip = tEl('button', 'jdock-attach');
    clip.type = 'button';
    clip.innerHTML = CLIP_SVG;
    clip.title = 'Attach a screenshot, PDF or text file';
    clip.setAttribute('aria-label', 'Attach a file');
    clip.onclick = () => picker.click();
    // A pasted screenshot attaches; pasted text pastes as usual.
    field.onpaste = e => {
      const files = [...(e.clipboardData ? e.clipboardData.files : [])];
      if (!files.length) return;
      e.preventDefault();
      attachDockFiles(root, files);
    };
    field.oninput = () => {
      dockDraft = field.value;
      send.disabled = !field.value.trim() && !dockReady().length;
      field.style.height = 'auto';
      field.style.height = Math.min(field.scrollHeight, 140) + 'px';
    };
    field.onkeydown = e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendDock(root); }
    };
    form.onsubmit = e => { e.preventDefault(); sendDock(root); };
    form.append(picker, clip, field, send);
    const wrap = tEl('div', 'jdock-compose');
    wrap.append(dockFilesEl(root), form);
    return wrap;
  }

  // The files waiting to go with the next message, each removable.
  function dockFilesEl(root) {
    const strip = tEl('div', 'jdock-files');
    dockFiles.forEach(f => {
      const chip = tEl('div', 'jdock-file ' + f.status);
      chip.appendChild(tEl('span', 'jdock-file-name', f.name));
      chip.appendChild(tEl('span', 'jdock-file-state',
        f.status === 'reading' ? 'Reading…' : f.status === 'error' ? f.error : 'Ready'));
      const x = tEl('button', 'jdock-file-x', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Remove ' + f.name);
      x.onclick = () => { dockFiles = dockFiles.filter(o => o !== f); redrawDockFiles(root); };
      chip.appendChild(x);
      strip.appendChild(chip);
    });
    return strip;
  }

  function redrawDockFiles(root) {
    const strip = root.querySelector('.jdock-files');
    if (strip) strip.replaceWith(dockFilesEl(root));
    const send = root.querySelector('.jdock-form .proj-send');
    if (send) send.disabled = !dockDraft.trim() && !dockReady().length;
  }

  const readAsBase64 = file => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

  // Each file is read into text on the server as soon as it's added, so
  // sending doesn't wait on it.
  function attachDockFiles(root, fileList) {
    [...fileList].forEach(async file => {
      const pasted = file.name === 'image.png' || !file.name;
      const name = pasted ? 'Screenshot ' + new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})
        .replace(':', '.') + '.png' : file.name;
      const entry = {name, status: 'reading', text: '', error: ''};
      dockFiles = [...dockFiles, entry];
      redrawDockFiles(root);
      let res;
      try {
        res = await jsonSend('/api/journey/attach', {name, data: await readAsBase64(file)});
      } catch (err) {
        res = {error: 'Couldn’t read that file'};
      }
      if (!dockFiles.includes(entry)) return;   // removed while reading
      Object.assign(entry, res.error ? {status: 'error', error: res.error} : {status: 'ready', text: res.text});
      if (res.saved) toast('Saved ' + name + ' to your memory too');
      redrawDockFiles(root);
    });
  }

  async function sendDock(root, queued) {
    const message = queued ? queued.message : dockDraft.trim();
    const files = queued ? queued.files : dockReady();
    if (!message && !files.length) return;
    if (!queued && dockFiles.some(f => f.status === 'reading')) { toast('Still reading a file…'); return; }
    const saved = [message || 'Here’s what I sent.', ...files.map(f => '📎 ' + f.name)].join('\n');
    if (dockBusy) {
      // Sent while it's thinking: shown as waiting, and sent right after this reply.
      if (dockQueued) { toast('One message can wait at a time'); return; }
      dockQueued = {message, files, saved};
      dockDraft = '';
      if (!queued) dockFiles = [];
      drawDock(root);
      return;
    }
    const lastAt = dockChat ? dockChat.messages.length - 1 : -1;
    const last = lastAt >= 0 ? dockChat.messages[lastAt] : null;
    if (last && last.role === 'assistant' && DOCK_CONFIRM.test(message) && dockPending(last).length) {
      dockDraft = '';
      const n = await applyDockMany(root, lastAt, dockPending(last).map(([, ai]) => ai));
      if (n) toast('Applied ' + n + ' change' + (n === 1 ? '' : 's'));
      return;
    }
    const pid = dockKey();
    dockBusy = true;
    if (!queued) { dockDraft = ''; dockFiles = []; }
    const before = dockChat;
    dockChat = {...(dockChat || {title: 'New chat', project_id: pid}),
                messages: [...(dockChat ? dockChat.messages : []), {role: 'user', content: saved}]};
    drawDock(root);
    const title = before ? '' : dockTitle;
    dockTitle = '';
    const hint = dockHint;
    dockHint = '';
    const res = await jsonSend('/api/journey/chat',
      {message, chat_id: before ? before.id : '', title, scope: dockScope, auto: dockAutoApply(),
       step_id: dockScope === 'home' ? '' : journeyFocus || '', hint,
       attachments: files.map(f => ({name: f.name, text: f.text}))});
    dockBusy = false;
    const next = dockQueued;
    dockQueued = null;
    // You may have moved on (another journey, or the Journeys page) while
    // it was thinking: the reply is saved to its chat; don't show it here.
    if (dockProject !== pid) {
      if (res.error) toast(res.error, {error: true});
      drawDock(root);
      return;
    }
    if (res.error) {
      dockChat = before;
      if (!dockDraft) dockDraft = message;
      if (!dockFiles.length) dockFiles = files;
      toast(res.error, {error: true});
    } else {
      dockChat = res.chat;
      dockFresh = dockChat.messages.length - 1;
      rememberDockChat(res.chat.id);
    }
    drawDock(root);
    root.querySelector('.jdock-input').focus();
    if (!res.error && dockAutoApply()) {
      const mi = dockChat.messages.length - 1;
      const ais = dockPending(dockChat.messages[mi]).filter(([a]) => !DOCK_ASKS_FIRST.includes(a.type)).map(([, ai]) => ai);
      if (ais.length) await applyDockMany(root, mi, ais);
    }
    if (next) await sendDock(root, next);
  }
