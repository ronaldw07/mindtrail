  // ---------- project detail ----------

  function relTime(iso) {
    if (!iso) return '';
    const secs = (Date.now() - new Date(iso).getTime()) / 1000;
    if (secs < 90) return 'just now';
    if (secs < 3600) return Math.round(secs / 60) + ' min ago';
    if (secs < 86400) return Math.round(secs / 3600) + ' hours ago';
    return Math.round(secs / 86400) + ' days ago';
  }

  function card(title, buttonLabel, onClick) {
    const c = document.createElement('div');
    c.className = 'card';
    const h = document.createElement('h4');
    h.appendChild(document.createTextNode(title));
    const sp = document.createElement('span'); sp.className = 'spacer';
    h.appendChild(sp);
    if (buttonLabel) {
      const b = document.createElement('button');
      b.className = 'card-btn';
      b.textContent = buttonLabel;
      b.onclick = onClick;
      h.appendChild(b);
    }
    c.appendChild(h);
    return c;
  }

  // A compact propose/accept chat card - same safety property as the
  // roadmap's larger canvas-side panel (the model only ever proposes;
  // nothing changes until Accept is clicked), packaged for the project
  // and profile screens where a full side panel doesn't fit. `chatLog`
  // is the caller's persistent array (survives a parent re-render since
  // it lives outside this card); `applyAction` performs one accepted
  // action's real mutation and returns whether it succeeded;
  // `afterApply` runs after a successful accept to refresh whatever the
  // action changed.
  function buildAssistantCard(title, hint, chatLog, sendMessage, applyAction, afterApply) {
    const c = card(title, null, null);
    const log = document.createElement('div');
    log.className = 'rc-log';
    c.appendChild(log);

    function renderActionCard(action) {
      const box = document.createElement('div');
      box.className = 'rc-action' + (action.resolved ? ' resolved' : '');
      const label = document.createElement('div');
      label.className = 'rc-action-label';
      label.textContent = action.label;
      box.appendChild(label);

      if (action.resolved) {
        const note = document.createElement('div');
        note.className = 'rc-action-resolved-note';
        note.textContent = action.resolved === 'accepted' ? '\u2713 Applied' : '\u2717 Dismissed';
        box.appendChild(note);
        return box;
      }

      const buttons = document.createElement('div');
      buttons.className = 'rc-action-buttons';
      const accept = document.createElement('button');
      accept.className = 'rc-accept';
      accept.textContent = 'Accept';
      accept.onclick = async () => {
        accept.disabled = true;
        const ok = await applyAction(action);
        if (!ok) { accept.disabled = false; return; }
        action.resolved = 'accepted';
        await afterApply();
      };
      buttons.appendChild(accept);
      const reject = document.createElement('button');
      reject.className = 'rc-reject';
      reject.textContent = 'Dismiss';
      reject.onclick = () => { action.resolved = 'rejected'; renderLog(); };
      buttons.appendChild(reject);
      box.appendChild(buttons);
      return box;
    }

    function renderLog() {
      log.innerHTML = '';
      if (!chatLog.length) {
        const hintEl = document.createElement('div');
        hintEl.className = 'muted';
        hintEl.textContent = hint;
        log.appendChild(hintEl);
      }
      chatLog.forEach(entry => {
        const msg = document.createElement('div');
        msg.className = 'rc-msg ' + entry.role;
        msg.textContent = entry.content;
        log.appendChild(msg);
        (entry.actions || []).forEach(a => log.appendChild(renderActionCard(a)));
      });
      log.scrollTop = log.scrollHeight;
    }
    renderLog();

    const form = document.createElement('form');
    form.className = 'rc-form';
    const input = document.createElement('input');
    input.className = 'rc-input';
    input.placeholder = 'Ask\u2026';
    form.appendChild(input);
    const mic = micButton();
    attachDictation(mic, input, msg => { if (msg) toast(msg, {error: msg.includes('fail')}); });
    form.appendChild(mic);
    const sendBtn = document.createElement('button');
    sendBtn.className = 'send';
    sendBtn.type = 'submit';
    sendBtn.textContent = 'Send';
    form.appendChild(sendBtn);
    form.onsubmit = async e => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      sendBtn.disabled = input.disabled = true;

      const historyForRequest = chatLog.map(m => ({role: m.role, content: m.content}));
      chatLog.push({role: 'user', content: message});
      renderLog();

      const res = await sendMessage(message, historyForRequest);
      sendBtn.disabled = input.disabled = false;
      input.focus();
      if (res.error) {
        chatLog.push({role: 'assistant', content: 'Error: ' + res.error, actions: []});
      } else {
        chatLog.push({role: 'assistant', content: res.reply, actions: res.actions || []});
      }
      renderLog();
    };
    c.appendChild(form);
    return c;
  }

  const VIEW_NAMES = ['project', 'roadmap', 'profile', 'dashboard', 'jobs', 'tasks', 'habits', 'journal', 'week', 'people', 'practice', 'stories', 'journey'];

  // Which sidebar button lights up for each view.
  const VIEW_NAV = {dashboard: 'open-today', week: 'open-week', tasks: 'open-tasks', habits: 'open-habits',
                    journal: 'open-journal', jobs: 'open-journey', people: 'open-people',
                    practice: 'open-journey', stories: 'open-stories', journey: 'open-journey',
                    profile: 'open-profile'};

  let activeView = null;

  function setActiveView(name) {
    activeView = name;
    // The journey assistant floats over the page; only a journey shows it.
    if (name !== 'journey') hideJourneyDock();
    VIEW_NAMES.forEach(v => $(v + '-view').classList.toggle('open', name === v));
    // Per button, not per view: Jobs and Practice share the Career button.
    new Set(Object.values(VIEW_NAV)).forEach(id => {
      const btn = $(id);
      const on = VIEW_NAV[name] === id;
      btn.classList.toggle('active', on);
      if (on) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });
    // Views with their own big title show it in the toolbar only once it
    // has scrolled away (see updateToolbarTitle in ui.js).
    $('topbar').dataset.title = ['chat', 'project', 'roadmap'].includes(name) ? 'inline' : 'large';
    updateToolbarTitle();
    loadBadges();
    log.style.display = name === 'chat' ? '' : 'none';
    $('composer').style.display = name === 'chat' ? '' : 'none';
    syncTreeActive();
  }

  function showChatView() { setActiveView('chat'); }
  function showProjectView() { setActiveView('project'); }
  function showRoadmapView() { setActiveView('roadmap'); }
  function showProfileView() { setActiveView('profile'); }
  function showDashboardView() { setActiveView('dashboard'); }

  async function openProject(id, opts) {
    opts = opts || {};
    const view = $('project-view');
    // Clicking the project that's already on screen refreshes it in place
    // rather than blanking it to a placeholder and back.
    if (currentProject === id && view.classList.contains('open')) opts = {...opts, background: true};
    currentProject = id;
    current = null;
    showProjectView();

    // The placeholder only appears if the load is slow enough to notice;
    // a fast load swaps straight from the old screen to the new one.
    let skeletonTimer = null;
    if (!opts.background) {
      skeletonTimer = setTimeout(() => view.replaceChildren(skeletonBlock(6)), SKELETON_DELAY_MS);
      $('breadcrumb').textContent = 'Projects';
      // A background refresh (e.g. after the chat assistant renames the
      // project) must not wipe the chat history it's about to redraw.
      projectChatLog = [];
    }

    // Opening a project must never block on a model call - background=1
    // always skips highlight generation here, regardless of opts.background
    // (which only controls the loading placeholder below). Stale or
    // missing highlights show as-is with a note; the Refresh button, not
    // navigation, is what pays the LLM round trip.
    const params = ['background=1'];
    if (opts.refresh) params.push('refresh=1');
    // Both requests are independent, so they're fired together instead of
    // one after the other — the roadmap fetch below just reads a promise
    // that has usually already resolved by the time it's needed.
    const dataPromise = api('/api/projects/' + id +
                            (params.length ? '?' + params.join('&') : ''));
    const rmDataPromise = api('/api/roadmap/' + id);
    const [data, rmData] = await Promise.all([dataPromise, rmDataPromise]);
    clearTimeout(skeletonTimer);
    // A later click won the race; drawing this one would show the wrong project.
    if (currentProject !== id) return;
    if (data.error) { view.innerHTML = ''; setStatus(data.error); return; }
    // Only a real navigation (not a background refresh after a rename or
    // move elsewhere) should overwrite what reload restores to.
    if (!opts.background) prefs.set('lastView', {type: 'project', id});

    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode('Projects / '));
    const b = document.createElement('b');
    b.textContent = data.name;
    $('breadcrumb').appendChild(b);

    const layout = document.createElement('div');
    layout.className = 'proj-layout';

    // --- left: title, a composer that starts a chat here, the chats ---
    const main = document.createElement('div');
    main.className = 'proj-main';
    main.appendChild(tEl('div', 'proj-title', data.name));
    main.appendChild(projectComposer(id, data.name));
    main.appendChild(projectChatList(data.conversations));
    layout.appendChild(main);

    // --- right rail: instructions, context, memory, then the cards ---
    const rail = document.createElement('div');
    rail.className = 'proj-rail';
    rail.appendChild(projectProps(id, data));

    // Refresh replaces only this panel's contents, so the rest of the
    // project screen does not flash while one card reloads.
    const hlCard = card('What\u2019s next', '\u21bb Refresh', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = '\u21bb Refreshing\u2026';
      const fresh = await api('/api/projects/' + id + '?refresh=1');
      btn.disabled = false;
      btn.textContent = '\u21bb Refresh';
      if (fresh.error) { toast(fresh.error, {error: true}); return; }
      fillHighlights(hlCard, fresh, id);
      toast(fresh.highlights_error
        ? 'Could not refresh: ' + fresh.highlights_error
        : 'Suggestions updated', {error: !!fresh.highlights_error});
    });
    fillHighlights(hlCard, data, id);
    rail.appendChild(hlCard);

    const roadmapCard = card('Roadmap', null, null);
    if (!rmData.roadmap) {
      const goalInput = document.createElement('input');
      goalInput.placeholder = 'What are you working toward?';
      goalInput.style.cssText = 'width:100%;padding:0.5rem 0.65rem;border-radius:8px;' +
        'border:1px solid #333;background:#191919;color:#ececec;font-size:0.85rem;' +
        'margin:0.5rem 0;';
      roadmapCard.appendChild(goalInput);
      const genBtn = document.createElement('button');
      genBtn.className = 'send';
      genBtn.textContent = 'Generate roadmap';
      genBtn.onclick = async () => {
        const goal = goalInput.value.trim();
        if (!goal) { toast('Enter a goal first', {error: true}); return; }
        setButtonBusy(genBtn, 'Generating\u2026');
        const res = await jsonSend('/api/roadmap/' + id + '/generate', {goal});
        setButtonIdle(genBtn, 'Generate roadmap');
        if (res.error) { toast(res.error, {error: true}); return; }
        openRoadmapView(id, data.name);
      };
      roadmapCard.appendChild(genBtn);
    } else {
      const summary = document.createElement('div');
      summary.className = 'muted';
      summary.textContent = rmData.roadmap.goal;
      roadmapCard.appendChild(summary);
      const openBtn = document.createElement('button');
      openBtn.className = 'send';
      openBtn.style.marginTop = '0.5rem';
      openBtn.textContent = 'Open roadmap';
      openBtn.onclick = () => openRoadmapView(id, data.name);
      roadmapCard.appendChild(openBtn);
    }
    rail.appendChild(roadmapCard);

    const assistantCard = buildAssistantCard(
      'Project Assistant',
      'Ask about this project, or tell it what to change \u2014 it can ' +
      'propose renaming it or updating its instructions.',
      projectChatLog,
      (message, history) => jsonSend('/api/projects/' + id + '/chat', {message, history}),
      async action => {
        const patch = {};
        if (action.name !== null) patch.name = action.name;
        if (action.instructions !== null) patch.instructions = action.instructions;
        const res = await jsonSend('/api/projects/' + id, patch, 'PATCH');
        if (res.error) { toast(res.error, {error: true}); return false; }
        return true;
      },
      () => refreshViews()
    );
    rail.appendChild(assistantCard);

    layout.appendChild(rail);
    view.replaceChildren(layout);
  }

  // Rebuilds only the body of the What's next card, leaving its header
  // (and the Refresh button being clicked) in place.
  function fillHighlights(cardEl, data, projectId) {
    cardEl.querySelectorAll(':scope > *:not(h4)').forEach(n => n.remove());

    if (data.highlights_error) {
      const e = document.createElement('div');
      e.className = 'muted';
      e.textContent = 'Could not refresh \u2014 ' + data.highlights_error +
                      '. Showing the previous suggestions.';
      cardEl.appendChild(e);
    }
    // Loading a project never generates automatically now, so an
    // entry_count > 0 project with zero highlights just hasn't had
    // Refresh clicked yet - distinct from one with nothing to work from.
    if (!data.highlights.length && !data.highlights_error) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = data.entry_count
        ? 'Not generated yet \u2014 hit Refresh to see suggestions.'
        : 'Add chats or a document, and suggestions appear here.';
      cardEl.appendChild(p);
    }
    if (data.highlights_stale && data.highlights.length && !data.highlights_error) {
      const note = document.createElement('div');
      note.className = 'stale-note';
      note.textContent = 'New activity since these \u2014 hit Refresh to update.';
      cardEl.appendChild(note);
    }

    data.highlights.forEach(h => {
      const tier = h.priority || 'next';
      const item = document.createElement('div');
      item.className = 'hl ' + tier;
      item.title = 'Click to expand';

      const head = document.createElement('div');
      head.className = 'hl-head';
      const badge = document.createElement('span');
      badge.className = 'tier ' + tier;
      badge.textContent = tier === 'now' ? 'Do now' : tier;
      head.appendChild(badge);
      head.appendChild(document.createTextNode(h.headline));
      item.appendChild(head);

      if (h.detail) {
        const d = document.createElement('div');
        d.className = 'hl-detail';
        d.textContent = h.detail;
        item.appendChild(d);
      }
      if (h.source) {
        const s = document.createElement('div');
        s.className = 'hl-source';
        // The prompt labels entries "[RESEARCH] ..." so the model can tell
        // documents from chats; that tag is internal and reads as noise here.
        s.textContent = 'from: ' + h.source.replace(/^\[[A-Z]+\]\s*/, '');
        item.appendChild(s);
      }
      makeClickable(item, () => expandHighlight(h, data.name));
      cardEl.appendChild(item);
    });

    if (data.highlights_generated_at && data.highlights.length) {
      const stamp = document.createElement('div');
      stamp.className = 'stamp';
      stamp.textContent = 'Updated ' + relTime(data.highlights_generated_at) +
                          ' \u00b7 based on ' + data.entry_count + ' item(s)';
      cardEl.appendChild(stamp);
    }
  }

  function expandHighlight(h, projectName) {
    const tier = h.priority || 'next';
    const parts = [];
    if (h.detail) parts.push(h.detail);
    if (h.source) {
      parts.push('Based on: ' + h.source.replace(/^\[[A-Z]+\]\s*/, ''));
    }
    parts.push('Project: ' + projectName);
    modal({
      title: (tier === 'now' ? '\u2605  ' : '') + h.headline,
      message: parts.join('\n\n'),
      confirmLabel: 'Ask about this'
    }).then(async ok => {
      if (!ok) return;
      // Turning a highlight into a question is the natural next move, so
      // it drops straight into the composer inside this project.
      newChatInProject(currentProject, projectName);
      input.value = h.headline;
      input.focus();
    });
  }

  function newChatInProject(projectId, projectName) {
    showChatView();
    current = null;
    pendingProject = {id: projectId, name: projectName};
    showEmptyState();
    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode(projectName + ' / '));
    const b = document.createElement('b');
    b.textContent = 'New chat';
    $('breadcrumb').appendChild(b);
    input.focus();
  }

