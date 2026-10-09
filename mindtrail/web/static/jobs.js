
  // ---------- jobs view ----------
  // Loaded before app.js and made only of declarations: app.js's boot
  // code (restoreLastView) may call openJobsView immediately, and nothing
  // here touches app.js's bindings ($, api, prefs, card...) until a
  // function actually runs, by which point app.js has defined them.

  const JOB_STAGE_LABELS = {
    saved: 'Saved', applied: 'Applied', oa: 'Assessment', interview: 'Interview',
    offer: 'Offer', rejected: 'Rejected', withdrawn: 'Withdrawn',
  };
  const JOB_STAGE_COLORS = {
    saved: '#8e8e93', applied: '#0a84ff', oa: '#ff9f0a', interview: '#bf5af2',
    offer: '#30d158', rejected: '#ff453a', withdrawn: '#8e8e93',
  };
  let jobsData = null;        // last /api/jobs payload
  let jobsSelectedId = null;  // application open in the detail panel

  function fmtShortDate(iso) {
    if (!iso) return '';
    // Noon local, so a bare YYYY-MM-DD never shifts a day across UTC.
    return new Date(iso + 'T12:00:00').toLocaleDateString(undefined,
      {month: 'short', day: 'numeric'});
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  async function openJobsView(focusAppId) {
    currentProject = null;
    current = null;
    setActiveView('jobs');
    prefs.set('lastView', {type: 'jobs'});
    $('breadcrumb').textContent = 'Jobs';
    if (focusAppId) jobsSelectedId = focusAppId;
    const view = $('jobs-view');
    if (!jobsData) { view.innerHTML = ''; view.appendChild(skeletonBlock(6)); }
    await reloadJobs();
  }

  async function reloadJobs() {
    jobsData = await api('/api/jobs');
    renderJobs();
  }

  // Server first, then re-render from the server's answer - a rejected
  // edit (blank company, bad date) never leaves the board showing a
  // value that wasn't saved.
  async function patchJob(id, fields) {
    const res = await jsonSend('/api/jobs/' + id, fields, 'PATCH');
    if (res.error) toast(res.error, {error: true});
    await reloadJobs();
    return !res.error;
  }

  function renderJobs() {
    const view = $('jobs-view');
    const data = jobsData;
    if (jobsSelectedId && !data.applications.some(a => a.id === jobsSelectedId)) {
      jobsSelectedId = null;
    }

    const layout = el('div', 'jobs-layout');
    const main = el('div', 'jobs-main');
    main.appendChild(jobsHeader(data));
    main.appendChild(jobsToolbar(data));
    main.appendChild(jobsBoard(data));
    layout.appendChild(main);
    const selected = data.applications.find(a => a.id === jobsSelectedId);
    if (selected) layout.appendChild(jobDetail(selected));
    commitView(view, layout);
  }

  function jobsHeader(data) {
    const head = el('div', 'jobs-head');
    head.appendChild(el('div', 'proj-title', 'Jobs'));
    const c = data.counts;
    const stats = el('div', 'jobs-stats');
    [
      [c.applied_this_week, 'applied this week'],
      [Math.round(c.response_rate * 100) + '%', 'heard back'],
      [c.interviewing, 'interviewing'],
      [c.total, 'tracked'],
    ].forEach(([n, label]) => {
      const s = el('div', 'jobs-stat');
      s.appendChild(el('div', 'jobs-stat-num', String(n)));
      s.appendChild(el('div', 'jobs-stat-label', label));
      stats.appendChild(s);
    });
    head.appendChild(stats);
    return head;
  }

  function jobsToolbar(data) {
    const bar = el('div', 'jobs-toolbar');

    const form = el('form', 'jobs-link-form');
    const input = el('input', 'jobs-link-input');
    input.placeholder = 'Paste a job posting link…';
    input.setAttribute('aria-label', 'Job posting link');
    const add = el('button', 'btn-primary jobs-btn', 'Add');
    add.type = 'submit';
    form.appendChild(input);
    form.appendChild(add);
    form.onsubmit = async e => {
      e.preventDefault();
      const url = input.value.trim();
      if (!url) return;
      setButtonBusy(add, 'Reading…');
      const res = await jsonSend('/api/jobs/link', {url});
      setButtonIdle(add, 'Add');
      if (res.error) { toast(res.error, {error: true}); return; }
      input.value = '';
      jobsSelectedId = res.application.id;
      toast(res.warning ? res.application.company + ' added — ' + res.warning
                        : res.application.company + ' added');
      await reloadJobs();
    };
    bar.appendChild(form);

    const more = el('button', 'btn-tinted', 'More ▾');
    more.setAttribute('aria-haspopup', 'menu');
    more.onclick = e => showMenuFrom(e.currentTarget, [
      {label: 'Add manually', run: addJobManually},
      {label: data.sheet.link ? 'Sync sheet' : 'Import from Google Sheets', run: () => importSheet(more)},
    ]);
    bar.appendChild(more);

    const scan = el('button', 'btn-tinted', 'Check email');
    scan.onclick = async () => {
      setButtonBusy(scan, 'Checking…');
      const res = await jsonSend('/api/jobs/scan', {});
      setButtonIdle(scan, 'Check email');
      toast(res.message || 'Done', {error: !res.ok});
      await reloadJobs();
    };
    bar.appendChild(scan);

    const email = data.email || {};
    if (email.message) {
      const note = el('div', 'jobs-email-status',
        'Email: ' + email.message + (email.at ? ' · ' + relTime(email.at) : ''));
      bar.appendChild(note);
    }
    return bar;
  }

  async function addJobManually() {
    const company = await askText('Add an application', '', 'Company');
    if (!company) return;
    const res = await jsonSend('/api/jobs', {company, stage: 'applied',
      applied_at: new Date().toLocaleDateString('en-CA')});
    if (res.error) { toast(res.error, {error: true}); return; }
    jobsSelectedId = res.application.id;
    await reloadJobs();
  }

  async function importSheet(btn) {
    const known = jobsData.sheet.link;
    const link = known || await askText('Import from Google Sheets', '',
      'https://docs.google.com/spreadsheets/d/…');
    if (!link) return;
    const label = btn.textContent;
    setButtonBusy(btn, 'Reading sheet…');
    const preview = await jsonSend('/api/jobs/sheet', {link, dry_run: true});
    setButtonIdle(btn, label);
    if (preview.error) { toast(preview.error, {error: true}); return; }
    const s = preview.summary;
    if (!s.new && !s.filled) { toast('Already up to date'); return; }
    const ok = await modal({
      title: known ? 'Sync sheet' : 'Import sheet',
      message: s.new + ' new applications, ' + s.filled + ' with details filled in, '
        + s.unchanged + ' already up to date, ' + s.skipped_rows + ' rows skipped. '
        + 'Nothing you changed in Mind Trail gets overwritten.',
      confirmLabel: 'Import',
    });
    if (!ok) return;
    const res = await jsonSend('/api/jobs/sheet', {link});
    if (res.error) { toast(res.error, {error: true}); return; }
    toast('Imported ' + res.summary.new + ' applications');
    await reloadJobs();
  }

  function jobsBoard(data) {
    const board = el('div', 'jobs-board');
    const showClosed = prefs.get('jobsShowClosed', false);
    const stages = data.pipeline.concat(showClosed ? data.closed : []);
    stages.forEach(stage => {
      const apps = data.applications.filter(a => a.stage === stage);
      board.appendChild(jobsColumn(stage, apps));
    });
    const closedCount = data.applications.filter(a => data.closed.includes(a.stage)).length;
    const toggle = el('button', 'btn-ghost jobs-closed-toggle',
      (showClosed ? 'Hide' : 'Show') + ' closed (' + closedCount + ')');
    toggle.onclick = () => { prefs.set('jobsShowClosed', !showClosed); renderJobs(); };
    const wrap = el('div', 'jobs-board-wrap');
    wrap.appendChild(board);
    wrap.appendChild(toggle);
    return wrap;
  }

  function jobsColumn(stage, apps) {
    const col = el('div', 'jobs-col');
    col.dataset.stage = stage;
    col.style.setProperty('--stage', JOB_STAGE_COLORS[stage] || '#636366');
    const head = el('div', 'jobs-col-head');
    head.appendChild(el('span', 'jobs-col-dot'));
    head.appendChild(el('span', 'jobs-col-name', JOB_STAGE_LABELS[stage]));
    head.appendChild(el('span', 'jobs-col-count', String(apps.length)));
    col.appendChild(head);
    apps.forEach(a => col.appendChild(jobCard(a)));
    // Dragging a card between columns: see enableJobDrag. The detail
    // panel's stage picker is the keyboard path to the same change.
    return col;
  }

  function jobCard(a) {
    const c = el('div', 'job-card' + (a.id === jobsSelectedId ? ' selected' : ''));
    c.dataset.key = 'job:' + a.id;
    c.dataset.id = a.id;
    const top = el('div', 'job-card-top');
    top.appendChild(avatar(a.company, 26));
    const names = el('div', 'job-card-names');
    names.appendChild(el('div', 'job-card-company', a.company));
    if (a.role) names.appendChild(el('div', 'job-card-role', a.role));
    top.appendChild(names);
    const since = a.applied_at || (a.created_at || '').slice(0, 10);
    if (since) {
      const days = Math.max(0, Math.round((Date.now() - new Date(since + 'T12:00:00')) / 86400000));
      const age = el('div', 'job-card-age', days + 'd');
      age.title = (a.applied_at ? 'Applied ' : 'Added ') + fmtShortDate(since);
      top.appendChild(age);
    }
    c.appendChild(top);
    enableJobDrag(c, a);
    const meta = el('div', 'job-card-meta');
    if (a.needs_review) meta.appendChild(el('span', 'job-chip review', 'Review'));
    if (a.deadline) meta.appendChild(el('span', 'job-chip', 'Due ' + fmtShortDate(a.deadline)));
    const open = a.tasks.filter(t => !t.done).length;
    if (open) meta.appendChild(el('span', 'job-chip', open + ' to-do' + (open > 1 ? 's' : '')));
    if (meta.childNodes.length) c.appendChild(meta);
    makeClickable(c, () => {
      jobsSelectedId = jobsSelectedId === a.id ? null : a.id;
      renderJobs();
    });
    return c;
  }

  function detailField(a, key, label, type) {
    const row = el('label', 'job-field');
    row.appendChild(el('span', 'job-field-label', label));
    const input = el(type === 'textarea' ? 'textarea' : 'input', 'job-field-input');
    if (type && type !== 'textarea') input.type = type;
    input.value = a[key] || '';
    input.addEventListener('change', () => patchJob(a.id, {[key]: input.value}));
    row.appendChild(input);
    return row;
  }

  function jobDetail(a) {
    const panel = el('aside', 'job-detail inspector');
    const top = el('div', 'job-detail-top');
    top.appendChild(el('div', 'job-detail-title', a.company));
    const close = el('button', 'nav-btn', '×');
    close.setAttribute('aria-label', 'Close details');
    close.onclick = () => { jobsSelectedId = null; renderJobs(); };
    top.appendChild(close);
    panel.appendChild(top);

    if (a.needs_review) {
      const review = el('div', 'job-review');
      review.appendChild(el('div', '', 'Added from an email — keep it?'));
      const keep = el('button', 'btn-primary jobs-btn', 'Keep');
      keep.onclick = () => patchJob(a.id, {needs_review: false});
      const discard = el('button', 'btn-ghost jobs-btn', 'Discard');
      discard.onclick = () => deleteJob(a, false);
      review.appendChild(keep);
      review.appendChild(discard);
      panel.appendChild(review);
    }

    const stageRow = el('label', 'job-field');
    stageRow.appendChild(el('span', 'job-field-label', 'Stage'));
    const select = el('select', 'job-field-input');
    jobsData.stages.forEach(s => {
      const o = el('option', '', JOB_STAGE_LABELS[s]);
      o.value = s;
      select.appendChild(o);
    });
    select.value = a.stage;
    select.addEventListener('change', () => patchJob(a.id, {stage: select.value}));
    stageRow.appendChild(select);
    panel.appendChild(stageRow);

    panel.appendChild(detailField(a, 'company', 'Company'));
    panel.appendChild(detailField(a, 'role', 'Role'));
    panel.appendChild(detailField(a, 'location', 'Location'));
    panel.appendChild(detailField(a, 'applied_at', 'Applied', 'date'));
    panel.appendChild(detailField(a, 'deadline', 'Deadline', 'date'));
    panel.appendChild(detailField(a, 'url', 'Link', 'url'));
    if (a.url && /^https?:\/\//.test(a.url)) {
      const link = el('a', 'job-open-link', 'Open posting ↗');
      link.href = a.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      panel.appendChild(link);
    }
    panel.appendChild(detailField(a, 'notes', 'Notes', 'textarea'));

    panel.appendChild(el('div', 'brief-section-label', 'To-dos'));
    a.tasks.forEach(t => panel.appendChild(taskRow(t, reloadJobs)));
    panel.appendChild(addTaskForm(a.id, reloadJobs));

    if (a.emails.length) {
      panel.appendChild(el('div', 'brief-section-label', 'Emails'));
      a.emails.forEach(m => {
        const row = el('div', 'job-email');
        row.appendChild(el('div', 'job-email-subject', m.subject || '(no subject)'));
        row.appendChild(el('div', 'job-email-meta',
          fmtShortDate((m.received_at || '').slice(0, 10)) + ' · ' + m.label));
        panel.appendChild(row);
      });
    }

    const del = el('button', 'btn-ghost jobs-btn job-delete', 'Delete application');
    del.onclick = () => deleteJob(a, true);
    panel.appendChild(del);
    return panel;
  }

  // Undoable for a few seconds, like every delete: the card vanishes now and
  // the application and its to-dos are removed when the toast runs out.
  async function deleteJob(a) {
    jobsSelectedId = null;
    renderJobs();
    softDelete({key: 'job:' + a.id, label: a.company,
                remove: () => api('/api/jobs/' + a.id, {method: 'DELETE'}),
                rerender: reloadJobs});
  }

  // ---------- tasks (shared by the Jobs panel and Today) ----------

  function taskRow(t, afterChange) {
    const row = el('div', 'task-row' + (t.done ? ' done' : ''));
    row.dataset.key = 'task:' + (t.task_id || t.id);
    const box = el('button', 'task-check');
    box.setAttribute('aria-label', (t.done ? 'Mark not done: ' : 'Mark done: ') + t.title);
    box.setAttribute('aria-pressed', t.done ? 'true' : 'false');
    // Reminders-style: the circle fills at once and the row stays put for a
    // beat, so a mis-click can be undone by clicking again; then it moves.
    let done = !!t.done;
    let settle = null;
    box.onclick = async e => {
      e.stopPropagation();
      clearTimeout(settle);
      done = !done;
      row.classList.toggle('done', done);
      box.setAttribute('aria-pressed', done ? 'true' : 'false');
      const res = await jsonSend('/api/tasks/' + (t.task_id || t.id), {done}, 'PATCH');
      if (res.error) {
        done = !done;
        row.classList.toggle('done', done);
        box.setAttribute('aria-pressed', done ? 'true' : 'false');
        toast(res.error, {error: true});
        return;
      }
      if (afterChange) settle = setTimeout(afterChange, done ? 1100 : 250);
    };
    row.appendChild(box);
    const body = el('div', 'task-body');
    body.appendChild(el('div', 'task-title', t.title));
    if (t.due_date) body.appendChild(el('div', 'task-due', fmtShortDate(t.due_date)));
    row.appendChild(body);
    return row;
  }

  function addTaskForm(applicationId, afterChange) {
    const form = el('form', 'task-add');
    const title = el('input', 'job-field-input');
    title.placeholder = 'Add a to-do…';
    title.setAttribute('aria-label', 'New to-do');
    const due = el('input', 'job-field-input task-add-date');
    due.type = 'date';
    due.setAttribute('aria-label', 'Due date');
    form.appendChild(title);
    form.appendChild(due);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!title.value.trim()) return;
      const res = await jsonSend('/api/tasks', {
        title: title.value, due_date: due.value, application_id: applicationId || null,
      });
      if (res.error) { toast(res.error, {error: true}); return; }
      if (afterChange) await afterChange();
    };
    return form;
  }

  async function quickAddTask() {
    const title = await askText('New to-do', '', 'e.g. Email Carla back');
    if (!title) return;
    const res = await jsonSend('/api/tasks', {title});
    if (res.error) { toast(res.error, {error: true}); return; }
    toast('Added to your to-dos');
    if ($('dashboard-view').classList.contains('open')) openDashboardView();
  }

  // ---------- dragging a card between columns ----------
  // Pointer-based rather than the browser's drag-and-drop, which shows a
  // faded ghost and gives no say over the motion. Here the card lifts, the
  // others glide aside to make room, and it settles into its slot.

  function enableJobDrag(card, a) {
    card.addEventListener('click', e => {
      if (card._wasDragged) { card._wasDragged = false; e.stopImmediatePropagation(); }
    }, true);
    card.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.pointerType === 'touch') return;
      const sx = e.clientX, sy = e.clientY;
      let drag = null;
      const move = ev => {
        if (!drag) {
          if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 5) return;
          drag = beginJobDrag(card, a, sx, sy);
        }
        drag.move(ev);
      };
      const key = ev => { if (ev.key === 'Escape' && drag) end(ev, true); };
      const end = (ev, cancel) => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', end);
        document.removeEventListener('pointercancel', end);
        document.removeEventListener('keydown', key);
        if (drag) { card._wasDragged = true; drag.drop(cancel || ev.type === 'pointercancel'); }
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', end);
      document.addEventListener('pointercancel', end);
      document.addEventListener('keydown', key);
    });
  }

  function beginJobDrag(card, a, sx, sy) {
    const rect = card.getBoundingClientRect();
    const board = document.querySelector('.jobs-board');
    const allCards = () => Array.from(document.querySelectorAll('.jobs-col .job-card'));
    const originCol = card.parentElement;
    const originNext = card.nextElementSibling;

    const ghost = card.cloneNode(true);
    ghost.classList.add('job-ghost');
    ghost.style.cssText = `left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;`;
    document.body.appendChild(ghost);
    card.classList.add('drag-source');
    document.body.classList.add('dragging-card');

    let overCol = null;
    const place = (col, y) => {
      const siblings = Array.from(col.querySelectorAll('.job-card:not(.drag-source)'));
      const before = siblings.find(s => {
        const r = s.getBoundingClientRect();
        return y < r.top + r.height / 2;
      }) || null;
      if (card.parentElement === col && card.nextElementSibling === before) return;
      flipNodes(allCards(), () => col.insertBefore(card, before));
    };

    return {
      move(ev) {
        ghost.style.transform = `translate(${ev.clientX - sx}px, ${ev.clientY - sy}px) scale(1.03)`;
        const col = document.elementsFromPoint(ev.clientX, ev.clientY)
          .find(n => n.classList && n.classList.contains('jobs-col')) || null;
        if (col !== overCol) {
          if (overCol) overCol.classList.remove('drop');
          if (col) col.classList.add('drop');
          overCol = col;
        }
        if (col) place(col, ev.clientY);
        if (board) {
          const b = board.getBoundingClientRect();
          if (ev.clientX < b.left + 40) board.scrollLeft -= 14;
          else if (ev.clientX > b.right - 40) board.scrollLeft += 14;
        }
      },
      drop(cancelled) {
        if (overCol) overCol.classList.remove('drop');
        document.body.classList.remove('dragging-card');
        const stage = overCol && overCol.dataset.stage;
        const moved = !cancelled && stage && stage !== a.stage;
        if (!moved) {
          flipNodes(allCards(), () => originCol.insertBefore(card, originNext));
        }
        const to = card.getBoundingClientRect();
        const finish = () => { ghost.remove(); card.classList.remove('drag-source'); };
        if (reducedMotion()) { finish(); } else {
          const anim = ghost.animate([
            {transform: ghost.style.transform},
            {transform: `translate(${to.left - rect.left}px, ${to.top - rect.top}px) scale(1)`},
          ], {duration: cssVarMs('--dur-spring-snappy', 260),
              easing: getComputedStyle(document.documentElement).getPropertyValue('--spring-snappy').trim() || 'ease-out',
              fill: 'forwards'});
          anim.onfinish = finish;
        }
        if (moved) patchJob(a.id, {stage});
      },
    };
  }
