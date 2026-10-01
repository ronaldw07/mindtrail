
  // ---------- people ----------
  // Declarations only, loaded before app.js (see the note atop jobs.js).

  const NUDGE_CHOICES = [
    {days: 0, label: 'No reminder'}, {days: 7, label: 'Every week'},
    {days: 14, label: 'Every 2 weeks'}, {days: 30, label: 'Every month'},
    {days: 90, label: 'Every 3 months'},
  ];
  const nudgeLabel = d => (NUDGE_CHOICES.find(c => c.days === d) || {label: 'Every ' + d + ' days'}).label;

  function sinceLabel(days) {
    if (days === null || days === undefined) return 'Never talked';
    if (days === 0) return 'Talked today';
    if (days === 1) return 'Talked yesterday';
    return 'Talked ' + days + ' days ago';
  }

  async function talkedToday(personId) {
    const res = await jsonSend('/api/people/' + personId, {talked_today: true}, 'PATCH');
    if (res.error) toast(res.error, {error: true});
    return res;
  }

  async function openPeopleView() {
    currentProject = null;
    current = null;
    setActiveView('people');
    prefs.set('lastView', {type: 'people'});
    $('breadcrumb').textContent = 'People';
    await renderPeopleView();
  }

  async function renderPeopleView() {
    const data = await api('/api/people');
    const view = $('people-view');
    view.innerHTML = '';
    const wrap = tEl('div', 'brief-wrap');
    wrap.appendChild(tEl('div', 'proj-title', 'People'));

    const form = tEl('form', 'task-add task-add-wide habit-add');
    const name = tEl('input', 'jobs-link-input');
    name.placeholder = 'Name';
    name.setAttribute('aria-label', 'Name');
    const context = tEl('input', 'jobs-link-input');
    context.placeholder = 'How you know them (optional)';
    context.setAttribute('aria-label', 'Context');
    const nudge = nudgeSelect(14);
    const add = tEl('button', 'btn-primary jobs-btn', 'Add');
    add.type = 'submit';
    [name, context, nudge, add].forEach(e => form.appendChild(e));
    form.onsubmit = async e => {
      e.preventDefault();
      if (!name.value.trim()) return;
      const res = await jsonSend('/api/people', {name: name.value, context: context.value,
                                                 nudge_every_days: Number(nudge.value)});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderPeopleView();
    };
    wrap.appendChild(form);

    const due = data.people.filter(p => p.due);
    const rest = data.people.filter(p => !p.due);
    if (due.length) {
      wrap.appendChild(tEl('div', 'brief-section-label task-group-head', 'Due for a nudge · ' + due.length));
      due.forEach(p => wrap.appendChild(personRow(p, data.applications)));
    }
    if (rest.length) {
      wrap.appendChild(tEl('div', 'brief-section-label task-group-head', 'Everyone'));
      rest.forEach(p => wrap.appendChild(personRow(p, data.applications)));
    }
    if (!data.people.length) {
      wrap.appendChild(tEl('div', 'empty-state',
        'Add the people you want to keep up with — a mentor, a recruiter, family.'));
    }
    view.appendChild(wrap);
  }

  function nudgeSelect(value) {
    const select = tEl('select', 'job-field-input habit-select');
    select.setAttribute('aria-label', 'Reminder');
    NUDGE_CHOICES.forEach(c => {
      const o = tEl('option', '', c.label);
      o.value = String(c.days);
      select.appendChild(o);
    });
    select.value = String(value);
    return select;
  }

  function personRow(p, applications) {
    const row = tEl('div', 'person-row' + (p.due ? ' due' : ''));
    const body = tEl('div', 'person-body');
    body.appendChild(tEl('div', 'person-name', p.name));
    const meta = [sinceLabel(p.days_since), nudgeLabel(p.nudge_every_days)];
    if (p.context) meta.unshift(p.context);
    if (p.company) meta.push(p.company);
    body.appendChild(tEl('div', 'person-meta', meta.join(' · ')));
    if (p.notes) body.appendChild(tEl('div', 'person-notes', p.notes));
    row.appendChild(body);
    const talked = tEl('button', 'btn-ghost jobs-btn', 'Talked today');
    talked.onclick = async () => { await talkedToday(p.id); renderPeopleView(); };
    row.appendChild(talked);
    const more = tEl('button', 'menu-btn task-more', '⋯');
    more.setAttribute('aria-label', 'Options for ' + p.name);
    more.onclick = e => openPersonMenu(e, p, applications);
    row.appendChild(more);
    return row;
  }

  function openPersonMenu(e, p, applications) {
    const update = async fields => {
      const res = await jsonSend('/api/people/' + p.id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderPeopleView();
    };
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const name = await askText('Rename', p.name);
        if (name) await update({name});
      }},
      {label: 'How you know them', run: async () => {
        const context = await askText('How you know them', p.context, 'e.g. AntAlmanac maintainer');
        if (context !== null) await update({context});
      }},
      {label: 'Notes', run: async () => {
        const notes = await modal({title: 'Notes on ' + p.name, input: true, multiline: true,
                                   value: p.notes, confirmLabel: 'Save'});
        if (notes !== null) await update({notes});
      }},
      {label: 'Reminder…', run: async () => {
        const days = await modal({title: 'Remind me to reach out', confirmLabel: 'Save',
          value: p.nudge_every_days, select: NUDGE_CHOICES.map(c => ({value: c.days, label: c.label}))});
        if (days !== null) await update({nudge_every_days: Number(days)});
      }},
      {label: 'Link to a job application…', run: async () => {
        const id = await modal({title: 'Linked application', confirmLabel: 'Save', value: p.application_id,
          select: [{value: '', label: 'None'}].concat(applications.map(a =>
            ({value: a.id, label: a.company + (a.role ? ' — ' + a.role : '')})))});
        if (id !== null) await update({application_id: id});
      }},
      {divider: true},
      {label: 'Delete', danger: true, run: async () => {
        if (!await askConfirm('Delete', 'Remove ' + p.name + '?', 'Delete')) return;
        await api('/api/people/' + p.id, {method: 'DELETE'});
        await renderPeopleView();
      }},
    ]);
  }
