
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
      const res = await jsonSend('/api/areas', {name, color: '#8a8f98'});
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
