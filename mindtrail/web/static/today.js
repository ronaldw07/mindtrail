
  // ---------- Today: the daily brief ----------
  // Declarations only, loaded before app.js (see the note atop jobs.js).
  //
  // Layout follows the editorial "morning brief": a painting masthead
  // with the day's title, the brief paragraph, an at-a-glance row of
  // small widgets you can reorder or hide, then labeled sections - label
  // on the left, content on the right.

  const TODAY_WIDGETS = [
    {id: 'habits', label: 'Habit rings'},
    {id: 'mood', label: 'Mood & energy'},
    {id: 'week', label: 'Week ahead'},
    {id: 'pipeline', label: 'Job pipeline'},
  ];
  const DEFAULT_LAYOUT = {order: TODAY_WIDGETS.map(w => w.id), hidden: [], art: true};

  function todayLayout() {
    const saved = prefs.get('todayLayout', null) || {};
    const known = TODAY_WIDGETS.map(w => w.id);
    // Keep the saved order, drop ids that no longer exist, append new ones.
    const order = (saved.order || []).filter(id => known.includes(id));
    known.forEach(id => { if (!order.includes(id)) order.push(id); });
    return {order, hidden: (saved.hidden || []).filter(id => known.includes(id)),
            art: saved.art !== false};
  }

  function tEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function greetingWord() {
    const h = new Date().getHours();
    if (h < 5) return 'Good night';
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  }

  // ---------- masthead ----------

  function masthead(layout) {
    const now = new Date();
    const wrap = tEl('header', 't-masthead');
    const date = tEl('div', 't-side t-side-date',
      now.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'}).toUpperCase());
    const time = tEl('div', 't-side t-side-time',
      now.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'}).toUpperCase());
    const art = tEl('div', 't-art' + (layout.art ? '' : ' plain'));
    const title = tEl('h1', 't-title');
    title.appendChild(tEl('span', 't-title-the', 'The'));
    title.appendChild(tEl('span', 't-title-main',
      now.toLocaleDateString(undefined, {weekday: 'long'}) + ' Brief'));
    art.appendChild(title);
    wrap.appendChild(date);
    wrap.appendChild(art);
    wrap.appendChild(time);
    if (layout.art) loadArtwork(art);
    return wrap;
  }

  // The image fades in once loaded - a one-time, page-load moment, not
  // a repeated interaction, so it's allowed motion (see life.css).
  async function loadArtwork(art) {
    let meta;
    try { meta = await api('/api/artwork'); } catch (err) { return; }
    if (!meta || !meta.available) { art.classList.add('plain'); return; }
    const img = new Image();
    img.alt = '';
    img.className = 't-art-img';
    img.onload = () => img.classList.add('loaded');
    img.src = '/api/artwork/image?day=' + encodeURIComponent(meta.day);
    art.insertBefore(img, art.firstChild);
    art.dataset.credit = meta.title + ', ' + meta.artist + (meta.date ? ', ' + meta.date : '');
    const credit = document.querySelector('.t-credit');
    if (credit) credit.textContent = art.dataset.credit;
  }

  function underline(summary) {
    const row = tEl('div', 't-under');
    const brief = tEl('p', 't-brief');
    row.appendChild(brief);
    row.appendChild(tEl('div', 't-credit', ''));
    if (summary.empty) {
      brief.textContent = greetingWord() + '. A clear day — nothing due and nothing on the calendar.';
    } else {
      loadBrief(brief, false);
    }
    return row;
  }

  // Asked for on every visit; the server answers from cache unless the
  // day's data changed (daily_brief.cached_brief), so this is a model
  // call only when there's something new to say.
  async function loadBrief(el, force) {
    el.classList.add('pending');
    el.textContent = force ? 'Rewriting…' : greetingWord() + '. Writing your brief…';
    let res;
    try {
      res = await jsonSend('/api/daily-summary/brief', {force});
    } catch (err) {
      res = {error: 'request failed'};
    }
    el.classList.remove('pending');
    el.innerHTML = '';
    el.appendChild(document.createTextNode(res.text ? res.text + ' '
      : greetingWord() + '. (Couldn’t write a brief: ' + (res.error || 'nothing to say') + '.) '));
    const again = tEl('button', 't-link', 'Rewrite');
    again.onclick = () => loadBrief(el, true);
    el.appendChild(again);
  }

  // ---------- at a glance ----------

  function glanceRow(summary, data, layout) {
    const row = tEl('section', 't-glance');
    row.setAttribute('aria-label', 'At a glance');
    layout.order.filter(id => !layout.hidden.includes(id)).forEach(id => {
      const w = {habits: habitRings, mood: moodChart, week: weekStrip, pipeline: pipelineTiles}[id];
      const tile = w(summary, data);
      if (tile) row.appendChild(tile);
    });
    const edit = tEl('button', 't-link t-customize', 'Customize');
    edit.onclick = e => openLayoutMenu(e);
    row.appendChild(edit);
    return row;
  }

  function glanceTile(title, onOpen) {
    const tile = tEl('div', 't-tile');
    const head = tEl('div', 't-tile-head', title);
    tile.appendChild(head);
    if (onOpen) makeClickable(head, onOpen);
    return tile;
  }

  const SVG_NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  }

  // One ring per habit: this week's check-ins against its weekly target.
  function habitRings(summary) {
    const habits = summary.habits || [];
    if (!habits.length) return null;
    const tile = glanceTile('Habits this week', () => openHabitsView());
    const rings = tEl('div', 't-rings');
    habits.slice(0, 6).forEach(h => {
      const target = h.target_per_week;
      const frac = Math.min(h.this_week / target, 1);
      const r = 16, c = 2 * Math.PI * r;
      const s = svg('svg', {viewBox: '0 0 40 40', width: 40, height: 40, role: 'img',
        'aria-label': h.name + ': ' + h.this_week + ' of ' + target + ' this week'});
      s.appendChild(svg('circle', {cx: 20, cy: 20, r, class: 't-ring-track'}));
      const arc = svg('circle', {cx: 20, cy: 20, r, class: 't-ring-arc',
        'stroke-dasharray': (c * frac) + ' ' + c, transform: 'rotate(-90 20 20)'});
      arc.style.stroke = habitColor(h);
      s.appendChild(arc);
      const item = tEl('div', 't-ring');
      item.appendChild(s);
      item.appendChild(tEl('div', 't-ring-name', h.name));
      item.appendChild(tEl('div', 't-ring-count', h.this_week + '/' + target));
      rings.appendChild(item);
    });
    tile.appendChild(rings);
    return tile;
  }

  // Two series on one 1-5 scale (one axis - never dual). Colors are the
  // first two validated palette slots; both lines are direct-labeled and
  // a legend names them, so identity is never color alone. Days with no
  // rating break the line rather than interpolating a value that wasn't
  // recorded.
  const MOOD_SERIES = [
    {key: 'mood', label: 'Mood', color: '#3987e5'},
    {key: 'energy', label: 'Energy', color: '#d95926'},
  ];
  function moodChart(summary) {
    const trend = (summary.journal && summary.journal.trend) || [];
    const tile = glanceTile('Mood & energy · 14 days', () => openJournalView());
    if (!trend.length) {
      tile.appendChild(tEl('div', 't-empty', 'Rate a day in the journal to see a trend.'));
      return tile;
    }
    const W = 260, H = 84, PADL = 6, PADR = 46, PADT = 8, PADB = 8;
    const today = localISO(new Date());
    const x = i => PADL + (i / 13) * (W - PADL - PADR);
    const y = v => PADT + (5 - v) / 4 * (H - PADT - PADB);
    const byDate = Object.fromEntries(trend.map(t => [t.date, t]));
    const s = svg('svg', {viewBox: `0 0 ${W} ${H}`, class: 't-spark', role: 'img',
      'aria-label': 'Mood and energy over the last 14 days'});
    [1, 3, 5].forEach(v => s.appendChild(svg('line', {x1: PADL, x2: W - PADR, y1: y(v), y2: y(v),
                                                      class: 't-grid'})));
    const labels = [];
    MOOD_SERIES.forEach(series => {
      let path = '', last = null;
      for (let i = 0; i < 14; i++) {
        const day = addDays(today, i - 13);
        const v = (byDate[day] || {})[series.key] || 0;
        if (!v) { last = null; continue; }
        path += (last === null ? 'M' : 'L') + x(i).toFixed(1) + ' ' + y(v).toFixed(1) + ' ';
        last = {i, v};
        const dot = svg('circle', {cx: x(i), cy: y(v), r: 4, fill: series.color, class: 't-dot'});
        const tip = svg('title');
        tip.textContent = series.label + ' ' + v + '/5 · ' + fmtShortDate(day);
        dot.appendChild(tip);
        s.appendChild(dot);
      }
      if (path) s.insertBefore(svg('path', {d: path, stroke: series.color, class: 't-line'}),
                               s.querySelector('.t-dot'));
      const lastPoint = [...Array(14).keys()].reverse()
        .map(i => ({i, v: (byDate[addDays(today, i - 13)] || {})[series.key] || 0}))
        .find(p => p.v);
      if (lastPoint) labels.push({series, x: x(lastPoint.i) + 8, y: y(lastPoint.v) + 4});
    });
    // Direct labels at each line's end, pushed apart when the two lines
    // end close together so they never print on top of each other.
    const LABEL_GAP = 12;
    if (labels.length === 2 && Math.abs(labels[0].y - labels[1].y) < LABEL_GAP) {
      const [hi, lo] = labels[0].y <= labels[1].y ? labels : [labels[1], labels[0]];
      const mid = (hi.y + lo.y) / 2;
      hi.y = mid - LABEL_GAP / 2;
      lo.y = mid + LABEL_GAP / 2;
    }
    labels.forEach(l => {
      const text = svg('text', {x: Math.max(...labels.map(o => o.x)), y: l.y, class: 't-direct'});
      text.textContent = l.series.label;
      s.appendChild(text);
    });
    tile.appendChild(s);
    const legend = tEl('div', 't-legend');
    MOOD_SERIES.forEach(series => {
      const item = tEl('span', 't-legend-item');
      const swatch = tEl('span', 't-swatch');
      swatch.style.background = series.color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(series.label));
      legend.appendChild(item);
    });
    tile.appendChild(legend);
    return tile;
  }

  // Seven days, today first: what's due each day across to-dos,
  // application deadlines, and roadmap steps.
  function weekStrip(summary, data) {
    const tile = glanceTile('Week ahead', () => openTasksView());
    const today = localISO(new Date());
    const byDay = {};
    const add = (day, title) => { (byDay[day] = byDay[day] || []).push(title); };
    (summary.tasks || []).forEach(t => add(t.due_date < today ? today : t.due_date, t.title));
    (summary.deadlines || []).forEach(d => add(d.due_date, d.title));
    const agenda = data.agenda || {};
    ['overdue', 'today', 'this_week'].forEach(k => (agenda[k] || []).forEach(n =>
      add(n.due_date < today ? today : n.due_date, n.title)));
    const strip = tEl('div', 't-week');
    for (let i = 0; i < 7; i++) {
      const day = addDays(today, i);
      const items = byDay[day] || [];
      const col = tEl('div', 't-week-day' + (i === 0 ? ' today' : ''));
      col.appendChild(tEl('div', 't-week-name', i === 0 ? 'Today'
        : new Date(day + 'T12:00:00').toLocaleDateString(undefined, {weekday: 'short'})));
      col.appendChild(tEl('div', 't-week-count', items.length ? String(items.length) : '–'));
      col.title = items.length ? items.join('\n') : 'Nothing due';
      strip.appendChild(col);
    }
    tile.appendChild(strip);
    return tile;
  }

  function pipelineTiles(summary) {
    const p = summary.pipeline;
    if (!p || !p.total) return null;
    const tile = glanceTile('Job search', () => openJobsView());
    const stats = tEl('div', 't-stats');
    [[p.applied_this_week, 'applied this week'], [p.interviewing, 'interviewing'],
     [Math.round(p.response_rate * 100) + '%', 'heard back']].forEach(([n, label]) => {
      const s = tEl('div', 't-stat');
      s.appendChild(tEl('div', 't-stat-num', String(n)));
      s.appendChild(tEl('div', 't-stat-label', label));
      stats.appendChild(s);
    });
    tile.appendChild(stats);
    return tile;
  }

  function openLayoutMenu(e) {
    const layout = todayLayout();
    const save = next => { prefs.set('todayLayout', next); openDashboardView(); };
    const items = [{label: (layout.art ? 'Hide' : 'Show') + ' daily painting',
                    run: () => save({...layout, art: !layout.art})}, {divider: true}];
    layout.order.forEach((id, i) => {
      const w = TODAY_WIDGETS.find(x => x.id === id);
      const hidden = layout.hidden.includes(id);
      items.push({label: (hidden ? 'Show ' : 'Hide ') + w.label, run: () => save({...layout,
        hidden: hidden ? layout.hidden.filter(h => h !== id) : layout.hidden.concat(id)})});
      if (i > 0) {
        items.push({label: '   Move ' + w.label + ' left', run: () => {
          const order = layout.order.slice();
          [order[i - 1], order[i]] = [order[i], order[i - 1]];
          save({...layout, order});
        }});
      }
    });
    items.push({divider: true}, {label: 'Reset layout', run: () => save(DEFAULT_LAYOUT)});
    showMenu(e, items);
  }

  // ---------- sections ----------

  function section(label, content) {
    const s = tEl('section', 't-section');
    const head = tEl('div', 't-head');
    head.appendChild(tEl('h2', 't-label', label));
    s.appendChild(head);
    const body = tEl('div', 't-body');
    if (content) body.appendChild(content);
    s.appendChild(body);
    return s;
  }

  // The one thing to do next, as its own card: label and a "Let's do it"
  // sticker on the left, the item on the right.
  function pushSection(item) {
    if (!item) return null;
    const s = section('Push your work forward', null);
    s.classList.add('t-push');
    const sticker = tEl('button', 't-sticker');
    const label = tEl('span', 't-sticker-text', 'Let’s do it →');
    sticker.appendChild(label);
    s.querySelector('.t-label').after(sticker);
    const body = s.querySelector('.t-body');
    body.appendChild(tEl('div', 't-push-title', item.title));
    const due = item.due_date ? ' · due ' + fmtShortDate(item.due_date) : '';
    let sub;
    if (item.kind === 'task') {
      sub = (item.company || 'To-do') + due;
      label.textContent = 'Done ✓';
      sticker.onclick = async () => {
        await jsonSend('/api/tasks/' + item.task_id, {done: true}, 'PATCH');
        openDashboardView();
      };
    } else if (item.kind === 'deadline') {
      sub = 'Application deadline' + due;
      sticker.onclick = () => openJobsView(item.application_id);
    } else {
      sub = item.project_name + due;
      sticker.onclick = () => openRoadmapView(item.project_id, item.project_name);
    }
    body.appendChild(tEl('div', 't-push-sub', sub));
    return s;
  }

  const BUCKET_TAGS = {overdue: 'Overdue', today: 'Due today'};

  function todoItem(opts) {
    const row = tEl('div', 't-item' + (opts.overdue ? ' overdue' : ''));
    if (opts.onCheck) {
      const check = tEl('button', 'task-check');
      check.setAttribute('aria-label', 'Mark done: ' + opts.title);
      check.onclick = async e => {
        e.stopPropagation();
        row.classList.add('done');
        await opts.onCheck();
      };
      row.appendChild(check);
    } else {
      row.appendChild(tEl('span', 't-item-mark'));
    }
    const body = tEl('div', 't-item-body');
    body.appendChild(tEl('div', 't-item-title', opts.title));
    body.appendChild(tEl('div', 't-item-sub', opts.sub));
    row.appendChild(body);
    if (opts.onOpen) makeClickable(row, opts.onOpen);
    return row;
  }

  function todoList(summary) {
    const list = tEl('div', 't-list');
    const tag = n => BUCKET_TAGS[n.bucket] || ('Due ' + fmtShortDate(n.due_date));
    const rows = [
      ...(summary.tasks || []).map(t => todoItem({
        title: t.title, overdue: t.bucket === 'overdue',
        sub: (t.company ? t.company + ' · ' : '') + tag(t),
        onCheck: async () => {
          await jsonSend('/api/tasks/' + t.task_id, {done: true}, 'PATCH');
          openDashboardView();
        },
        onOpen: t.application_id ? () => openJobsView(t.application_id) : null,
      })),
      ...(summary.deadlines || []).map(d => todoItem({
        title: d.title, sub: 'Application deadline · ' + tag(d),
        onOpen: () => openJobsView(d.application_id),
      })),
      ...(summary.due || []).map(n => todoItem({
        title: n.title, overdue: n.bucket === 'overdue', sub: n.project_name + ' · ' + tag(n),
        onOpen: () => openRoadmapView(n.project_id, n.project_name),
      })),
      ...(summary.unblocked || []).map(n => todoItem({
        title: n.title, sub: n.project_name + ' · Ready to start',
        onOpen: () => openRoadmapView(n.project_id, n.project_name),
      })),
      ...(summary.recurring || []).map(n => todoItem({
        title: n.title, sub: n.project_name + ' · Coming up ' + fmtShortDate(n.due_date),
        onOpen: () => openRoadmapView(n.project_id, n.project_name),
      })),
    ];
    rows.forEach(r => list.appendChild(r));
    if (!rows.length) list.appendChild(tEl('div', 't-empty', 'Nothing due. Enjoy it.'));
    const add = tEl('button', 't-link', '+ Add a to-do');
    add.onclick = () => quickAddTask();
    list.appendChild(add);
    return list;
  }

  function habitList(habits) {
    const list = tEl('div', 't-habits');
    if (!habits.length) {
      const link = tEl('button', 't-link', 'Add your first habit →');
      link.onclick = () => openHabitsView();
      list.appendChild(link);
      return list;
    }
    habits.forEach(h => {
      const row = tEl('div', 't-habit' + (h.done_today ? ' done' : ''));
      const check = tEl('button', 'task-check');
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
      row.appendChild(tEl('span', 't-habit-name', h.name));
      if (h.streak) row.appendChild(tEl('span', 't-habit-streak',
        h.streak + (h.unit === 'day' ? '-day' : '-week') + ' streak'));
      list.appendChild(row);
    });
    return list;
  }

  // The day as a list of times, the current or next event highlighted.
  function dayTimeline(calendar) {
    const cal = calendar || {connected: false};
    const box = tEl('div', 't-day');
    if (!cal.connected) {
      box.appendChild(tEl('div', 't-empty', cal.needs_reconnect
        ? 'Google Calendar needs reconnecting — run: mindtrail google connect'
        : 'Connect Google Calendar to see your day here — run: mindtrail google connect'));
      return box;
    }
    const events = cal.events || [];
    if (cal.stale || cal.error) {
      box.appendChild(tEl('div', 't-note', 'Showing calendar as of ' + (cal.as_of || 'earlier')));
    }
    if (!events.length) {
      box.appendChild(tEl('div', 't-empty', 'Nothing on your calendar today.'));
      return box;
    }
    const now = new Date();
    const nowHM = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
    const timed = events.filter(e => !e.all_day);
    const nextIdx = timed.findIndex(e => e.start >= nowHM);
    // The next event to start, or the last one once the day's are over.
    const highlight = nextIdx === -1 ? timed[timed.length - 1] : timed[nextIdx];
    events.forEach(e => {
      const row = tEl('div', 't-day-row' + (e === highlight ? ' current' : ''));
      row.appendChild(tEl('span', 't-day-time', e.all_day ? 'All day' : fmtClock(e.start)));
      row.appendChild(tEl('span', 't-day-title', e.title));
      box.appendChild(row);
    });
    return box;
  }

  function fmtClock(hm) {
    const [h, m] = hm.split(':').map(Number);
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})
      .replace(' AM', 'a').replace(' PM', 'p');
  }

  function updatesList(highlights) {
    const list = tEl('div', 't-list');
    if (!highlights.length) {
      list.appendChild(tEl('div', 't-empty', 'Project highlights show up here.'));
      return list;
    }
    highlights.forEach((h, i) => {
      const row = tEl('div', 't-update');
      row.appendChild(tEl('span', 't-update-num', String(i + 1).padStart(2, '0')));
      const body = tEl('div', 't-item-body');
      body.appendChild(tEl('div', 't-item-title', h.headline));
      body.appendChild(tEl('div', 't-item-sub', h.project_name));
      row.appendChild(body);
      makeClickable(row, () => openProject(h.project_id));
      list.appendChild(row);
    });
    return list;
  }

  function journalPrompt(journal) {
    const box = tEl('div', 't-list');
    if (journal && journal.written_today) {
      box.appendChild(tEl('div', 't-empty', 'Written today.'));
      const open = tEl('button', 't-link', 'Open today’s entry');
      open.onclick = () => openJournalView();
      box.appendChild(open);
    } else {
      const write = tEl('button', 't-link', 'Write today’s entry →');
      write.onclick = () => openJournalView();
      box.appendChild(write);
    }
    return box;
  }

  function laterList(data) {
    const list = tEl('div', 't-list');
    const agenda = data.agenda || {};
    const items = (agenda.this_week || []).concat(agenda.later || []).slice(0, 8);
    items.forEach(n => list.appendChild(todoItem({
      title: n.title, sub: n.project_name + ' · Due ' + fmtShortDate(n.due_date),
      onOpen: () => openRoadmapView(n.project_id, n.project_name),
    })));
    (data.recent || []).slice(0, 5).forEach(c => list.appendChild(todoItem({
      title: c.title, sub: 'Chat · ' + relTime(c.updated_at),
      onOpen: () => { showChatView(); openConversation(c.id); },
    })));
    return list.childNodes.length ? list : null;
  }

  function footer(summary) {
    const sources = ['your to-dos', 'jobs', 'habits', 'journal'];
    if (summary.calendar && summary.calendar.connected) sources.push('Google Calendar');
    const f = tEl('footer', 't-footer');
    f.textContent = 'Made for you by mindtrail from ' + sources.slice(0, -1).join(', ')
      + ', and ' + sources[sources.length - 1] + '.';
    return f;
  }

  async function openDashboardView() {
    currentProject = null;
    current = null;
    showDashboardView();
    prefs.set('lastView', {type: 'dashboard'});
    $('breadcrumb').textContent = 'Today';

    const view = $('dashboard-view');
    if (!view.querySelector('.t-page')) {
      view.innerHTML = '';
      view.appendChild(skeletonBlock(6));
    }
    const [data, summary] = await Promise.all([
      api('/api/dashboard'), api('/api/daily-summary'),
    ]);
    const layout = todayLayout();
    const page = tEl('div', 't-page');
    page.appendChild(masthead(layout));
    page.appendChild(underline(summary));
    page.appendChild(glanceRow(summary, data, layout));

    const push = pushSection(summary.top_priority);
    if (push) page.appendChild(push);
    page.appendChild(section('Top to-dos', todoList(summary)));
    page.appendChild(section('Habits', habitList(summary.habits || [])));
    page.appendChild(section('Your day', dayTimeline(summary.calendar)));
    page.appendChild(section('New updates', updatesList(data.highlights || [])));
    page.appendChild(section('Journal', journalPrompt(summary.journal)));
    const later = laterList(data);
    if (later) page.appendChild(section('Later & recent', later));
    page.appendChild(footer(summary));

    view.innerHTML = '';
    view.appendChild(page);
  }
