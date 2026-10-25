
  // ---------- journey: side panel ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Next up, suggestions (with the places they come from), and the chat
  // that reshapes the journey. Nothing here changes a track on its own:
  // suggestions and chat actions wait for Accept.

  const SUGGESTION_SOURCES = {review: 'Review', mindtrail: 'Mind Trail', gmail: 'Gmail', calendar: 'Calendar', gemini: 'Gemini', paste: 'Pasted chat'};
  const SUGGESTION_KINDS = {add_done: 'Did', add_step: 'Next', mark_done: 'Finished'};
  let journeyChatLog = [];

  function journeyRail() {
    const rail = tEl('aside', 'journey-rail');
    const pending = journeyData.suggestions.length;
    const pane = tEl('div', 'jpane');
    const which = prefs.get('journeyRail', 'next');
    const show = key => {
      pane.replaceChildren(key === 'suggestions' ? journeySuggestionsPane()
        : key === 'chat' ? journeyChatPane() : journeyNextPane());
    };
    rail.appendChild(segmented([
      {value: 'next', label: 'Next up'},
      {value: 'suggestions', label: 'Suggestions' + (pending ? ' · ' + pending : '')},
      {value: 'chat', label: 'Assistant'},
    ], which, key => { prefs.set('journeyRail', key); show(key); }, 'Side panel'));
    rail.appendChild(pane);
    show(which);
    return rail;
  }

  // ---------- next up ----------

  function journeyNextPane() {
    const box = tEl('div', 'jnext');
    if (!journeyData.next_up.length) {
      box.appendChild(emptyState('todo', 'Nothing pressing',
        'Put steps in this term or next and the most important ones show up here.'));
      return box;
    }
    journeyData.next_up.forEach(s => {
      const row = tEl('button', 'jnext-row');
      row.type = 'button';
      row.appendChild(tEl('div', 'jnext-title', s.title));
      row.appendChild(tEl('div', 'jnext-sub', s.track + ' · ' + s.reason));
      row.onclick = () => journeyStepSheet(s);
      box.appendChild(row);
    });
    return box;
  }

  // ---------- suggestions ----------

  function journeySuggestionsPane() {
    const box = tEl('div', 'jsugg');
    const list = tEl('div', 'jsugg-list');
    const items = journeyData.suggestions;
    if (!items.length) {
      list.appendChild(tEl('div', 'jsugg-empty',
        'Nothing waiting. Review a past year, or pull from the sources below.'));
    }
    items.forEach(s => list.appendChild(journeySuggestion(s)));
    if (items.length > 1) {
      const all = tEl('button', 'btn-plain jsugg-all', 'Accept all ' + items.length);
      all.onclick = async () => {
        all.disabled = true;
        const done = [];
        for (const s of items) {
          const res = await jsonSend('/api/journey/suggestions/' + s.id + '/accept', journeySuggestionTarget(s));
          if (res.node_id) done.push(res.node_id);
        }
        await renderJourney(done);
      };
      list.appendChild(all);
    }
    box.appendChild(list);
    box.appendChild(journeySources());
    return box;
  }

  // New steps land on the track you're looking at, else the one the model named.
  function journeySuggestionTarget(s) {
    const tab = journeyTab();
    return {roadmap_id: s.kind === 'mark_done' ? '' : (s.roadmap_id || (tab === 'all' ? '' : tab))};
  }

  function journeySuggestion(s) {
    const card = tEl('div', 'jsugg-card');
    const head = tEl('div', 'jsugg-head');
    head.appendChild(tEl('span', 'jsugg-kind ' + s.kind, SUGGESTION_KINDS[s.kind]));
    head.appendChild(tEl('span', 'jsugg-source', SUGGESTION_SOURCES[s.source] || s.source));
    card.appendChild(head);
    card.appendChild(tEl('div', 'jsugg-title', s.title));
    const where = [s.track, s.term_label].filter(Boolean).join(' · ');
    if (where) card.appendChild(tEl('div', 'jsugg-where', where));
    if (s.detail) card.appendChild(tEl('div', 'jsugg-detail', s.detail));
    if (s.reason) card.appendChild(tEl('div', 'jsugg-reason', s.reason));
    const row = tEl('div', 'jsugg-actions');
    const accept = tEl('button', 'btn-tinted', s.kind === 'mark_done' ? 'Mark done' : 'Add');
    accept.onclick = async () => {
      accept.disabled = true;
      const res = await jsonSend('/api/journey/suggestions/' + s.id + '/accept', journeySuggestionTarget(s));
      if (res.error) { accept.disabled = false; toast(res.error, {error: true}); return; }
      await renderJourney([res.node_id]);
    };
    const dismiss = tEl('button', 'btn-plain', 'Dismiss');
    dismiss.onclick = async () => {
      await jsonSend('/api/journey/suggestions/' + s.id + '/dismiss', {});
      await renderJourney();
    };
    row.appendChild(accept);
    row.appendChild(dismiss);
    card.appendChild(row);
    return card;
  }

  // ---------- where suggestions come from ----------

  async function journeyScan(btn, label, path, body) {
    setButtonBusy(btn, 'Reading…');
    const res = await jsonSend(path, body || {});
    setButtonIdle(btn, label);
    if (res.error) { toast(res.error, {error: true}); return; }
    toast(res.looked_at
      ? 'Read ' + res.looked_at + ' items · ' + res.added + ' new suggestion' + (res.added === 1 ? '' : 's')
      : 'Nothing new to read');
    await renderJourney();
  }

  function journeySources() {
    const box = tEl('div', 'jsources');
    box.appendChild(tEl('div', 'jsources-title', 'Update from'));
    const add = (label, hint, run) => {
      const row = tEl('div', 'jsource');
      const text = tEl('div', 'jsource-text');
      text.appendChild(tEl('div', 'jsource-label', label));
      text.appendChild(tEl('div', 'jsource-hint', hint));
      row.appendChild(text);
      const b = tEl('button', 'btn-tinted', 'Read');
      b.onclick = () => run(b);
      row.appendChild(b);
      box.appendChild(row);
    };
    add('Mind Trail', 'Practice, jobs, interviews, chats, GitHub',
      b => journeyScan(b, 'Read', '/api/journey/scan/mindtrail'));
    add('Gmail', 'Club, course, hackathon and research emails',
      b => journeyScan(b, 'Read', '/api/journey/scan/gmail'));
    add('Google Calendar', 'Exams, deadlines and events in the next two months',
      b => journeyScan(b, 'Read', '/api/journey/scan/calendar'));
    add('Gemini export', 'Takeout → My Activity → Gemini Apps', b => journeyPickGemini(b));
    add('Paste a chat', 'Any conversation you want counted', async b => {
      const text = await modal({title: 'Paste a chat', input: true, multiline: true,
        placeholder: 'Paste the conversation here', confirmLabel: 'Read it'});
      if (text) await journeyScan(b, 'Read', '/api/journey/import/paste', {text});
    });
    box.appendChild(tEl('div', 'jsources-note',
      'Text from these goes to the AI model to be summarised, and nowhere else.'));
    return box;
  }

  function journeyPickGemini(btn) {
    const input = tEl('input');
    input.type = 'file';
    input.accept = '.json,.html,application/json,text/html';
    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return;
      await journeyScan(btn, 'Read', '/api/journey/import/gemini', {text: await file.text()});
    };
    input.click();
  }

  // ---------- chat ----------

  function journeyChatPane() {
    const box = tEl('div', 'jchat');
    const log = tEl('div', 'jchat-log');
    const draw = () => {
      log.replaceChildren();
      if (!journeyChatLog.length) {
        log.appendChild(tEl('div', 'jsugg-empty',
          'Tell it what to change: “make a research track”, “copy SWE as a backup plan”, ' +
          '“move LeetCode prep to winter”, or ask it to compare two tracks.'));
      }
      journeyChatLog.forEach(m => {
        log.appendChild(tEl('div', 'rc-msg ' + m.role, m.content));
        (m.actions || []).forEach(a => log.appendChild(journeyActionCard(a, draw)));
      });
      log.scrollTop = log.scrollHeight;
    };
    draw();
    box.appendChild(log);

    const form = tEl('form', 'jchat-form');
    const input = tEl('input');
    input.placeholder = 'Ask or change something…';
    input.setAttribute('aria-label', 'Message the assistant');
    const send = tEl('button', 'send', 'Send');
    send.type = 'submit';
    form.appendChild(input);
    form.appendChild(send);
    form.onsubmit = async e => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      send.disabled = input.disabled = true;
      const history = journeyChatLog.map(m => ({role: m.role, content: m.content}));
      journeyChatLog.push({role: 'user', content: message});
      draw();
      const res = await jsonSend('/api/journey/chat', {message, history});
      send.disabled = input.disabled = false;
      input.focus();
      journeyChatLog.push(res.error
        ? {role: 'assistant', content: 'Error: ' + res.error, actions: []}
        : {role: 'assistant', content: res.reply, actions: res.actions || []});
      draw();
    };
    box.appendChild(form);
    return box;
  }

  function journeyActionCard(action, redraw) {
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
      action.resolved = 'accepted';
      if (['create_track', 'duplicate_track'].includes(action.type)) prefs.set('journeyTab', res.track_id);
      await renderJourney(res.changed);
    };
    const dismiss = tEl('button', 'rc-reject', 'Dismiss');
    dismiss.onclick = () => { action.resolved = 'rejected'; redraw(); };
    buttons.appendChild(accept);
    buttons.appendChild(dismiss);
    card.appendChild(buttons);
    return card;
  }

  // Today's widget: how this term is going and the first thing next. Stays
  // hidden until the journey is set up.
  function journeyTile() {
    const tile = glanceTile('Journey', () => openJourneyView());
    tile.hidden = true;
    api('/api/journey/today').then(d => {
      if (!d.setup) return;
      tile.hidden = false;
      tile.querySelector('.t-tile-head').textContent = 'Journey · ' + d.label;
      if (d.total) {
        const bar = tEl('div', 'jtile-bar');
        const fill = tEl('div', 'jtile-fill');
        fill.style.width = Math.round(d.done / d.total * 100) + '%';
        bar.appendChild(fill);
        tile.appendChild(bar);
        tile.appendChild(tEl('div', 't-note', d.done + ' of ' + d.total + ' steps done this term'));
      } else {
        tile.appendChild(tEl('div', 't-note', 'No steps in this term yet'));
      }
      d.next.forEach(s => {
        const item = tEl('div', 't-item');
        const body = tEl('div', 't-item-body');
        body.appendChild(tEl('div', 't-item-title', s.title));
        body.appendChild(tEl('div', 't-item-sub', s.track + ' · ' + s.reason));
        item.appendChild(body);
        makeClickable(item, () => openJourneyView());
        tile.appendChild(item);
      });
      if (d.pending) tile.appendChild(tEl('div', 't-note', d.pending + ' suggestion' + (d.pending === 1 ? '' : 's') + ' waiting'));
    });
    return tile;
  }
