  // ---------- command palette (Cmd+K) ----------
  // /api/search is semantic vector search over memory entries only - it
  // cannot find a project, a chat, or a roadmap step, and semantic
  // matching is not fuzzy matching (typing "roadm" would match nothing
  // there). So the palette fuzzy-matches client-side over a fresh
  // /api/palette-index fetch on every open (projects, chats, roadmap
  // step titles - cheap, local, no LLM), and queries /api/search
  // separately, debounced, for the memory-entries group. No open/close
  // animation anywhere in here - deliberate, see PLAN.md: this is a
  // keyboard action used constantly, and animating it makes the whole
  // app feel slow.

  const PALETTE_MEMORY_DEBOUNCE_MS = 200;
  const PALETTE_MAX_PER_GROUP = 6;

  // Icon tile + type label per kind of result, so a row says what it is.
  const PALETTE_KINDS = {
    project: {label: 'Project', color: '#0071e3', icon: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'},
    chat: {label: 'Chat', color: '#248a3d', icon: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'},
    step: {label: 'Step', color: '#8944ab', icon: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M6 8v4a4 4 0 0 0 4 4h6"/>'},
    memory: {label: 'Memory', color: '#636366', icon: '<path d="M4 6h16M4 12h16M4 18h10"/>'},
    todo: {label: 'To-do', color: '#0071e3', icon: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>'},
    job: {label: 'Job', color: '#a0560a', icon: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'},
    person: {label: 'Person', color: '#0e7c86', icon: '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>'},
    action: {label: 'Action', color: '#d9480f', icon: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>'},
  };

  // Cheap subsequence fuzzy match, not a full fuzzy-ranking algorithm:
  // every character of the query must appear in order in the text.
  // Rewards an early, consecutive run so "roadm" ranks "Roadmap" above
  // a title that merely happens to contain the same letters scattered
  // apart. Returns -1 for no match, so callers can filter with >= 0.
  function fuzzyScore(query, text) {
    const q = query.toLowerCase(), t = text.toLowerCase();
    if (!q) return 0;
    let ti = 0, score = 0, streak = 0;
    for (let qi = 0; qi < q.length; qi++) {
      const idx = t.indexOf(q[qi], ti);
      if (idx === -1) return -1;
      streak = (idx === ti) ? streak + 1 : 1;
      score += (10 - Math.min(idx - ti, 9)) + streak;
      ti = idx + 1;
    }
    return score;
  }

  // Context-aware: "Tidy roadmap" / "Regenerate roadmap" only make sense
  // with a roadmap open, so they're omitted otherwise rather than shown
  // disabled. Both trigger the exact toolbar buttons the canvas already
  // has (see the ids added alongside tidyBtn/regenBtn in renderRoadmap)
  // instead of duplicating their logic here.
  function paletteActions() {
    const actions = [
      {label: 'New chat', run: () => { closePalette(); newChat(); }},
      {label: 'New note', run: () => { closePalette(); addNote(); }},
      {label: 'Save a link', run: () => { closePalette(); saveUrl(); }},
      {label: 'New project', run: () => { closePalette(); createProject(); }},
      {label: 'Go to Today', run: () => { closePalette(); openDashboardView(); }},
      {label: 'Go to Jobs', run: () => { closePalette(); openJobsView(); }},
      {label: 'Go to To-dos', run: () => { closePalette(); openTasksView(); }},
      {label: 'Go to Habits', run: () => { closePalette(); openHabitsView(); }},
      {label: 'Weekly review', run: () => { closePalette(); openWeekView(); }},
      {label: 'Go to People', run: () => { closePalette(); openPeopleView(); }},
      {label: 'Go to Practice', run: () => { closePalette(); openPracticeView(); }},
      {label: 'Go to Stories', run: () => { closePalette(); openStoriesView(); }},
      {label: 'Write in journal', run: () => { closePalette(); openJournalView(); }},
      {label: 'Go to Profile', run: () => { closePalette(); openProfileView(); }},
      {label: 'Add a to-do', run: () => { closePalette(); quickAddTask(); }},
      {label: 'Start a focus session', run: () => { closePalette(); startFocus(); }},
      {label: 'Add a job application', run: async () => {
        closePalette();
        await openJobsView();
        const input = document.querySelector('.jobs-link-input');
        if (input) input.focus();
      }},
    ];
    if (isRoadmapViewOpen()) {
      actions.push({label: 'Tidy roadmap', run: () => {
        closePalette();
        const btn = $('roadmap-tidy-btn');
        if (btn) btn.click();
      }});
      actions.push({label: 'Regenerate roadmap', run: () => {
        closePalette();
        const btn = $('roadmap-regenerate-btn');
        if (btn) btn.click();
      }});
    }
    return actions;
  }

  let paletteTrigger = null;
  let popPaletteLayer = null;

  function closePalette() {
    const el = $('palette');
    if (el.style.display !== 'block') return;
    el.style.display = 'none';
    el.innerHTML = '';
    if (popPaletteLayer) { popPaletteLayer(); popPaletteLayer = null; }
    const trigger = paletteTrigger;
    paletteTrigger = null;
    if (trigger && typeof trigger.focus === 'function') trigger.focus();
  }

  async function openPalette() {
    const el = $('palette');
    if (el.style.display === 'block') {
      const existing = el.querySelector('input');
      if (existing) existing.focus();
      return;
    }
    paletteTrigger = document.activeElement;
    el.innerHTML = '';
    // Styling lives in app.css (.palette-*) - see the "command palette /
    // shortcuts overlay" section there for the frosted material.
    el.style.display = 'block';
    const box = document.createElement('div');
    box.className = 'palette-box';
    el.appendChild(box);

    const input = document.createElement('input');
    input.placeholder = 'Search to-dos, jobs, people, chats, memory…';
    input.setAttribute('aria-label', 'Command palette');
    input.name = 'palette-query';
    input.className = 'palette-input';
    box.appendChild(input);

    const list = document.createElement('div');
    list.className = 'palette-list';
    box.appendChild(list);

    el.onclick = ev => { if (ev.target === el) closePalette(); };
    popPaletteLayer = pushLayer(() => closePalette());

    const index = await api('/api/palette-index');
    let flatItems = [];
    let selected = 0;
    let memoryResults = [];
    let memoryDebounce = null;

    function group(label, items) {
      if (!items.length) return;
      const heading = document.createElement('div');
      heading.textContent = label;
      heading.className = 'palette-group-heading';
      list.appendChild(heading);
      items.forEach(item => {
        const idx = flatItems.length;
        flatItems.push(item);
        const row = document.createElement('div');
        row.dataset.idx = String(idx);
        row.className = 'palette-row';
        const kind = PALETTE_KINDS[item.kind || 'action'];
        const tile = document.createElement('span');
        tile.className = 'palette-tile';
        tile.style.setProperty('--tile', kind.color);
        tile.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + kind.icon + '</svg>';
        row.appendChild(tile);
        const text = document.createElement('span');
        text.className = 'palette-text';
        text.textContent = item.label;
        row.appendChild(text);
        if (item.sub) {
          const sub = document.createElement('span');
          sub.className = 'palette-sub';
          sub.textContent = item.sub;
          row.appendChild(sub);
        }
        const type = document.createElement('span');
        type.className = 'palette-type';
        type.textContent = kind.label;
        row.appendChild(type);
        row.onclick = () => item.run();
        list.appendChild(row);
      });
    }

    function highlight() {
      list.querySelectorAll('[data-idx]').forEach(row => {
        const isSelected = Number(row.dataset.idx) === selected;
        row.classList.toggle('selected', isSelected);
        if (isSelected) row.scrollIntoView({block: 'nearest'});
      });
    }

    function paint() {
      list.innerHTML = '';
      flatItems = [];
      const query = input.value.trim();

      const rank = (items, textOf) => (!query ? [] : items
        .map(it => ({item: it, score: fuzzyScore(query, textOf(it))}))
        .filter(r => r.score >= 0)
        .sort((a, b) => b.score - a.score)
        .map(r => r.item));

      const projects = rank(index.projects, p => p.name);
      const todos = rank(index.tasks || [], t => t.title);
      const jobs = rank(index.jobs || [], a => a.company + ' ' + a.role);
      const people = rank(index.people || [], p => p.name + ' ' + p.context);
      const chats = rank(index.chats, c => c.title);
      const nodes = rank(index.roadmap_nodes, n => n.title);
      const actions = paletteActions()
        .filter(a => !query || fuzzyScore(query, a.label) >= 0);

      group('To-dos', todos.slice(0, PALETTE_MAX_PER_GROUP).map(t => ({
        kind: 'todo', label: t.title, sub: t.due_date ? fmtShortDate(t.due_date) : '',
        run: () => { closePalette(); openTasksView(); },
      })));
      group('Jobs', jobs.slice(0, PALETTE_MAX_PER_GROUP).map(a => ({
        kind: 'job', label: a.company, sub: a.role,
        run: () => { closePalette(); openJobsView(a.id); },
      })));
      group('People', people.slice(0, PALETTE_MAX_PER_GROUP).map(p => ({
        kind: 'person', label: p.name, sub: p.context,
        run: () => { closePalette(); openPeopleView(); },
      })));
      group('Projects', projects.slice(0, PALETTE_MAX_PER_GROUP).map(p => ({
        kind: 'project', label: p.name,
        run: () => { closePalette(); openProject(p.id); },
      })));
      group('Chats', chats.slice(0, PALETTE_MAX_PER_GROUP).map(c => ({
        kind: 'chat', label: c.title, sub: c.project_name || '',
        run: () => { closePalette(); showChatView(); openConversation(c.id); },
      })));
      group('Roadmap steps', nodes.slice(0, PALETTE_MAX_PER_GROUP).map(n => ({
        kind: 'step', label: n.title, sub: n.project_name,
        run: () => { closePalette(); openRoadmapView(n.project_id, n.project_name); },
      })));
      group('Memory entries', memoryResults.slice(0, PALETTE_MAX_PER_GROUP).map(r => ({
        kind: 'memory', label: r.query,
        run: () => {
          closePalette();
          if (r.kind === 'journal') { openJournalView(r.topic); return; }
          showChatView();
          openConversation(r.conversation_id);
        },
      })));
      group('Actions', actions);

      if (!flatItems.length) {
        const empty = document.createElement('div');
        empty.textContent = query ? 'No matches.' : 'Type to search, or pick an action below.';
        empty.className = 'palette-empty';
        list.appendChild(empty);
      }
      selected = Math.min(selected, Math.max(flatItems.length - 1, 0));
      highlight();
    }

    input.addEventListener('input', () => {
      const query = input.value.trim();
      clearTimeout(memoryDebounce);
      selected = 0;
      if (!query) { memoryResults = []; paint(); return; }
      // Paint immediately with whatever's already known (fuzzy groups and
      // actions cost nothing) - the memory-entries group fills in once
      // the debounced /api/search call actually resolves.
      paint();
      memoryDebounce = setTimeout(async () => {
        const data = await api('/api/search?q=' + encodeURIComponent(query));
        if (input.value.trim() !== query) return; // a newer keystroke already won
        memoryResults = data.results || [];
        paint();
      }, PALETTE_MEMORY_DEBOUNCE_MS);
    });

    input.addEventListener('keydown', ev => {
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        if (flatItems.length) { selected = (selected + 1) % flatItems.length; highlight(); }
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        if (flatItems.length) {
          selected = (selected - 1 + flatItems.length) % flatItems.length;
          highlight();
        }
      } else if (ev.key === 'Enter') {
        ev.preventDefault();
        const item = flatItems[selected];
        if (item) item.run();
      }
      // Escape is deliberately not handled here - the layer stack owns
      // dismissal so only the topmost open layer (this palette) closes.
    });

    paint();
    input.focus();
  }

  // ---------- keyboard bindings (single source of truth) ----------
  // Every bare-key or modifier shortcut in the app is declared exactly
  // once here. Two things fall out of that: the '?' overlay below is
  // *generated* from this table instead of hand-typed, so it can never
  // drift from what actually fires, and the "don't fire while typing"
  // guard lives in one place rather than being copy-pasted at every call
  // site that happens to bind a bare key - get it right here once, and
  // typing "?" into the composer or any other field can never open the
  // overlay by accident.
  const KEY_BINDINGS = [
    {
      keys: 'Cmd/Ctrl+K',
      label: 'Open command palette',
      allowWhileTyping: true, // a global open shortcut works from anywhere, Raycast-style
      test: ev => (ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k',
      run: () => openPalette(),
    },
    {
      keys: 'Cmd/Ctrl+1–9',
      label: 'Go to Today, Week, To-dos, Habits, Journal, People, Jobs, Practice, Stories',
      allowWhileTyping: true,
      test: ev => (ev.metaKey || ev.ctrlKey) && !ev.shiftKey && !ev.altKey && /^[1-9]$/.test(ev.key),
      run: ev => $(['open-today', 'open-week', 'open-tasks', 'open-habits', 'open-journal',
                    'open-people', 'open-jobs', 'open-practice', 'open-stories'][Number(ev.key) - 1]).click(),
    },
    {
      keys: 'Cmd/Ctrl+N',
      label: 'New to-do',
      allowWhileTyping: true,
      test: ev => (ev.metaKey || ev.ctrlKey) && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === 'n',
      run: () => quickAddTask(),
    },
    {
      keys: 'Cmd/Ctrl+,',
      label: 'Open settings',
      allowWhileTyping: true,
      test: ev => (ev.metaKey || ev.ctrlKey) && ev.key === ',',
      run: () => openProfileView(),
    },
    {
      keys: 'Cmd/Ctrl+[ and ]',
      label: 'Back and forward',
      allowWhileTyping: true,
      test: ev => (ev.metaKey || ev.ctrlKey) && (ev.key === '[' || ev.key === ']'),
      run: ev => $(ev.key === '[' ? 'nav-back' : 'nav-fwd').click(),
    },
    {
      keys: '?',
      label: 'Show keyboard shortcuts',
      allowWhileTyping: false, // a bare key must not hijack typing a literal "?"
      test: ev => ev.key === '?' && !ev.metaKey && !ev.ctrlKey && !ev.altKey,
      run: () => openShortcutsOverlay(),
    },
  ];

  document.addEventListener('keydown', ev => {
    for (const binding of KEY_BINDINGS) {
      if (!binding.test(ev)) continue;
      if (!binding.allowWhileTyping && isTypingTarget(ev.target)) continue;
      ev.preventDefault();
      binding.run(ev);
      return;
    }
  });

  let shortcutsTrigger = null;
  let popShortcutsLayer = null;

  function closeShortcutsOverlay() {
    const el = $('shortcuts');
    if (el.style.display !== 'block') return;
    el.style.display = 'none';
    el.innerHTML = '';
    if (popShortcutsLayer) { popShortcutsLayer(); popShortcutsLayer = null; }
    const trigger = shortcutsTrigger;
    shortcutsTrigger = null;
    if (trigger && typeof trigger.focus === 'function') trigger.focus();
  }

  function openShortcutsOverlay() {
    const el = $('shortcuts');
    if (el.style.display === 'block') return;
    shortcutsTrigger = document.activeElement;
    el.innerHTML = '';
    // Styling lives in app.css (.shortcuts-*).
    el.style.display = 'block';
    const box = document.createElement('div');
    box.className = 'shortcuts-box';
    el.appendChild(box);

    const h = document.createElement('h3');
    h.textContent = 'Keyboard shortcuts';
    h.className = 'shortcuts-title';
    box.appendChild(h);

    // Generated straight from KEY_BINDINGS, not retyped - see the banner
    // comment above the table for why that's the whole point.
    KEY_BINDINGS.forEach(b => {
      const row = document.createElement('div');
      row.className = 'shortcuts-row';
      const label = document.createElement('span');
      label.textContent = b.label;
      const key = document.createElement('span');
      key.textContent = b.keys;
      key.className = 'shortcuts-key';
      row.appendChild(label);
      row.appendChild(key);
      box.appendChild(row);
    });

    // Not table-driven: these belong to the palette's own listbox
    // interaction, not to a global bare-key binding that could drift.
    const hint = document.createElement('div');
    hint.textContent =
      'While the palette is open: ↑↓ to navigate, Enter to run, Esc to close.';
    hint.className = 'shortcuts-hint';
    box.appendChild(hint);

    el.onclick = ev => { if (ev.target === el) closeShortcutsOverlay(); };
    popShortcutsLayer = pushLayer(() => closeShortcutsOverlay());
  }

