
  // ---------- Today: the daily brief ----------
  // Declarations only, loaded before app.js (see the note atop jobs.js).
  //
  // Layout follows the editorial "morning brief": a painting masthead
  // with the day's title, the brief paragraph, an at-a-glance row of
  // small widgets you can reorder or hide, then labeled sections - label
  // on the left, content on the right.

  const TODAY_WIDGETS = [
    {id: 'journey', label: 'Journey'},
    {id: 'weather', label: 'Weather'},
    {id: 'interviews', label: 'Interviews'},
    {id: 'practice', label: 'Practice to review'},
    {id: 'activity', label: 'Activity rings', wide: true},
    {id: 'habits', label: 'Habit rings'},
    {id: 'mood', label: 'Mood & energy'},
    {id: 'week', label: 'Week ahead'},
    {id: 'pipeline', label: 'Job pipeline'},
    {id: 'focus', label: 'Focus time'},
    {id: 'health', label: 'Sleep & workouts'},
  ];
  // Habit rings start hidden: the Habits section lists the same habits.
  const DEFAULT_LAYOUT = {order: TODAY_WIDGETS.map(w => w.id), hidden: ['habits'], art: true, v: 2};

  function todayLayout() {
    const saved = prefs.get('todayLayout', null) || {};
    const known = TODAY_WIDGETS.map(w => w.id);
    // Keep the saved order, drop ids that no longer exist, append new ones.
    const order = (saved.order || []).filter(id => known.includes(id));
    known.forEach(id => { if (!order.includes(id)) order.push(id); });
    const hidden = (saved.hidden || []).filter(id => known.includes(id));
    // Layouts saved before v2 pick up the new default of hiding habit rings once.
    if ((saved.v || 1) < 2 && !hidden.includes('habits')) hidden.push('habits');
    return {order, hidden, art: saved.art !== false, v: 2};
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

  // From 6pm Today turns into the evening wind-down: what got done, what
  // to carry over, and the journal - the counterpart to the morning brief.
  const EVENING_HOUR = 18;
  const isEvening = () => new Date().getHours() >= EVENING_HOUR;

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
      now.toLocaleDateString(undefined, {weekday: 'long'}) + (isEvening() ? ' Wind-down' : ' Brief')));
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
    const text = res.text ? res.text + ' '
      : greetingWord() + '. (Couldn’t write a brief: ' + (res.error || 'nothing to say') + '.) ';
    // The model sometimes marks names **like this**: show them bold.
    text.split(/\*\*(.+?)\*\*/g).forEach((part, i) =>
      el.appendChild(i % 2 ? tEl('strong', '', part) : document.createTextNode(part)));
    const again = tEl('button', 't-link', 'Rewrite');
    again.onclick = () => loadBrief(el, true);
    el.appendChild(again);
  }

  // ---------- at a glance ----------

  function glanceRow(summary, data, layout) {
    const row = tEl('section', 't-glance');
    row.setAttribute('aria-label', 'At a glance');
    layout.order.filter(id => !layout.hidden.includes(id)).forEach(id => {
      const w = {journey: journeyTile, interviews: interviewsTile, practice: practiceTile, weather: weatherTile, activity: activityRings, habits: habitRings, mood: moodChart, week: weekStrip, pipeline: pipelineTiles,
                 focus: focusTile, health: healthTile}[id];
      const tile = w(summary, data);
      if (tile) row.appendChild(tile);
    });
    const edit = tEl('button', 't-link t-customize', 'Edit widgets');
    edit.onclick = () => openWidgetSheet();
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
    // A line through one or two points says nothing: show the latest
    // numbers until there are enough days to draw a trend.
    if (trend.length < 3) {
      const latest = trend[trend.length - 1];
      const row = tEl('div', 't-mood-now');
      MOOD_SERIES.forEach(series => {
        const cell = tEl('div', 't-mood-cell');
        const num = tEl('div', 't-stat-num', latest[series.key] ? latest[series.key] + '/5' : '–');
        cell.appendChild(num);
        const label = tEl('div', 't-stat-label', series.label);
        label.style.setProperty('--dot', series.color);
        cell.appendChild(label);
        row.appendChild(cell);
      });
      tile.appendChild(row);
      tile.appendChild(tEl('div', 't-note', 'A trend line appears after 3 days of ratings.'));
      return tile;
    }
    // Drawn at roughly its on-screen size so 11px labels stay 11px.
    const W = 400, H = 96, PADL = 6, PADR = 56, PADT = 10, PADB = 10;
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
    (summary.assignments || []).forEach(a => add(a.due, a.title));
    const agenda = data.agenda || {};
    ['overdue', 'today', 'this_week'].forEach(k => (agenda[k] || []).forEach(n =>
      add(n.due_date < today ? today : n.due_date, n.title)));
    const strip = tEl('div', 't-week');
    for (let i = 0; i < 7; i++) {
      const day = addDays(today, i);
      const items = byDay[day] || [];
      const col = tEl('div', 't-week-day' + (i === 0 ? ' today' : ''));
      col.appendChild(tEl('div', 't-week-name',
        new Date(day + 'T12:00:00').toLocaleDateString(undefined, {weekday: 'short'})));
      if (i === 0) col.setAttribute('aria-label', 'Today');
      col.appendChild(tEl('div', 't-week-count', items.length ? String(items.length) : '–'));
      col.title = items.length ? items.join('\n') : 'Nothing due';
      strip.appendChild(col);
    }
    tile.appendChild(strip);
    return tile;
  }

  // Minutes per day this week: one series, one hue, bars anchored to the
  // baseline with rounded data-ends and 2px gaps (dataviz mark spec).
  // The total is the headline; per-day values are on hover.
  function focusTile(summary, data) {
    const f = data.focus;
    const tile = glanceTile('Focus this week', () => startFocus());
    if (!f) return tile;
    const head = tEl('div', 't-focus-head');
    head.appendChild(tEl('span', 't-stat-num', fmtMinutes(f.total)));
    head.appendChild(tEl('span', 't-stat-label', fmtMinutes(f.today) + ' today'));
    tile.appendChild(head);
    const W = 420, H = 56, GAP = 8, max = Math.max(...f.days, 60);
    const bw = (W - GAP * 6) / 7;
    const s = svg('svg', {viewBox: `0 0 ${W} ${H + 14}`, class: 't-bars', role: 'img',
      'aria-label': 'Focus minutes per day this week'});
    const todayIdx = (new Date().getDay() + 6) % 7;
    'MTWTFSS'.split('').forEach((d, i) => {
      const h = f.days[i] ? Math.max((f.days[i] / max) * H, 4) : 0;
      const x = i * (bw + GAP);
      if (h) {
        const bar = svg('rect', {x, y: H - h, width: bw, height: h, rx: 4, class: 't-bar'});
        const tip = svg('title');
        tip.textContent = fmtMinutes(f.days[i]);
        bar.appendChild(tip);
        s.appendChild(bar);
      }
      s.appendChild(svg('line', {x1: x, x2: x + bw, y1: H, y2: H, class: 't-grid'}));
      const label = svg('text', {x: x + bw / 2, y: H + 12, class: 't-axis' + (i === todayIdx ? ' today' : '')});
      label.textContent = d;
      s.appendChild(label);
    });
    tile.appendChild(s);
    const start = tEl('button', 't-link', prefs.get('focusTimer', null) ? 'Running…' : 'Start a session');
    start.onclick = e => { e.stopPropagation(); startFocus(); };
    tile.appendChild(start);
    return tile;
  }

  // Last seven nights as bars (one series, one hue), average as the
  // headline, and this week's workouts. Hidden until Health data exists.
  function healthTile(summary) {
    const h = summary.health;
    if (!h) return null;
    const tile = glanceTile('Sleep & workouts', null);
    const head = tEl('div', 't-focus-head');
    head.appendChild(tEl('span', 't-stat-num', h.avg_sleep ? fmtMinutes(h.avg_sleep) : '–'));
    head.appendChild(tEl('span', 't-stat-label', 'average sleep, last 7 nights'));
    tile.appendChild(head);
    const W = 420, H = 48, GAP = 8, max = Math.max(...h.sleep.map(n => n.minutes), 8 * 60);
    const bw = (W - GAP * 6) / 7;
    const s = svg('svg', {viewBox: `0 0 ${W} ${H + 14}`, class: 't-bars', role: 'img',
      'aria-label': 'Hours of sleep, last seven nights'});
    h.sleep.forEach((n, i) => {
      const x = i * (bw + GAP);
      if (n.minutes) {
        const bh = Math.max((n.minutes / max) * H, 4);
        const bar = svg('rect', {x, y: H - bh, width: bw, height: bh, rx: 4, class: 't-bar t-bar-sleep'});
        const tip = svg('title');
        tip.textContent = fmtShortDate(n.date) + ': ' + fmtMinutes(n.minutes);
        bar.appendChild(tip);
        s.appendChild(bar);
      }
      s.appendChild(svg('line', {x1: x, x2: x + bw, y1: H, y2: H, class: 't-grid'}));
      const label = svg('text', {x: x + bw / 2, y: H + 12, class: 't-axis'});
      label.textContent = new Date(n.date + 'T12:00:00').toLocaleDateString(undefined, {weekday: 'narrow'});
      s.appendChild(label);
    });
    tile.appendChild(s);
    const w = h.workouts;
    tile.appendChild(tEl('div', 't-item-sub', w.length
      ? w.length + ' workout' + (w.length > 1 ? 's' : '') + ' this week · '
        + fmtMinutes(w.reduce((a, x) => a + x.minutes, 0))
      : 'No workouts logged this week'));
    return tile;
  }

  function fmtMinutes(m) {
    return m < 60 ? m + ' min' : Math.floor(m / 60) + 'h' + (m % 60 ? ' ' + (m % 60) + 'm' : '');
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

  // ---------- weather ----------
  // Filled in after the tile is on screen; Today never waits on it. Hidden
  // until a city is set in Settings.
  function weatherTile() {
    const tile = glanceTile('Weather', () => openProfileView());
    tile.hidden = true;
    api('/api/weather').then(w => {
      if (!w.configured || w.error && !w.temp) return;
      tile.hidden = false;
      const unit = w.unit === 'celsius' ? '°C' : '°F';
      const head = tEl('div', 't-focus-head');
      head.appendChild(tEl('span', 't-stat-num', w.temp === undefined ? '–' : w.temp + unit));
      head.appendChild(tEl('span', 't-stat-label', (w.summary || '') + (w.place ? ' · ' + w.place : '')));
      tile.appendChild(head);
      if (w.high !== undefined) {
        tile.appendChild(tEl('div', 't-item-sub', 'High ' + w.high + unit + ' · Low ' + w.low + unit
          + (w.rain ? ' · ' + w.rain + '% chance of rain' : '')));
      }
    });
    return tile;
  }

  // ---------- activity rings ----------
  // Three nested rings, each a validated categorical hue: habit check-ins
  // against their weekly targets, focus time against a goal, and average
  // sleep against a goal. Arcs fill with a spring when the tile appears.
  const RING_DEFAULTS = {focusHours: 10, sleepHours: 8};
  const ringGoals = () => ({...RING_DEFAULTS, ...(prefs.get('ringGoals', {}) || {})});

  function activityRings(summary, data) {
    const goals = ringGoals();
    const habits = summary.habits || [];
    const habitDone = habits.reduce((n, h) => n + Math.min(h.this_week, h.target_per_week), 0);
    const habitTarget = habits.reduce((n, h) => n + h.target_per_week, 0);
    const focusMin = (data && data.focus && data.focus.total) || 0;
    const sleepMin = (summary.health && summary.health.avg_sleep) || 0;
    const rings = [
      {key: 'habits', label: 'Habits', color: '#3987e5', value: habitDone, goal: habitTarget,
       text: habitTarget ? habitDone + ' of ' + habitTarget + ' check-ins' : 'No habits yet'},
      {key: 'focus', label: 'Focus', color: '#d95926', value: focusMin, goal: goals.focusHours * 60,
       text: fmtMinutes(focusMin) + ' of ' + goals.focusHours + 'h'},
      {key: 'sleep', label: 'Sleep', color: '#199e70', value: sleepMin, goal: goals.sleepHours * 60,
       text: sleepMin ? fmtMinutes(sleepMin) + ' avg of ' + goals.sleepHours + 'h' : 'No Health data'},
    ];
    const tile = glanceTile('Activity · this week', null);
    tile.classList.add('wide');
    const body = tEl('div', 't-activity');
    const size = 120;
    const s = svg('svg', {viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: 'img',
      'aria-label': rings.map(r => r.label + ': ' + r.text).join('. ')});
    const arcs = [];
    rings.forEach((r, i) => {
      const radius = 50 - i * 14;
      const circ = 2 * Math.PI * radius;
      s.appendChild(svg('circle', {cx: 60, cy: 60, r: radius, class: 't-ring-track t-ring-wide'}));
      const arc = svg('circle', {cx: 60, cy: 60, r: radius, class: 't-ring-arc t-ring-wide',
        'stroke-dasharray': '0 ' + circ, transform: 'rotate(-90 60 60)'});
      arc.style.stroke = r.color;
      s.appendChild(arc);
      arcs.push([arc, r.goal ? Math.min(r.value / r.goal, 1) * circ : 0, circ]);
    });
    body.appendChild(s);
    const legend = tEl('div', 't-activity-legend');
    rings.forEach(r => {
      const row = tEl('div', 't-activity-row');
      const dot = tEl('span', 't-swatch');
      dot.style.background = r.color;
      row.appendChild(dot);
      row.appendChild(tEl('span', 't-activity-name', r.label));
      row.appendChild(tEl('span', 't-activity-text', r.text));
      legend.appendChild(row);
    });
    body.appendChild(legend);
    tile.appendChild(body);
    // Next frame, so the transition has a starting point to run from.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      arcs.forEach(([arc, len, circ]) => arc.setAttribute('stroke-dasharray', len + ' ' + circ));
    }));
    return tile;
  }

  // ---------- edit widgets ----------
  // A sheet with a switch per widget, up/down to reorder, and the goals
  // behind the rings. Every change saves at once; Today redraws on close.
  async function openWidgetSheet() {
    let layout = todayLayout();
    const body = tEl('div', 'widget-sheet');
    const save = next => { layout = next; prefs.set('todayLayout', next); paint(); };
    const move = (i, by) => {
      const order = layout.order.slice();
      [order[i], order[i + by]] = [order[i + by], order[i]];
      save({...layout, order});
    };
    function paint() {
      body.innerHTML = '';
      body.appendChild(tEl('div', 'widget-head', 'Widgets'));
      const list = tEl('div', 'group-list');
      layout.order.forEach((id, i) => {
        const w = TODAY_WIDGETS.find(x => x.id === id);
        const row = tEl('div', 'widget-row');
        row.appendChild(switchEl(!layout.hidden.includes(id), on => save({...layout,
          hidden: on ? layout.hidden.filter(h => h !== id) : layout.hidden.concat(id)}), 'Show ' + w.label));
        row.appendChild(tEl('span', 'widget-name', w.label));
        const up = tEl('button', 'stepper-btn', '↑');
        const down = tEl('button', 'stepper-btn', '↓');
        up.type = down.type = 'button';
        up.setAttribute('aria-label', 'Move ' + w.label + ' up');
        down.setAttribute('aria-label', 'Move ' + w.label + ' down');
        up.disabled = i === 0;
        down.disabled = i === layout.order.length - 1;
        up.onclick = () => move(i, -1);
        down.onclick = () => move(i, 1);
        row.appendChild(up);
        row.appendChild(down);
        list.appendChild(row);
      });
      body.appendChild(list);
      body.appendChild(settingRow('Daily painting', switchEl(layout.art, on => save({...layout, art: on}),
        'Daily painting')));
      const goals = ringGoals();
      body.appendChild(tEl('div', 'widget-head', 'Ring goals'));
      body.appendChild(settingRow('Focus per week', stepper(goals.focusHours, 1, 40, n => n + ' hours',
        n => prefs.set('ringGoals', {...ringGoals(), focusHours: n}), 'Focus hours per week')));
      body.appendChild(settingRow('Sleep per night', stepper(goals.sleepHours, 5, 11, n => n + ' hours',
        n => prefs.set('ringGoals', {...ringGoals(), sleepHours: n}), 'Sleep hours per night')));
      const reset = tEl('button', 'btn-plain', 'Reset layout');
      reset.onclick = () => save({...DEFAULT_LAYOUT, order: TODAY_WIDGETS.map(w => w.id)});
      body.appendChild(reset);
    }
    paint();
    await modal({title: 'Edit widgets', body, confirmLabel: 'Done', hideCancel: true});
    openDashboardView();
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

  const BUCKET_TAGS = {overdue: 'Overdue', today: 'Due today'};
  const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)';
  const AUTO_REMOVE_MS = 700;   // how long a checked row stays struck before it goes
  const SMALL_WORDS = new Set(['a', 'an', 'and', 'of', 'the', 'to', 'in', 'for', 'on']);

  // Marking a to-do done (or not) where it comes from.
  const TODO_DONE = {
    task: (ref, done) => jsonSend('/api/tasks/' + ref, {done}, 'PATCH'),
    assignment: (ref, done) => jsonSend('/api/canvas/done', {uid: ref, done}),
    step_task: (ref, done) => jsonSend('/api/journey/tasks/' + ref, {done}, 'PATCH'),
  };
  const markTodo = (action, mark, extra) => jsonSend('/api/today/marks', {action, ...mark, ...extra});
  const removeWhenDone = () => prefs.get('todayRemoveWhenDone', false);

  function titleCase(text) {
    return text.toLowerCase().split(/\s+/)
      .map((w, i) => i && SMALL_WORDS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  }

  // "W7M13: Design and Tech: Lighting [D10: INTRO TO THEATRE F26]" ->
  // {title: "Design and Tech: Lighting", course: "Intro to Theatre"}.
  function splitCourse(raw) {
    const m = raw.match(/^(.*?)\s*\[([^\]]+)\]\s*$/);
    if (!m) return {title: raw, course: ''};
    const title = m[1].replace(/^[A-Z]\d+[A-Z]\d+:\s*/, '').replace(/^[^\p{L}\p{N}]+/u, '') || m[1];
    const [code, name = ''] = m[2].split(/:\s*/);
    const cut = /(\.\.\.|…)$/.test(name);
    const course = name && !cut ? name.replace(/\s+[FWSU]\d{2}$/, '') : code.split(/\s+/).slice(0, 2).join(' ');
    return {title, course: titleCase(course)};
  }

  // Fades a row out and closes the gap it leaves; drops its group label
  // once the group is empty.
  function removeRow(row) {
    const list = row.parentElement;
    const done = () => {
      row.remove();
      list.querySelectorAll('.t-group').forEach(g => {
        const next = g.nextElementSibling;
        if (!next || !next.classList.contains('t-item')) g.remove();
      });
    };
    if (reducedMotion()) { done(); return; }
    row.style.overflow = 'hidden';
    row.animate([{opacity: 1, height: row.offsetHeight + 'px'},
                 {opacity: 0, height: '0px', paddingTop: '0px', paddingBottom: '0px'}],
                {duration: 220, easing: EASE_OUT}).onfinish = done;
  }

  // mark: {kind, ref, title, sub, group} for anything Today can cross off
  // or archive. Checking crosses it off in place (no reload); with
  // "Remove when done" on it then slides out to the archive.
  function todoRow(opts) {
    const row = tEl('div', 't-item' + (opts.overdue ? ' overdue' : '') + (opts.crossed ? ' done' : '')
      + (opts.pinned ? ' pinned' : ''));
    const mark = opts.mark;
    const canCheck = mark && TODO_DONE[mark.kind];
    if (canCheck || opts.onCheck) {
      const check = tEl('button', 'task-check');
      const label = () => check.setAttribute('aria-label',
        (row.classList.contains('done') ? 'Not done: ' : 'Mark done: ') + opts.title);
      label();
      check.onclick = async e => {
        e.stopPropagation();
        const nowDone = !row.classList.contains('done');
        row.classList.toggle('done', nowDone);
        label();
        if (opts.onToggled) opts.onToggled();
        if (!canCheck) { await opts.onCheck(); return; }
        const res = await TODO_DONE[mark.kind](mark.ref, nowDone);
        if (res.error) {
          row.classList.toggle('done', !nowDone);
          label();
          if (opts.onToggled) opts.onToggled();
          toast(res.error, {error: true});
          return;
        }
        await markTodo(nowDone ? 'cross' : 'uncross', mark);
        if (nowDone && removeWhenDone()) {
          setTimeout(async () => {
            if (!row.classList.contains('done')) return;   // unchecked meanwhile
            await markTodo('archive', mark, {done: true});
            removeRow(row);
          }, AUTO_REMOVE_MS);
        }
      };
      row.appendChild(check);
    } else {
      row.appendChild(tEl('span', 't-item-mark'));
    }
    const body = tEl('div', 't-item-body');
    body.appendChild(tEl('div', 't-item-title', opts.title));
    body.appendChild(tEl('div', 't-item-sub', opts.sub));
    row.appendChild(body);
    if (mark && opts.onPin) {
      const star = tEl('button', 't-star' + (opts.pinned ? ' on' : ''), opts.pinned ? '★' : '☆');
      star.title = opts.pinned ? 'Unstar' : 'Star as one of today’s 3';
      star.setAttribute('aria-label', (opts.pinned ? 'Unstar: ' : 'Star for today: ') + opts.title);
      star.setAttribute('aria-pressed', opts.pinned ? 'true' : 'false');
      star.onclick = e => { e.stopPropagation(); opts.onPin(!opts.pinned); };
      row.appendChild(star);
    }
    if (mark) {
      const trash = tEl('button', 't-trash');
      trash.innerHTML = TRASH_SVG;
      trash.title = 'Remove (goes to the archive)';
      trash.setAttribute('aria-label', 'Remove: ' + opts.title);
      trash.onclick = async e => {
        e.stopPropagation();
        const res = await markTodo('archive', mark, {done: row.classList.contains('done')});
        if (res.error) { toast(res.error, {error: true}); return; }
        removeRow(row);
        toast('Moved to the archive', {undo: async () => { await markTodo('forget', mark); openDashboardView(); }});
      };
      row.appendChild(trash);
    }
    if (opts.onOpen) makeClickable(row, opts.onOpen);
    return row;
  }

  const TRASH_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/>' +
    '<path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';

  function todoList(summary) {
    const list = tEl('div', 't-list');
    const tag = n => BUCKET_TAGS[n.bucket] || ('Due ' + fmtShortDate(n.due_date));
    const today = localISO(new Date());
    const marks = summary.today_marks || {crossed: [], pinned: [], hidden: []};
    const keyOf = m => m.kind + ':' + m.ref;
    const picked = new Set(marks.pinned.map(keyOf));
    // Starring redraws just this list, in place.
    const repin = async (mark, on) => {
      const res = await markTodo(on ? 'pin' : 'unpin', mark);
      if (res.error) { toast(res.error, {error: true}); return; }
      const fresh = await api('/api/today/marks');
      if (!fresh.error) summary.today_marks = fresh;
      list.replaceWith(todoList(summary));
    };
    const topLabel = tEl('h3', 't-group t-group-top');
    let topRows = [];
    const countTop = () => {
      const done = topRows.filter(r => r.classList.contains('done')).length;
      topLabel.textContent = 'Today’s ' + topRows.length + ' · ' + done + ' of ' + topRows.length + ' done';
    };
    const todoItem = opts => {
      if (!opts.mark) return todoRow(opts);
      const row = todoRow({...opts, pinned: picked.has(keyOf(opts.mark)), onPin: on => repin(opts.mark, on),
                           onToggled: () => countTop()});
      row.dataset.key = keyOf(opts.mark);
      return row;
    };
    const skip = new Set([...marks.hidden, ...marks.crossed.map(c => c.kind + ':' + c.ref)]);
    const shown = (kind, ref) => !skip.has(kind + ':' + ref);
    // A journey's steps open their own page; other roadmaps open the canvas.
    const openNode = n => (summary.journey_ids || []).includes(n.project_id)
      ? openStepAnywhere(n.project_id, n.node_id) : openRoadmapView(n.project_id, n.project_name);
    // A step whose own sub-step is already listed isn't named again, and
    // each journey shows only its next step.
    const covered = new Set((summary.step_tasks || []).map(t => t.node_id));
    const seenProject = new Set();
    const nextStep = n => {
      if (covered.has(n.node_id) || !shown('step', n.node_id) || seenProject.has(n.project_id)) return false;
      seenProject.add(n.project_id);
      return true;
    };
    const stepItem = (n, sub, overdue) => todoItem({
      title: n.title, overdue, sub: n.project_name + ' · ' + sub, onOpen: () => openNode(n),
      mark: {kind: 'step', ref: n.node_id, title: n.title, sub: n.project_name + ' · ' + sub, group: 'journeys'},
    });
    const groups = {classes: [], journeys: [], other: []};
    groups.other.push(
      ...(summary.tasks || []).filter(t => shown('task', t.task_id)).map(t => {
        const sub = (t.company ? t.company + ' · ' : '') + tag(t);
        return todoItem({
          title: t.title, overdue: t.bucket === 'overdue', sub,
          mark: {kind: 'task', ref: t.task_id, title: t.title, sub, group: 'other'},
          onOpen: t.application_id ? () => openJobsView(t.application_id) : null,
        });
      }),
      ...(summary.nudges || []).map(n => todoItem({
        title: 'Reach out to ' + n.name,
        sub: (n.context ? n.context + ' · ' : '') + sinceLabel(n.days_since),
        onCheck: () => talkedToday(n.person_id),
        onOpen: () => openPeopleView(),
      })),
      ...(summary.deadlines || []).map(d => todoItem({
        title: d.title, sub: 'Application deadline · ' + tag(d),
        onOpen: () => openJobsView(d.application_id),
      })));
    groups.classes.push(...(summary.assignments || []).filter(a => shown('assignment', a.uid)).map(a => {
      const {title, course} = splitCourse(a.title);
      const sub = (course || 'Assignment') + ' · ' + (a.due === today ? 'Due today' : 'Due ' + fmtShortDate(a.due))
        + (a.time ? ' ' + fmtClock(a.time) : '');
      return todoItem({
        title, sub, mark: {kind: 'assignment', ref: a.uid, title, sub, group: 'classes'},
        onOpen: a.url ? () => window.open(a.url, '_blank', 'noopener') : null,
      });
    }));
    groups.journeys.push(
      ...(summary.step_tasks || []).filter(t => shown('step_task', t.id)).map(t => {
        const sub = t.step_title + ' · ' + (t.due < today ? 'Overdue' : t.due === today ? 'Due today' : 'Due ' + fmtShortDate(t.due));
        return todoItem({
          title: t.title, overdue: t.due < today, sub,
          mark: {kind: 'step_task', ref: t.id, title: t.title, sub, group: 'journeys'},
          onOpen: () => openStepAnywhere(t.project_id, t.node_id),
        });
      }),
      ...(summary.due || []).filter(nextStep).map(n => stepItem(n, tag(n), n.bucket === 'overdue')),
      ...(summary.unblocked || []).filter(nextStep).map(n => stepItem(n, 'Ready to start', false)),
      ...(summary.recurring || []).filter(nextStep).map(n => stepItem(n, 'Coming up ' + fmtShortDate(n.due_date), false)));
    // What you've crossed off today stays, struck through, at the end of its group.
    marks.crossed.forEach(c => (groups[c.grp] || groups.other).push(todoItem({
      title: c.title, sub: c.sub, crossed: true, mark: {kind: c.kind, ref: c.ref, title: c.title, sub: c.sub, group: c.grp},
    })));
    // Today's 3 (starred) lead, in the order they were starred.
    const all = [...groups.classes, ...groups.journeys, ...groups.other];
    topRows = marks.pinned.map(p => all.find(r => r.dataset.key === keyOf(p))).filter(Boolean);
    const top = topRows;
    Object.keys(groups).forEach(k => { groups[k] = groups[k].filter(r => !top.includes(r)); });
    if (top.length) {
      list.appendChild(topLabel);
      countTop();
      top.forEach(r => list.appendChild(r));
    } else {
      list.appendChild(tEl('div', 't-pick-hint', 'Star up to 3 to make them today’s focus.'));
    }
    [['Classes', 'classes'], ['Journeys', 'journeys'], ['Other', 'other']].forEach(([label, key]) => {
      if (!groups[key].length) return;
      list.appendChild(tEl('h3', 't-group', label));
      groups[key].forEach(r => list.appendChild(r));
    });
    if (!top.length && !Object.values(groups).some(g => g.length)) list.appendChild(tEl('div', 't-empty', 'Nothing due. Enjoy it.'));
    const links = tEl('div', 't-list-links');
    const add = tEl('button', 't-link', '+ Add a to-do');
    add.onclick = () => quickAddTask();
    const archive = tEl('button', 't-link t-link-quiet', 'Archive');
    archive.onclick = () => openTodoArchive();
    links.append(add, archive);
    list.appendChild(links);
    return list;
  }

  // "Remove when done", beside the Top to-dos title.
  function removeWhenDoneSwitch() {
    const wrap = tEl('label', 't-auto-remove');
    wrap.appendChild(tEl('span', '', 'Remove when done'));
    wrap.appendChild(switchEl(removeWhenDone(), on => prefs.set('todayRemoveWhenDone', on), 'Remove when done'));
    return wrap;
  }

  // Everything removed from Today, newest first, each with Put back.
  async function openTodoArchive() {
    const res = await api('/api/today/archive');
    if (res.error) { toast(res.error, {error: true}); return; }
    const body = tEl('div', 't-archive');
    if (!res.items.length) body.appendChild(tEl('div', 't-empty', 'Nothing archived yet.'));
    res.items.forEach(item => {
      const row = tEl('div', 't-archive-row');
      const text = tEl('div', 't-item-body');
      text.appendChild(tEl('div', 't-item-title', item.title));
      text.appendChild(tEl('div', 't-item-sub', (item.done_on ? 'Done ' + fmtShortDate(item.done_on) : 'Removed')
        + (item.sub ? ' · ' + item.sub : '')));
      const back = tEl('button', 'btn-plain', 'Put back');
      back.onclick = async () => {
        back.disabled = true;
        const undo = item.done_on && TODO_DONE[item.kind] ? await TODO_DONE[item.kind](item.ref, false) : {};
        if (undo.error) { toast(undo.error, {error: true}); back.disabled = false; return; }
        await markTodo('forget', item);
        removeRow(row);
      };
      row.append(text, back);
      body.appendChild(row);
    });
    await modal({title: 'Archive', body, confirmLabel: 'Done', hideCancel: true});
    openDashboardView();
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
      const name = tEl('span', 't-habit-name', h.name);
      if (h.step) {
        const link = tEl('button', 'habit-step t-habit-step', '↳ ' + h.step.title);
        link.type = 'button';
        link.onclick = () => openStepAnywhere(h.step.project_id, h.step.id);
        name.appendChild(link);
      }
      row.appendChild(name);
      if (h.streak) row.appendChild(tEl('span', 't-habit-streak',
        h.streak + (h.unit === 'day' ? '-day' : '-week') + ' streak'));
      list.appendChild(row);
    });
    return list;
  }

  // The day as a list of times, the current or next event highlighted.
  function dayTimeline(calendar, freeTime) {
    const cal = calendar || {connected: false};
    const box = tEl('div', 't-day');
    if (!cal.connected) {
      const link = tEl('button', 't-link', cal.needs_reconnect
        ? 'Google Calendar needs reconnecting. Open Settings →'
        : 'Connect Google Calendar to see your day here. Open Settings →');
      link.type = 'button';
      link.onclick = () => openProfileView();
      box.appendChild(link);
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
    const rows = events.map(e => ({at: e.all_day ? '' : e.start, node: (() => {
      const row = tEl('div', 't-day-row' + (e === highlight ? ' current' : ''));
      row.appendChild(tEl('span', 't-day-time', e.all_day ? 'All day' : fmtClock(e.start)));
      row.appendChild(tEl('span', 't-day-title', e.title));
      return row;
    })()}));
    (freeTime || []).forEach(f => rows.push({at: f.start, node: freeRow(f)}));
    rows.sort((a, b) => a.at.localeCompare(b.at)).forEach(r => box.appendChild(r.node));
    return box;
  }

  function freeRow(f) {
    const row = tEl('div', 't-day-row free');
    row.appendChild(tEl('span', 't-day-time', fmtClock(f.start)));
    const body = tEl('div', '');
    body.appendChild(tEl('div', 't-day-title', 'Free until ' + fmtClock(f.end) + ' · '
      + fmtMinutes(f.minutes)));
    if (f.suggestion) {
      const tip = tEl('div', 't-item-sub');
      tip.appendChild(document.createTextNode('Good time for: ' + f.suggestion + ' '));
      const go = tEl('button', 't-link', 'Focus on it');
      go.onclick = () => startFocus({label: f.suggestion});
      tip.appendChild(go);
      body.appendChild(tip);
    }
    row.appendChild(body);
    return row;
  }

  function fmtClock(hm) {
    const [h, m] = hm.split(':').map(Number);
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})
      .replace(' AM', 'a').replace(' PM', 'p');
  }

  // GitHub first (review requests, failing CI, your open PRs), then
  // project highlights - one numbered feed.
  function updatesList(highlights, github) {
    const list = tEl('div', 't-list');
    const gh = (github && github.items) || [];
    if (!highlights.length && !gh.length) {
      list.appendChild(tEl('div', 't-empty', 'Project highlights and GitHub activity show up here.'));
      return list;
    }
    gh.forEach((g, i) => {
      const row = tEl('div', 't-update');
      row.appendChild(tEl('span', 't-update-num', String(i + 1).padStart(2, '0')));
      const body = tEl('div', 't-item-body');
      const title = tEl('div', 't-item-title', g.title + ' ');
      title.appendChild(tEl('span', 't-repo', g.repo));
      body.appendChild(title);
      body.appendChild(tEl('div', 't-item-sub', g.detail));
      row.appendChild(body);
      makeClickable(row, () => window.open(g.url, '_blank', 'noopener'));
      list.appendChild(row);
    });
    highlights.forEach((h, j) => {
      const i = j + gh.length;
      const row = tEl('div', 't-update');
      row.appendChild(tEl('span', 't-update-num', String(i + 1).padStart(2, '0')));
      const body = tEl('div', 't-item-body');
      body.appendChild(tEl('div', 't-item-title', h.headline));
      body.appendChild(tEl('div', 't-item-sub', h.project_name));
      row.appendChild(body);
      makeClickable(row, () => openProject(h.project_id));
      list.appendChild(row);
    });
    // The first few; the rest behind a link.
    const rows = [...list.querySelectorAll('.t-update')];
    if (rows.length > UPDATES_SHOWN) {
      rows.slice(UPDATES_SHOWN).forEach(r => { r.hidden = true; });
      const more = tEl('button', 't-link t-link-quiet', 'Show ' + (rows.length - UPDATES_SHOWN) + ' more');
      more.onclick = () => { rows.forEach(r => { r.hidden = false; }); more.remove(); };
      list.appendChild(more);
    }
    return list;
  }
  const UPDATES_SHOWN = 3;

  // One saved link a day, oldest unread first.
  function readThis(reading) {
    const box = tEl('div', 't-list');
    const pick = reading.pick;
    box.appendChild(todoRow({title: pick.title, sub: new URL(pick.url).hostname + ' · saved '
      + relTime(pick.saved_at) + (reading.unread > 1 ? ' · ' + (reading.unread - 1) + ' more unread' : ''),
      onOpen: () => window.open(pick.url, '_blank', 'noopener')}));
    const done = tEl('button', 't-link', 'Mark as read');
    done.onclick = async () => {
      await jsonSend('/api/reading/read', {url: pick.url});
      openDashboardView();
    };
    box.appendChild(done);
    return box;
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

  function finishedList(summary) {
    const list = tEl('div', 't-list');
    const habits = (summary.habits || []).filter(h => h.done_today);
    (summary.finished_today || []).forEach(t => list.appendChild(todoRow({
      title: t.title, sub: t.company ? t.company + ' · Done' : 'Done'})));
    habits.forEach(h => list.appendChild(todoRow({title: h.name, sub: 'Habit · Done'})));
    list.querySelectorAll('.t-item').forEach(r => r.classList.add('finished'));
    if (!list.childNodes.length) {
      list.appendChild(tEl('div', 't-empty', 'Nothing checked off yet — that’s fine. Rest counts.'));
    }
    return list;
  }

  function carryOver(summary) {
    const open = (summary.tasks || []).filter(t => t.bucket === 'overdue' || t.bucket === 'today');
    if (!open.length) return null;
    const box = tEl('div', 't-list');
    open.forEach(t => box.appendChild(todoRow({title: t.title, overdue: t.bucket === 'overdue',
      sub: (t.company ? t.company + ' · ' : '') + (BUCKET_TAGS[t.bucket] || '')})));
    const btn = tEl('button', 'btn-primary jobs-btn t-carry', 'Move all to tomorrow');
    btn.onclick = async () => {
      const res = await jsonSend('/api/tasks/roll', {});
      if (res.error) { toast(res.error, {error: true}); return; }
      toast('Moved ' + res.moved + ' to tomorrow');
      openDashboardView();
    };
    box.appendChild(btn);
    return box;
  }

  function laterList(data) {
    const list = tEl('div', 't-list');
    const agenda = data.agenda || {};
    const items = (agenda.this_week || []).concat(agenda.later || []).slice(0, 8);
    items.forEach(n => list.appendChild(todoRow({
      title: n.title, sub: n.project_name + ' · Due ' + fmtShortDate(n.due_date),
      onOpen: () => openRoadmapView(n.project_id, n.project_name),
    })));
    (data.recent || []).slice(0, 5).forEach(c => list.appendChild(todoRow({
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
    const [data, summary, focus, reading, github, steps, marks] = await Promise.all([
      api('/api/dashboard'), api('/api/daily-summary'), api('/api/focus/week'),
      api('/api/reading'), api('/api/github'), api('/api/journey/due'), api('/api/today/marks'),
    ]);
    summary.today_marks = marks.error ? null : marks;
    data.focus = focus;
    summary.step_tasks = steps.tasks || [];
    summary.journey_ids = steps.journey_ids || [];
    const layout = todayLayout();
    const page = tEl('div', 't-page');
    page.appendChild(masthead(layout));
    page.appendChild(underline(summary));
    // The to-dos come first: they're what Today is for. The glance widgets follow.
    const todos = section(isEvening() ? 'Coming up' : 'Top to-dos', todoList(summary));
    todos.querySelector('.t-head').appendChild(removeWhenDoneSwitch());
    if (isEvening()) {
      page.appendChild(section('What you finished', finishedList(summary)));
      const carry = carryOver(summary);
      if (carry) page.appendChild(section('Carry over', carry));
      page.appendChild(todos);
      page.appendChild(glanceRow(summary, data, layout));
      page.appendChild(section('Journal', journalPrompt(summary.journal)));
    } else {
      page.appendChild(todos);
      page.appendChild(glanceRow(summary, data, layout));
    }
    page.appendChild(section('Habits', habitList(summary.habits || [])));
    page.appendChild(section('Your day', dayTimeline(summary.calendar, summary.free_time)));
    page.appendChild(section('New updates', updatesList(data.highlights || [], github)));
    if (reading.pick) page.appendChild(section('Read this', readThis(reading)));
    if (!isEvening()) page.appendChild(section('Journal', journalPrompt(summary.journal)));
    // Sunday is review day.
    if (new Date().getDay() === 0) {
      const go = tEl('button', 't-link', 'Look back on this week and set next week’s top three →');
      go.onclick = () => openWeekView();
      page.appendChild(section('Weekly review', go));
    }
    const later = laterList(data);
    if (later) page.appendChild(section('Later & recent', later));
    page.appendChild(footer(summary));

    view.innerHTML = '';
    view.appendChild(page);
  }
