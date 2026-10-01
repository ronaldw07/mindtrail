
  // ---------- life areas, habits, journal ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.

  let lifeAreas = [];  // [{id, name, color, sort}], refreshed with the sidebar

  async function loadAreas() {
    const data = await api('/api/areas');
    lifeAreas = data.areas || [];
    return lifeAreas;
  }

  const areaById = id => lifeAreas.find(a => a.id === id) || null;

  function areaDot(areaId) {
    const area = areaById(areaId);
    if (!area) return null;
    const dot = document.createElement('span');
    dot.className = 'area-dot';
    dot.style.background = area.color;
    dot.title = area.name;
    return dot;
  }

  async function pickArea(title, currentId) {
    const choice = await modal({
      title, select: [{value: '', label: 'None'}].concat(
        lifeAreas.map(a => ({value: a.id, label: a.name}))),
      value: currentId || '', confirmLabel: 'Save',
    });
    return choice;  // null if cancelled, '' for none
  }

  async function setProjectArea(p) {
    const areaId = await pickArea('Life area for "' + p.name + '"', p.area_id);
    if (areaId === null) return;
    const res = await jsonSend('/api/projects/' + p.id + '/area', {area_id: areaId}, 'PATCH');
    if (res.error) { toast(res.error, {error: true}); return; }
    await loadSidebar();
  }

  function areasCard() {
    const c = card('Life areas', '+ Add', async () => {
      const name = await askText('New life area', '', 'e.g. Family');
      if (!name) return;
      const res = await jsonSend('/api/areas', {name});
      if (res.error) { toast(res.error, {error: true}); return; }
      await loadAreas();
      c.replaceWith(areasCard());
    });
    const hint = document.createElement('div');
    hint.className = 'muted area-hint';
    hint.textContent = 'Tag projects, to-dos, and habits so Today can show where your week went.';
    c.appendChild(hint);
    lifeAreas.forEach(a => {
      const row = document.createElement('div');
      row.className = 'area-row';
      const color = document.createElement('input');
      color.type = 'color';
      color.value = a.color;
      color.className = 'area-color';
      color.setAttribute('aria-label', a.name + ' color');
      const name = document.createElement('input');
      name.className = 'job-field-input';
      name.value = a.name;
      name.setAttribute('aria-label', 'Area name');
      const save = async () => {
        const res = await jsonSend('/api/areas/' + a.id,
          {name: name.value, color: color.value}, 'PATCH');
        if (res.error) { toast(res.error, {error: true}); name.value = a.name; return; }
        await loadSidebar();
      };
      color.addEventListener('change', save);
      name.addEventListener('change', save);
      const del = document.createElement('button');
      del.className = 'nav-btn';
      del.textContent = '×';
      del.setAttribute('aria-label', 'Delete ' + a.name);
      del.onclick = async () => {
        if (!await askConfirm('Delete area', 'Untag everything in "' + a.name
            + '" and remove the area?', 'Delete')) return;
        await api('/api/areas/' + a.id, {method: 'DELETE'});
        await loadSidebar();
        c.replaceWith(areasCard());
      };
      row.appendChild(color);
      row.appendChild(name);
      row.appendChild(del);
      c.appendChild(row);
    });
    return c;
  }

  // ---------- to-dos view ----------

  const localISO = d => d.toLocaleDateString('en-CA');  // YYYY-MM-DD, local
  const addDays = (iso, n) => {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() + n);
    return localISO(d);
  };

  function taskGroup(t, today) {
    if (t.done) return 'done';
    if (!t.due_date) return 'someday';
    if (t.due_date < today) return 'overdue';
    if (t.due_date === today) return 'today';
    if (t.due_date <= addDays(today, 7)) return 'week';
    return 'later';
  }

  const TASK_GROUPS = [
    ['overdue', 'Overdue'], ['today', 'Today'], ['week', 'Next 7 days'],
    ['later', 'Later'], ['someday', 'No date'], ['done', 'Done this week'],
  ];

  async function openTasksView() {
    currentProject = null;
    current = null;
    setActiveView('tasks');
    prefs.set('lastView', {type: 'tasks'});
    $('breadcrumb').textContent = 'To-dos';
    await renderTasksView();
  }

  async function renderTasksView(focusAdd) {
    const data = await api('/api/tasks?all=1');
    const view = $('tasks-view');
    view.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'brief-wrap';
    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'To-dos';
    wrap.appendChild(title);

    const form = document.createElement('form');
    form.className = 'task-add task-add-wide';
    const input = document.createElement('input');
    input.className = 'jobs-link-input';
    input.placeholder = 'Add a to-do — try “Call mom tmrw” or “Taxes oct 12”';
    input.setAttribute('aria-label', 'New to-do');
    form.appendChild(input);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!input.value.trim()) return;
      const res = await jsonSend('/api/tasks', {title: input.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderTasksView(true);
    };
    wrap.appendChild(form);

    const today = localISO(new Date());
    const weekAgo = addDays(today, -7);
    const tasks = data.tasks.filter(t => !t.done || (t.done_at || '').slice(0, 10) >= weekAgo);
    const showDone = prefs.get('tasksShowDone', false);
    TASK_GROUPS.forEach(([key, label]) => {
      const items = tasks.filter(t => taskGroup(t, today) === key);
      if (!items.length) return;
      const head = document.createElement('div');
      head.className = 'brief-section-label task-group-head';
      head.textContent = label + ' · ' + items.length;
      if (key === 'done') {
        makeClickable(head, () => { prefs.set('tasksShowDone', !showDone); renderTasksView(); });
        head.textContent += showDone ? '  ▾' : '  ▸';
      }
      wrap.appendChild(head);
      if (key === 'done' && !showDone) return;
      items.forEach(t => wrap.appendChild(inboxRow(t, key === 'overdue')));
    });
    if (!tasks.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'Nothing to do. Add one above.';
      wrap.appendChild(empty);
    }
    view.appendChild(wrap);
    if (focusAdd) wrap.querySelector('.jobs-link-input').focus();
  }

  function inboxRow(t, overdue) {
    const row = taskRow(t, () => renderTasksView());
    if (overdue) row.classList.add('overdue');
    const dot = areaDot(t.area_id);
    if (dot) row.insertBefore(dot, row.children[1]);
    if (t.application_id) {
      const chip = document.createElement('span');
      chip.className = 'job-chip task-job-chip';
      chip.textContent = 'Job';
      chip.onclick = () => openJobsView(t.application_id);
      row.querySelector('.task-body').appendChild(chip);
    }
    const more = document.createElement('button');
    more.className = 'menu-btn task-more';
    more.textContent = '⋯';
    more.setAttribute('aria-label', 'To-do options');
    more.onclick = e => { e.stopPropagation(); openTaskMenu(e, t); };
    row.appendChild(more);
    return row;
  }

  function openTaskMenu(e, t) {
    const update = async fields => {
      const res = await jsonSend('/api/tasks/' + t.id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderTasksView();
    };
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const title = await askText('Rename to-do', t.title);
        if (title) await update({title});
      }},
      {label: 'Set due date', run: async () => {
        const due = await modal({title: 'Due date', input: true, inputType: 'date',
                                 value: t.due_date, confirmLabel: 'Save'});
        if (due) await update({due_date: due});
      }},
      ...(t.due_date ? [{label: 'Clear due date', run: () => update({due_date: ''})}] : []),
      {label: 'Set life area…', run: async () => {
        const areaId = await pickArea('Life area', t.area_id);
        if (areaId !== null) await update({area_id: areaId});
      }},
      {divider: true},
      {label: 'Delete', danger: true, run: async () => {
        await api('/api/tasks/' + t.id, {method: 'DELETE'});
        await renderTasksView();
        toast('To-do deleted');
      }},
    ]);
  }

  // ---------- habits view ----------

  const HABIT_TARGETS = [7, 6, 5, 4, 3, 2, 1];
  const targetLabel = n => n >= 7 ? 'Every day' : n + '× a week';
  // Same first slot as the area palette (see organize/areas.py).
  const HABIT_DEFAULT_COLOR = '#3987e5';
  const habitColor = h => (areaById(h.area_id) || {}).color || HABIT_DEFAULT_COLOR;

  function habitMeta(h) {
    const unit = h.unit === 'day' ? 'day' : 'week';
    const s = h.streak ? h.streak + '-' + unit + ' streak' : 'No streak yet';
    return h.unit === 'day' ? s : s + ' · ' + h.this_week + ' of ' + h.target_per_week + ' this week';
  }

  async function toggleHabit(h, day) {
    const res = await jsonSend('/api/habits/' + h.id + '/toggle', day ? {date: day} : {});
    if (res.error) toast(res.error, {error: true});
    return res;
  }

  async function openHabitsView() {
    currentProject = null;
    current = null;
    setActiveView('habits');
    prefs.set('lastView', {type: 'habits'});
    $('breadcrumb').textContent = 'Habits';
    await renderHabitsView();
  }

  async function renderHabitsView() {
    const showArchived = prefs.get('habitsShowArchived', false);
    const data = await api('/api/habits' + (showArchived ? '?archived=1' : ''));
    const view = $('habits-view');
    view.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'brief-wrap habits-wrap';
    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'Habits';
    wrap.appendChild(title);
    wrap.appendChild(habitAddForm());

    data.habits.forEach(h => wrap.appendChild(habitCard(h, data)));
    if (!data.habits.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No habits yet. Add one above — “Read 20 min”, “ARC 3× a week”.';
      wrap.appendChild(empty);
    }
    const toggle = document.createElement('button');
    toggle.className = 'btn-ghost jobs-closed-toggle';
    toggle.textContent = showArchived ? 'Hide archived' : 'Show archived';
    toggle.onclick = () => { prefs.set('habitsShowArchived', !showArchived); renderHabitsView(); };
    wrap.appendChild(toggle);
    view.appendChild(wrap);
  }

  function habitAddForm() {
    const form = document.createElement('form');
    form.className = 'task-add task-add-wide habit-add';
    const name = document.createElement('input');
    name.className = 'jobs-link-input';
    name.placeholder = 'New habit';
    name.setAttribute('aria-label', 'Habit name');
    const target = document.createElement('select');
    target.className = 'job-field-input habit-select';
    target.setAttribute('aria-label', 'How often');
    HABIT_TARGETS.forEach(n => {
      const o = document.createElement('option');
      o.value = String(n);
      o.textContent = targetLabel(n);
      target.appendChild(o);
    });
    const area = document.createElement('select');
    area.className = 'job-field-input habit-select';
    area.setAttribute('aria-label', 'Life area');
    [{id: '', name: 'No area'}].concat(lifeAreas).forEach(a => {
      const o = document.createElement('option');
      o.value = a.id;
      o.textContent = a.name;
      area.appendChild(o);
    });
    const add = document.createElement('button');
    add.className = 'btn-primary jobs-btn';
    add.type = 'submit';
    add.textContent = 'Add';
    [name, target, area, add].forEach(el => form.appendChild(el));
    form.onsubmit = async e => {
      e.preventDefault();
      if (!name.value.trim()) return;
      const res = await jsonSend('/api/habits', {
        name: name.value, target_per_week: Number(target.value), area_id: area.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderHabitsView();
    };
    return form;
  }

  function habitCard(h, data) {
    const c = document.createElement('div');
    c.className = 'card habit-card' + (h.archived ? ' archived' : '');
    const head = document.createElement('div');
    head.className = 'habit-head';
    const check = document.createElement('button');
    check.className = 'task-check habit-check';
    check.setAttribute('aria-pressed', h.done_today ? 'true' : 'false');
    check.setAttribute('aria-label', (h.done_today ? 'Undo today: ' : 'Done today: ') + h.name);
    check.onclick = async () => { await toggleHabit(h); renderHabitsView(); };
    head.appendChild(check);
    const body = document.createElement('div');
    body.className = 'habit-body';
    const name = document.createElement('div');
    name.className = 'habit-name';
    const dot = areaDot(h.area_id);
    if (dot) name.appendChild(dot);
    name.appendChild(document.createTextNode(h.name));
    body.appendChild(name);
    const meta = document.createElement('div');
    meta.className = 'habit-meta';
    meta.textContent = targetLabel(h.target_per_week) + ' · ' + habitMeta(h);
    body.appendChild(meta);
    head.appendChild(body);
    const more = document.createElement('button');
    more.className = 'menu-btn task-more';
    more.textContent = '⋯';
    more.setAttribute('aria-label', 'Habit options');
    more.onclick = e => openHabitMenu(e, h);
    head.appendChild(more);
    c.appendChild(head);
    c.appendChild(habitHeatmap(h, data));
    return c;
  }

  // 52 weeks × 7 days, Monday on top, one column per week - the GitHub
  // contribution layout. One hue per habit (its area's), so it's a single
  // series: no legend, the card title names it. Cells in the last week
  // are clickable to backfill a missed check-in; the server enforces the
  // same window.
  function habitHeatmap(h, data) {
    const done = new Set(h.logs);
    const today = data.today;
    const first = addDays(today, -((new Date(today + 'T12:00:00').getDay() + 6) % 7)
                                 - 7 * (data.heatmap_weeks - 1));
    const grid = document.createElement('div');
    grid.className = 'heatmap';
    grid.style.setProperty('--habit-color', habitColor(h));
    grid.setAttribute('role', 'img');
    grid.setAttribute('aria-label', h.name + ': done ' + h.logs.length + ' times in the last '
      + data.heatmap_weeks + ' weeks');
    const editableFrom = addDays(today, -7);
    for (let w = 0; w < data.heatmap_weeks; w++) {
      for (let d = 0; d < 7; d++) {
        const day = addDays(first, w * 7 + d);
        const cell = document.createElement('div');
        cell.className = 'heat-cell';
        cell.style.gridColumn = String(w + 1);
        cell.style.gridRow = String(d + 1);
        if (day > today) { cell.classList.add('future'); grid.appendChild(cell); continue; }
        const isDone = done.has(day);
        if (isDone) cell.classList.add('on');
        if (day === today) cell.classList.add('today');
        cell.title = fmtShortDate(day) + (isDone ? ' — done' : '');
        if (day >= editableFrom) {
          cell.classList.add('editable');
          cell.onclick = async () => { await toggleHabit(h, day); renderHabitsView(); };
        }
        grid.appendChild(cell);
      }
    }
    return grid;
  }

  function openHabitMenu(e, h) {
    const update = async fields => {
      const res = await jsonSend('/api/habits/' + h.id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderHabitsView();
    };
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const name = await askText('Rename habit', h.name);
        if (name) await update({name});
      }},
      {label: 'How often…', run: async () => {
        const n = await modal({title: 'How often', confirmLabel: 'Save', value: h.target_per_week,
          select: HABIT_TARGETS.map(t => ({value: t, label: targetLabel(t)}))});
        if (n !== null) await update({target_per_week: Number(n)});
      }},
      {label: 'Set life area…', run: async () => {
        const areaId = await pickArea('Life area', h.area_id);
        if (areaId !== null) await update({area_id: areaId});
      }},
      {label: h.archived ? 'Unarchive' : 'Archive', run: () => update({archived: !h.archived})},
      {divider: true},
      {label: 'Delete', danger: true, run: async () => {
        if (!await askConfirm('Delete habit', 'Delete "' + h.name
            + '" and its whole history? Archive keeps the history.', 'Delete')) return;
        await api('/api/habits/' + h.id, {method: 'DELETE'});
        await renderHabitsView();
      }},
    ]);
  }

  // Today's compact version: one tap per habit, streak alongside.
  function habitsTodayCard(habits) {
    const c = card('Habits', 'All habits', () => openHabitsView());
    if (!habits.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No habits yet — add one from the Habits page.';
      c.appendChild(p);
      return c;
    }
    const list = document.createElement('div');
    list.className = 'habit-today-list';
    habits.forEach(h => {
      const row = document.createElement('div');
      row.className = 'habit-today' + (h.done_today ? ' done' : '');
      const check = document.createElement('button');
      check.className = 'task-check';
      check.setAttribute('aria-pressed', h.done_today ? 'true' : 'false');
      check.setAttribute('aria-label', (h.done_today ? 'Undo today: ' : 'Done today: ') + h.name);
      check.onclick = async () => {
        const res = await toggleHabit(h);
        if (res.error) return;
        h.done_today = res.logged;
        check.setAttribute('aria-pressed', res.logged ? 'true' : 'false');
        row.classList.toggle('done', res.logged);
      };
      row.appendChild(check);
      const name = document.createElement('div');
      name.className = 'habit-today-name';
      name.textContent = h.name;
      row.appendChild(name);
      const meta = document.createElement('div');
      meta.className = 'habit-today-meta';
      meta.textContent = h.streak ? h.streak + (h.unit === 'day' ? 'd' : 'w') : '';
      row.appendChild(meta);
      list.appendChild(row);
    });
    c.appendChild(list);
    return c;
  }

  // ---------- journal view ----------

  const MOOD_LABELS = ['Rough', 'Low', 'Okay', 'Good', 'Great'];
  const ENERGY_LABELS = ['Drained', 'Low', 'Steady', 'Good', 'Charged'];
  const JOURNAL_SAVE_DELAY_MS = 900;
  let journalDay = null;
  let journalPending = null;  // {timer, flush} for the unsaved edit, if any

  async function openJournalView(day) {
    currentProject = null;
    current = null;
    setActiveView('journal');
    prefs.set('lastView', {type: 'journal'});
    $('breadcrumb').textContent = 'Journal';
    if (journalPending) await journalPending.flush();
    journalDay = day || null;
    await renderJournalView();
  }

  async function renderJournalView() {
    const data = await api('/api/journal' + (journalDay ? '?date=' + journalDay : ''));
    if (data.error) { toast(data.error, {error: true}); journalDay = null; return renderJournalView(); }
    const entry = data.entry;
    journalDay = entry.date;
    const view = $('journal-view');
    view.innerHTML = '';
    const layout = document.createElement('div');
    layout.className = 'proj-layout';
    const main = document.createElement('div');
    main.className = 'proj-main journal-main';

    const nav = document.createElement('div');
    nav.className = 'journal-nav';
    const prev = document.createElement('button');
    prev.className = 'nav-btn';
    prev.textContent = '←';
    prev.setAttribute('aria-label', 'Previous day');
    prev.onclick = () => openJournalView(addDays(entry.date, -1));
    const next = document.createElement('button');
    next.className = 'nav-btn';
    next.textContent = '→';
    next.setAttribute('aria-label', 'Next day');
    next.disabled = entry.date >= data.today;
    next.onclick = () => openJournalView(addDays(entry.date, 1));
    const heading = document.createElement('div');
    heading.className = 'proj-title journal-date';
    heading.textContent = entry.date === data.today ? 'Today'
      : new Date(entry.date + 'T12:00:00').toLocaleDateString(undefined,
          {weekday: 'long', month: 'long', day: 'numeric'});
    nav.appendChild(prev);
    nav.appendChild(heading);
    nav.appendChild(next);
    if (entry.date !== data.today) {
      const back = document.createElement('button');
      back.className = 'btn-ghost jobs-btn';
      back.textContent = 'Today';
      back.onclick = () => openJournalView(null);
      nav.appendChild(back);
    }
    main.appendChild(nav);

    const state = {body: entry.body, mood: entry.mood, energy: entry.energy};
    const status = document.createElement('div');
    status.className = 'journal-status';

    const save = async () => {
      journalPending = null;
      status.textContent = 'Saving…';
      const res = await jsonSend('/api/journal', {date: entry.date, ...state});
      status.textContent = res.error ? 'Not saved: ' + res.error : 'Saved';
    };
    const schedule = () => {
      status.textContent = 'Editing…';
      if (journalPending) clearTimeout(journalPending.timer);
      journalPending = {timer: setTimeout(save, JOURNAL_SAVE_DELAY_MS),
                        flush: async () => { clearTimeout(journalPending.timer); await save(); }};
    };

    main.appendChild(ratingRow('Mood', MOOD_LABELS, state.mood, v => { state.mood = v; schedule(); }));
    main.appendChild(ratingRow('Energy', ENERGY_LABELS, state.energy, v => { state.energy = v; schedule(); }));

    const prompts = document.createElement('div');
    prompts.className = 'journal-prompts';
    data.prompts.forEach(p => {
      const b = document.createElement('button');
      b.className = 'journal-prompt';
      b.textContent = p;
      b.onclick = () => {
        const sep = box.value && !box.value.endsWith('\n') ? '\n\n' : '';
        box.value += sep + p + '\n';
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
        state.body = box.value;
        schedule();
      };
      prompts.appendChild(b);
    });
    main.appendChild(prompts);

    const box = document.createElement('textarea');
    box.className = 'journal-box';
    box.value = entry.body;
    box.placeholder = 'Write anything. It saves as you type, and chat can find it later.';
    box.setAttribute('aria-label', 'Journal entry');
    box.addEventListener('input', () => { state.body = box.value; schedule(); });
    box.addEventListener('blur', () => { if (journalPending) journalPending.flush(); });
    main.appendChild(box);
    main.appendChild(status);
    layout.appendChild(main);

    const rail = document.createElement('div');
    rail.className = 'proj-rail';
    const past = card('Past entries', null, null);
    if (!data.recent.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing yet.';
      past.appendChild(p);
    }
    data.recent.forEach(e => {
      const row = document.createElement('div');
      row.className = 'journal-past' + (e.date === entry.date ? ' current' : '');
      const top = document.createElement('div');
      top.className = 'journal-past-date';
      top.textContent = fmtShortDate(e.date) + (e.mood ? ' · ' + MOOD_LABELS[e.mood - 1] : '');
      row.appendChild(top);
      if (e.preview) {
        const prev = document.createElement('div');
        prev.className = 'journal-past-preview';
        prev.textContent = e.preview;
        row.appendChild(prev);
      }
      makeClickable(row, () => openJournalView(e.date));
      past.appendChild(row);
    });
    rail.appendChild(past);
    layout.appendChild(rail);
    view.appendChild(layout);
    if (!entry.body) box.focus();
  }

  // A radiogroup of five buttons; clicking the selected one clears it.
  function ratingRow(label, labels, value, onChange) {
    const row = document.createElement('div');
    row.className = 'rating-row';
    row.setAttribute('role', 'radiogroup');
    row.setAttribute('aria-label', label);
    const name = document.createElement('span');
    name.className = 'rating-label';
    name.textContent = label;
    row.appendChild(name);
    let current = value;
    const buttons = labels.map((text, i) => {
      const b = document.createElement('button');
      b.className = 'rating-btn';
      b.textContent = text;
      b.setAttribute('role', 'radio');
      b.onclick = () => {
        current = current === i + 1 ? 0 : i + 1;
        paint();
        onChange(current);
      };
      row.appendChild(b);
      return b;
    });
    const paint = () => buttons.forEach((b, i) => {
      b.setAttribute('aria-checked', current === i + 1 ? 'true' : 'false');
    });
    paint();
    return row;
  }

  function journalTodayCard(journal) {
    const c = card('Journal', journal && journal.written_today ? 'Open' : null,
                   () => openJournalView(null));
    const p = document.createElement('div');
    if (journal && journal.written_today) {
      p.className = 'muted';
      p.textContent = 'Written today.';
      c.appendChild(p);
    } else {
      const btn = document.createElement('button');
      btn.className = 'btn-primary jobs-btn';
      btn.textContent = 'Write today’s entry';
      btn.onclick = () => openJournalView(null);
      c.appendChild(btn);
    }
    return c;
  }
