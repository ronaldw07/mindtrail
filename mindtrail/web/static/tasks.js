
  // ---------- to-dos view ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Reminders layout: four filter tiles with counts, grouped lists, and an
  // inspector for the details of one to-do.

  const TASK_FILTERS = [
    {key: 'today', label: 'Today', color: '#0071e3',
     icon: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 3v4M16 3v4"/>'},
    {key: 'scheduled', label: 'Scheduled', color: '#d70015',
     icon: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'},
    {key: 'all', label: 'All', color: '#636366',
     icon: '<path d="M4 6h16M4 12h16M4 18h16"/>'},
    {key: 'done', label: 'Done', color: '#248a3d', icon: '<path d="M5 12l5 5 9-10"/>'},
  ];

  const TASK_GROUPS = [
    ['overdue', 'Overdue'], ['today', 'Today'], ['week', 'Next 7 days'],
    ['later', 'Later'], ['someday', 'No date'],
  ];

  let tasksSelectedId = null;   // to-do open in the inspector

  function taskGroup(t, today) {
    if (!t.due_date) return 'someday';
    if (t.due_date < today) return 'overdue';
    if (t.due_date === today) return 'today';
    if (t.due_date <= addDays(today, 7)) return 'week';
    return 'later';
  }

  function taskFilterMatch(key, t, today) {
    if (key === 'done') return t.done;
    if (t.done) return false;
    if (key === 'today') return !!t.due_date && t.due_date <= today;
    if (key === 'scheduled') return !!t.due_date;
    return true;
  }

  async function openTasksView() {
    currentProject = null;
    current = null;
    setActiveView('tasks');
    prefs.set('lastView', {type: 'tasks'});
    $('breadcrumb').textContent = 'To-dos';
    await renderTasksView();
  }

  async function renderTasksView(focusAdd) {
    closeTaskCard();
    const data = await api('/api/tasks?all=1');
    const view = $('tasks-view');
    const today = localISO(new Date());
    const weekAgo = addDays(today, -7);
    const tasks = data.tasks.filter(t => !t.done || (t.done_at || '').slice(0, 10) >= weekAgo);
    const filter = prefs.get('tasksFilter', 'all');
    if (tasksSelectedId && !tasks.some(t => t.id === tasksSelectedId)) tasksSelectedId = null;

    const layout = tEl('div', 'tasks-layout');
    const main = tEl('div', 'tasks-main');
    main.appendChild(tEl('div', 'proj-title', 'To-dos'));
    main.appendChild(taskTiles(tasks, today, filter));
    main.appendChild(taskAddForm());

    if (filter === 'done') {
      const done = tasks.filter(t => t.done)
        .sort((a, b) => (b.done_at || '').localeCompare(a.done_at || ''));
      if (done.length) main.appendChild(taskGroupList('Done this week', done, false));
    } else {
      TASK_GROUPS.forEach(([key, label]) => {
        const items = tasks.filter(t => taskFilterMatch(filter, t, today) && taskGroup(t, today) === key);
        if (items.length) main.appendChild(taskGroupList(label, items, key === 'overdue'));
      });
    }
    if (!main.querySelector('.group-list')) {
      main.appendChild(emptyState('todo', filter === 'done' ? 'Nothing finished yet' : 'All clear',
        filter === 'done' ? 'To-dos you check off this week show up here.'
                          : 'Add a to-do above — try “Call mom tmrw” or “Taxes oct 12”.'));
    }
    layout.appendChild(main);
    const selected = tasks.find(t => t.id === tasksSelectedId);
    if (selected) layout.appendChild(taskInspector(selected));
    commitView(view, layout);
    if (focusAdd) layout.querySelector('.task-add-input').focus();
    loadBadges();
  }

  function taskTiles(tasks, today, filter) {
    const row = tEl('div', 'filter-tiles');
    TASK_FILTERS.forEach(f => {
      const count = tasks.filter(t => taskFilterMatch(f.key, t, today)).length;
      const tile = tEl('button', 'filter-tile' + (f.key === filter ? ' active' : ''));
      tile.type = 'button';
      tile.setAttribute('aria-pressed', f.key === filter ? 'true' : 'false');
      const icon = tEl('span', 'filter-icon');
      icon.style.setProperty('--tile', f.color);
      icon.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + f.icon + '</svg>';
      tile.appendChild(icon);
      const n = tEl('span', 'filter-count', String(count));
      tile.appendChild(n);
      tile.appendChild(tEl('span', 'filter-label', f.label));
      tile.onclick = () => { prefs.set('tasksFilter', f.key); renderTasksView(); };
      row.appendChild(tile);
    });
    return row;
  }

  function taskAddForm() {
    const form = tEl('form', 'task-add task-add-wide');
    const input = tEl('input', 'task-add-input');
    input.placeholder = 'New to-do — try “Call mom tmrw” or “Water plants every mon”';
    input.setAttribute('aria-label', 'New to-do');
    form.appendChild(input);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!input.value.trim()) return;
      const res = await jsonSend('/api/tasks', {title: input.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderTasksView(true);
    };
    return form;
  }

  function taskGroupList(label, items, overdue) {
    const section = tEl('section', 'group-section');
    section.appendChild(tEl('div', 'group-title' + (overdue ? ' overdue' : ''), label + ' · ' + items.length));
    const list = tEl('div', 'group-list');
    items.forEach(t => list.appendChild(inboxRow(t, overdue)));
    section.appendChild(list);
    return section;
  }

  function inboxRow(t, overdue) {
    const row = taskRow(t, () => renderTasksView());
    row.classList.add('group-row');
    if (overdue) row.classList.add('overdue');
    if (t.id === tasksSelectedId) row.classList.add('selected');
    const body = row.querySelector('.task-body');
    const due = body.querySelector('.task-due');
    if (due) body.appendChild(due);
    if (t.repeat_label) {
      const rep = tEl('span', 'task-repeat', '↻ ' + t.repeat_label);
      rep.title = 'Repeats';
      body.appendChild(rep);
    }
    const dot = areaDot(t.area_id);
    if (dot) body.appendChild(dot);
    if (t.application_id) {
      // The company, and that the job is closed if it is, so a stale to-do stands out.
      const job = t.job || {};
      const chip = tEl('span', 'job-chip task-job-chip' + (job.closed ? ' closed' : ''),
        (job.company || 'Job') + (job.closed ? ' · ' + capitalize(job.stage) : ''));
      chip.onclick = e => { e.stopPropagation(); openJobsView(t.application_id); };
      body.appendChild(chip);
    }
    body.classList.add('task-body-open');
    body.title = 'Show details';
    body.onclick = e => { e.stopPropagation(); openTaskCard(t, row); };
    const info = tEl('button', 'task-info');
    info.type = 'button';
    info.setAttribute('aria-label', 'Details for ' + t.title);
    info.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
      + 'stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
      + '<path d="M12 11v5"/><path d="M12 8h.01"/></svg>';
    info.onclick = e => {
      e.stopPropagation();
      tasksSelectedId = tasksSelectedId === t.id ? null : t.id;
      renderTasksView();
    };
    row.appendChild(info);
    return row;
  }

  const capitalize = w => (w || '').charAt(0).toUpperCase() + (w || '').slice(1);

  // A small box under a to-do: what it's for, the job and the email it
  // came from, with the email's start loaded on demand.
  let taskCard = null;
  function closeTaskCard() {
    if (!taskCard) return;
    taskCard.remove();
    taskCard = null;
    document.removeEventListener('pointerdown', taskCardOutside, true);
    document.removeEventListener('keydown', taskCardKey, true);
  }
  const taskCardOutside = e => { if (taskCard && !taskCard.contains(e.target)) closeTaskCard(); };
  const taskCardKey = e => { if (e.key === 'Escape') closeTaskCard(); };

  function openTaskCard(t, row) {
    const reopen = taskCard && taskCard.dataset.id === String(t.id);
    closeTaskCard();
    if (reopen) return;   // a second click on the same to-do closes it
    const card = tEl('div', 'task-card');
    card.dataset.id = t.id;
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'About ' + t.title);
    card.appendChild(tEl('div', 'task-card-title', t.title));
    const facts = tEl('div', 'task-card-facts');
    facts.appendChild(tEl('span', '', t.due_date ? 'Due ' + fmtShortDate(t.due_date) : 'No date'));
    if (t.repeat_label) facts.appendChild(tEl('span', '', '↻ ' + t.repeat_label));
    card.appendChild(facts);
    if (t.job) {
      const job = tEl('div', 'task-card-job');
      job.appendChild(tEl('div', 'task-card-company', t.job.company + (t.job.role ? ' — ' + t.job.role : '')));
      job.appendChild(tEl('span', 'task-card-stage' + (t.job.closed ? ' closed' : ''), capitalize(t.job.stage)));
      if (t.job.closed) job.appendChild(tEl('div', 'task-card-note', 'This job is closed, so this to-do may be stale.'));
      card.appendChild(job);
    }
    if (t.email) {
      const mail = tEl('div', 'task-card-email');
      mail.appendChild(tEl('div', 'task-card-label', 'From an email · ' + fmtShortDate((t.email.received_at || '').slice(0, 10))));
      mail.appendChild(tEl('div', 'task-card-subject', t.email.subject || '(no subject)'));
      const preview = tEl('div', 'task-card-preview', 'Loading the email…');
      mail.appendChild(preview);
      card.appendChild(mail);
      api('/api/email/' + t.email.id).then(res => {
        if (!card.isConnected) return;
        preview.textContent = res.error ? res.error
          : (res.sender ? res.sender.replace(/\s*<.*>$/, '') + ': ' : '') + res.preview;
        if (res.url) openMail.href = res.url;
      });
    }
    const actions = tEl('div', 'task-card-actions');
    if (t.application_id) {
      const job = tEl('button', 'btn-tinted', 'Open job');
      job.onclick = () => { closeTaskCard(); openJobsView(t.application_id); };
      actions.appendChild(job);
    }
    const openMail = tEl('a', 'btn-tinted', 'Open original email ↗');
    if (t.email) {
      openMail.href = t.email.url;
      openMail.target = '_blank';
      openMail.rel = 'noopener';
      actions.appendChild(openMail);
    }
    const edit = tEl('button', 'btn-plain', 'Edit');
    edit.onclick = () => { closeTaskCard(); tasksSelectedId = t.id; renderTasksView(); };
    actions.appendChild(edit);
    card.appendChild(actions);

    document.body.appendChild(card);
    const r = row.getBoundingClientRect();
    const below = r.bottom + 6 + card.offsetHeight < window.innerHeight;
    card.style.left = Math.min(r.left + 28, window.innerWidth - card.offsetWidth - 12) + 'px';
    card.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - card.offsetHeight - 6)) + 'px';
    card.style.transformOrigin = below ? 'top left' : 'bottom left';
    if (!reducedMotion()) {
      card.animate([{opacity: 0, transform: 'scale(0.97)'}, {opacity: 1, transform: 'none'}],
                   {duration: 160, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
    }
    taskCard = card;
    document.addEventListener('pointerdown', taskCardOutside, true);
    document.addEventListener('keydown', taskCardKey, true);
  }

  // Everything about one to-do, edited in place; each change saves at once.
  function taskInspector(t) {
    const panel = tEl('aside', 'inspector');
    const head = tEl('div', 'inspector-head');
    head.appendChild(tEl('div', 'inspector-kicker', 'Details'));
    const close = tEl('button', 'btn-plain', 'Done');
    close.onclick = () => { tasksSelectedId = null; renderTasksView(); };
    head.appendChild(close);
    panel.appendChild(head);

    const save = async fields => {
      const res = await jsonSend('/api/tasks/' + t.id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderTasksView();
    };

    const title = tEl('input', 'inspector-title');
    title.value = t.title;
    title.setAttribute('aria-label', 'Title');
    title.onchange = () => { if (title.value.trim() && title.value !== t.title) save({title: title.value}); };
    panel.appendChild(title);

    const due = tEl('input', 'job-field-input');
    due.type = 'date';
    due.value = t.due_date || '';
    due.setAttribute('aria-label', 'Due date');
    due.onchange = () => save({due_date: due.value});
    const quick = tEl('div', 'quick-dates');
    const today = localISO(new Date());
    [['Today', today], ['Tomorrow', addDays(today, 1)], ['Next week', addDays(today, 7)], ['None', '']]
      .forEach(([label, value]) => {
        const b = tEl('button', 'btn-tinted', label);
        b.type = 'button';
        b.onclick = () => save({due_date: value});
        quick.appendChild(b);
      });
    panel.appendChild(inspectorField('Due', due, quick));

    const repeat = tEl('select', 'job-field-input');
    repeat.setAttribute('aria-label', 'Repeat');
    const presets = [['', 'Never'], ['day:1', 'Every day'], ['week:1', 'Every week'],
                     ['week:2', 'Every 2 weeks'], ['month:1', 'Every month']];
    // A rule typed in quick-add ("every mon") isn't one of the presets: show it as is.
    if (t.repeat && !presets.some(p => p[0] === t.repeat)) presets.push([t.repeat, t.repeat_label]);
    presets.forEach(([value, label]) => {
      const o = tEl('option', '', label);
      o.value = value;
      repeat.appendChild(o);
    });
    repeat.value = t.repeat || '';
    repeat.onchange = () => save({repeat: repeat.value});
    panel.appendChild(inspectorField('Repeat', repeat));

    const area = tEl('select', 'job-field-input');
    area.setAttribute('aria-label', 'Life area');
    [{id: '', name: 'None'}].concat(lifeAreas).forEach(a => {
      const o = tEl('option', '', a.name);
      o.value = a.id;
      area.appendChild(o);
    });
    area.value = t.area_id || '';
    area.onchange = () => save({area_id: area.value});
    panel.appendChild(inspectorField('Life area', area));

    const job = tEl('select', 'job-field-input');
    job.setAttribute('aria-label', 'Linked application');
    job.appendChild(Object.assign(tEl('option', '', 'None'), {value: ''}));
    api('/api/jobs').then(d => {
      (d.applications || []).forEach(a => {
        const o = tEl('option', '', a.company + (a.role ? ' — ' + a.role : ''));
        o.value = a.id;
        job.appendChild(o);
      });
      job.value = t.application_id || '';
    });
    job.onchange = () => save({application_id: job.value || null});
    panel.appendChild(inspectorField('Job', job));

    const actions = tEl('div', 'inspector-actions');
    const focus = tEl('button', 'btn-tinted', 'Focus on this');
    focus.onclick = () => startFocus({label: t.title, task_id: t.id});
    const del = tEl('button', 'btn-tinted btn-danger-tinted', 'Delete');
    del.onclick = () => {
      tasksSelectedId = null;
      renderTasksView().then(() => softDelete({
        key: 'task:' + t.id, label: 'To-do',
        remove: () => api('/api/tasks/' + t.id, {method: 'DELETE'}), rerender: renderTasksView,
      }));
    };
    actions.appendChild(focus);
    actions.appendChild(del);
    panel.appendChild(actions);
    return panel;
  }

  function inspectorField(label, control, extra) {
    const f = tEl('div', 'inspector-field');
    f.appendChild(tEl('div', 'inspector-label', label));
    f.appendChild(control);
    if (extra) f.appendChild(extra);
    return f;
  }
