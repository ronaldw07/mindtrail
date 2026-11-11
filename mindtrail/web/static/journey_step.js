  // ---------- journey: one step's own page ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Clicking a step on the timeline opens its page: daily goals you check
  // off each day (habits tied to the step), then a route of one-off
  // sub-steps ending at the step itself. The assistant can plan both.

  let journeyFocus = null;   // the step whose page is open, or null for the timeline
  // Half-typed text in a step page's add boxes, so a tick (which redraws
  // the page) doesn't wipe it. Keyed by step id and box.
  const journeyDrafts = {};
  function keepDraft(input, key) {
    input.value = journeyDrafts[key] || '';
    input.addEventListener('input', () => { journeyDrafts[key] = input.value; });
    return () => { delete journeyDrafts[key]; };
  }
  const GOAL_DAYS = 7;       // days shown in a daily goal's strip
  const GOAL_BACKFILL = 7;   // how far back a missed day can still be checked
  const GOAL_OFTEN = [[7, 'Every day'], [5, '5× a week'], [3, '3× a week'], [1, 'Once a week']];

  function journeyFindStep(id) {
    for (const t of journeyData.tracks) {
      const s = t.steps.find(x => x.id === id);
      if (s) return {...s, track: t.name, shared: t.shared, color: journeyTrackColor(t)};
    }
    return null;
  }

  async function openJourneyStep(id) {
    journeyFocus = id;
    await renderJourney();
    $('journey-view').scrollTop = 0;
    const back = document.querySelector('.jstep .jcrumb-back');
    if (back) back.focus({preventScroll: true});
  }

  // From Today or Habits: open the step's journey first. Always ask the
  // server - the copy of journeyData here can be from a journey since left.
  // From Today or Habits: a step's page, or (no step - a goal for a whole
  // path or journey) the journey itself.
  async function openStepAnywhere(projectId, nodeId) {
    const res = await jsonSend('/api/journey/select', {project_id: projectId});
    if (res.error) { toast(res.error, {error: true}); return; }
    await openJourneyView(nodeId ? {detail: true, step: nodeId} : {detail: true});
  }

  async function closeJourneyStep() {
    const id = journeyFocus;
    journeyFocus = null;
    await renderJourney();
    const chip = document.querySelector('[data-key="step:' + id + '"]');
    if (chip) { chip.scrollIntoView({block: 'center'}); chip.focus({preventScroll: true}); }
  }

  const journeyTermLabel = term => {
    for (const y of journeyData.years) for (const t of y.terms) if (t.term === term) return t.label;
    return 'No term yet';
  };

  function localIsoDate(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  const shortDay = iso => new Date(iso + 'T12:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
  // Plans and suggestions ask first when what you've told it doesn't
  // cover something that would change them (e.g. which internships).
  // Sent to the assistant alongside the message, not shown in the chat.
  const ASK_FIRST = 'If what I\'ve told you doesn\'t already say something that would change this, ask me that first.';
  const planPrompt = s => 'Plan out "' + s.title + '": break it into concrete things I can do, in order, with dates.';
  // Start a step like a tutorial: the assistant asks a few quick questions
  // (tap an answer or type one), then lays out the route from them.
  const guidePrompt = s => 'Help me get started on "' + s.title + '".';
  const walkPrompt = (s, t) => 'Walk me through "' + t.title + '" (part of "' + s.title + '"), one small step at a time.';
  const startGuide = s => askJourneyAssistant(guidePrompt(s), {fresh: true, title: 'Start: ' + s.title});
  const walkThrough = (s, t) => askJourneyAssistant(walkPrompt(s, t), {fresh: true, title: 'Guide: ' + t.title});
  const goalsPrompt = s => 'Suggest daily goals for "' + s.title + '" that I can check off each day.';

  async function renderJourneyStep(view, s) {
    const data = await api('/api/journey/steps/' + s.id + '/tasks');
    if (data.error) { toast(data.error, {error: true}); journeyFocus = null; await renderJourney(); return; }
    const page = tEl('div', 'jstep');
    page.style.setProperty('--c', s.color);
    const bar = tEl('div', 'jcrumb');
    bar.appendChild(journeyBackButton(journeyData.name, closeJourneyStep));
    page.append(bar, journeyStepHead(s, data.tasks), ...(data.tasks.length ? [journeyStepProgress(data.tasks)] : []),
      journeyStepSection('Daily goals', journeyGoals(s, data.goals, data.today)),
      journeyStepSection('Route', journeyRoute(s, data.tasks)));
    commitView(view, page);
  }

  function journeyStepSection(label, content) {
    const sec = tEl('section', 'jstep-section');
    sec.appendChild(tEl('h3', 'jstep-label', label));
    sec.appendChild(content);
    return sec;
  }

  function journeyStepHead(s, tasks) {
    const head = tEl('div', 'jstep-head');
    const meta = tEl('div', 'jstep-meta');
    meta.appendChild(tEl('span', 'jstep-dot'));
    const when = journeyIsMap() ? (s.due_date ? 'By ' + shortDay(s.due_date) : 'No date') : journeyTermLabel(s.term);
    meta.appendChild(tEl('span', '', (s.shared ? 'Every path' : s.track) + ' · ' + when));
    const status = tEl('button', 'jstep-status ' + s.status, JOURNEY_STATUS_WORD[s.status] + ' ▾');
    status.type = 'button';
    status.setAttribute('aria-label', 'Status: ' + JOURNEY_STATUS_WORD[s.status] + '. Change status');
    status.onclick = () => showMenuFrom(status, JOURNEY_STATUSES.filter(([v]) => v !== s.status)
      .map(([v, word]) => ({label: 'Mark ' + word, run: async () => {
        const res = await jsonSend('/api/roadmap-node/' + s.id, {status: v}, 'PATCH');
        if (res.error) toast(res.error, {error: true});
        await renderJourney([s.id]);
      }})));
    meta.appendChild(status);
    head.appendChild(meta);
    // Click the title or the details to change them in place.
    const title = tEl('div', 'proj-title jstep-editable', s.title);
    title.title = 'Rename';
    makeClickable(title, () => journeyRenameStep(s));
    head.appendChild(title);
    const detail = tEl('p', 'jstep-detail jstep-editable' + (s.detail ? '' : ' empty'), s.detail || 'Add details…');
    detail.title = 'Edit details';
    makeClickable(detail, () => journeyEditStepDetail(s));
    head.appendChild(detail);

    const hasPlan = tasks.some(t => !t.done);
    const more = tEl('button', 'jhead-more', '⋯');
    more.type = 'button';
    more.title = 'More';
    more.setAttribute('aria-label', 'More step options');
    more.onclick = () => showMenuFrom(more, [
      {label: 'Edit step…', run: () => journeyStepSheet(s)},
      ...(hasPlan ? [{label: 'Redo plan', run: () => askJourneyAssistant(
        'Redo the plan for "' + s.title + '". Keep what I\'ve done; replace the rest with a better route, '
        + 'with no two sub-steps that repeat each other.',
        {fresh: true, title: 'Redo plan: ' + s.title, hint: ASK_FIRST})}] : []),
      {label: 'Suggest daily goals', run: () => askJourneyAssistant(goalsPrompt(s), {fresh: true, title: 'Daily goals: ' + s.title, hint: ASK_FIRST})},
      {label: 'Sort route by date', run: () => journeySortRoute(s, tasks)},
      {divider: true},
      {label: 'Rename…', run: () => journeyRenameStep(s)},
      ...journeyPaths().filter(t => t.id !== s.track_id && !s.shared)
        .map(t => ({label: 'Move to ' + t.name, run: () => journeyMoveStep(s, t.id)})),
      {divider: true},
      {label: 'Clear unfinished sub-steps', danger: true, run: () => journeyClearRoute(s, tasks)},
      {label: 'Delete step', danger: true, run: async () => {
        journeyFocus = null;
        await renderJourney();
        softDelete({key: 'step:' + s.id, label: 'Step',
          remove: () => api('/api/roadmap-node/' + s.id, {method: 'DELETE'}), rerender: journeyRerender});
      }},
    ]);
    // The ⋯ sits at the end of the status line rather than on a row of its own.
    meta.appendChild(more);
    return head;
  }

  async function journeyEditStepDetail(s) {
    const detail = await modal({title: 'Details', input: true, multiline: true, value: s.detail,
                                placeholder: 'What this step involves', confirmLabel: 'Save'});
    if (detail === null || detail === s.detail) return;
    const res = await jsonSend('/api/roadmap-node/' + s.id, {title: s.title, detail}, 'PATCH');
    if (res.error) toast(res.error, {error: true});
    await renderJourney([s.id]);
  }

  async function journeyMoveStep(s, trackId) {
    const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: s.term, track_id: trackId});
    if (res.error) toast(res.error, {error: true});
    await renderJourney([s.id]);
  }

  // The last stop of a step's route ticked off: the step is done too. Say
  // what's next, so the journey keeps moving.
  function journeyStepFinished(s) {
    const next = (journeyData.next_up || []).find(n => n.id !== s.id);
    toast('“' + s.title + '” done' + (next ? ' · Next up: ' + next.title : ''), {seconds: 5});
  }

  async function journeySortRoute(s, tasks) {
    const order = [...tasks.filter(t => t.done),
      ...tasks.filter(t => !t.done).sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999'))];
    await journeySaveOrder(s, order.map(t => t.id));
  }

  async function journeyClearRoute(s, tasks) {
    const open = tasks.filter(t => !t.done).length;
    if (!open) { toast('Nothing unfinished to clear'); return; }
    if (!(await askConfirm('Clear the route?', open + ' unfinished sub-step' + (open === 1 ? '' : 's') +
      ' will be removed. Done ones stay.', 'Clear'))) return;
    const res = await jsonSend('/api/journey/steps/' + s.id + '/tasks/clear', {});
    if (res.error) toast(res.error, {error: true});
    await renderJourney([s.id]);
  }

  async function journeySaveOrder(s, ids) {
    const res = await jsonSend('/api/journey/steps/' + s.id + '/tasks/order', {order: ids});
    if (res.error) toast(res.error, {error: true});
    await renderJourney();
  }

  function journeyStepProgress(tasks) {
    const wrap = tEl('div', 'jstep-progress');
    const done = tasks.filter(t => t.done).length;
    const track = tEl('div', 'jstep-bar');
    const fill = tEl('span');
    fill.style.setProperty('--p', (tasks.length ? Math.round(done / tasks.length * 100) : 0) + '%');
    track.appendChild(fill);
    wrap.appendChild(track);
    wrap.appendChild(tEl('div', 'jstep-count', tasks.length ? done + ' of ' + tasks.length + ' sub-steps done' : 'No sub-steps yet'));
    return wrap;
  }

  // ---------- daily goals ----------

  function journeyGoals(s, goals, today) {
    const box = tEl('div', 'jgoals');
    goals.forEach(g => box.appendChild(journeyGoalRow(g, today, s)));
    if (!goals.length) {
      const empty = tEl('div', 'jgoals-empty');
      empty.appendChild(tEl('span', '', 'Things to do regularly for this step, checked off each day.'));
      const ask = tEl('button', 'btn-plain', 'Suggest some');
      ask.type = 'button';
      ask.onclick = () => askJourneyAssistant(goalsPrompt(s), {fresh: true, title: 'Daily goals: ' + s.title, hint: ASK_FIRST});
      empty.appendChild(ask);
      box.appendChild(empty);
    }
    box.appendChild(journeyGoalAdd(s));
    return box;
  }

  // s is the step whose page this is on, or null on the journey page.
  function journeyGoalRow(g, today, s) {
    const row = tEl('div', 'jgoal' + (g.done_today ? ' done' : ''));
    row.dataset.key = 'goal:' + g.id;
    const check = tEl('button', 'jgoal-check', g.done_today ? '✓' : '');
    check.type = 'button';
    check.dataset.focus = 'goal:' + g.id;
    check.setAttribute('aria-pressed', g.done_today ? 'true' : 'false');
    check.setAttribute('aria-label', (g.done_today ? 'Undo today: ' : 'Done today: ') + g.name);
    check.onclick = async () => { row.classList.toggle('done'); await toggleHabit(g); await renderJourney(); };

    const body = tEl('div', 'jgoal-body');
    body.appendChild(tEl('div', 'jgoal-name', g.name));
    const often = (GOAL_OFTEN.find(([n]) => n === g.target_per_week) || [0, g.target_per_week + '× a week'])[1];
    body.appendChild(tEl('div', 'jgoal-meta', often + ' · ' + g.this_week + (g.unit === 'day' ? ' this week' :
      ' of ' + g.target_per_week + ' this week') + (g.streak ? ' · ' + g.streak + '-' + g.unit + ' streak' : '')));
    const scope = g.scope || {kind: 'step'};
    if (scope.kind !== 'step' || !s) {
      body.querySelector('.jgoal-meta').appendChild(tEl('span', 'jgoal-scope ' + scope.kind,
        scope.kind === 'journey' ? 'Whole journey' : scope.kind === 'path' ? scope.name : 'One step'));
    }

    const more = tEl('button', 'jhead-more jgoal-more', '⋯');
    more.type = 'button';
    more.dataset.focus = 'goal-more:' + g.id;
    more.setAttribute('aria-label', 'Options for ' + g.name);
    more.onclick = () => showMenuFrom(more, journeyGoalMenu(g, s));
    row.append(check, body, journeyGoalStrip(g, today), more);
    onRightClick(row, e => showMenu(e, journeyGoalMenu(g, s)));
    return row;
  }

  // The last two weeks, one square per day; the last week can be checked.
  function journeyGoalStrip(g, today) {
    const strip = tEl('div', 'jgoal-strip');
    const logged = new Set(g.logs);
    const end = new Date(today + 'T12:00');
    for (let i = GOAL_DAYS - 1; i >= 0; i--) {
      const d = new Date(end);
      d.setDate(end.getDate() - i);
      const iso = localIsoDate(d);
      const cell = tEl('button', 'jgoal-day' + (logged.has(iso) ? ' on' : '') + (i === 0 ? ' today' : ''));
      cell.type = 'button';
      cell.dataset.focus = 'day:' + g.id + ':' + iso;
      if (i < GOAL_BACKFILL) cell.dataset.letter = d.toLocaleDateString(undefined, {weekday: 'narrow'});
      const label = d.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
      cell.title = label + (logged.has(iso) ? ' · done' : '');
      cell.setAttribute('aria-label', label + (logged.has(iso) ? ', done' : ', not done'));
      if (i < GOAL_BACKFILL) {
        cell.onclick = async () => { cell.classList.toggle('on'); await toggleHabit(g, iso); await renderJourney(); };
      } else {
        cell.disabled = true;
      }
      strip.appendChild(cell);
    }
    return strip;
  }

  function journeyGoalMenu(g, s) {
    const save = async patch => {
      const res = await jsonSend('/api/habits/' + g.id, patch, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderJourney();
    };
    return [
      {label: 'Rename…', run: async () => { const name = await askText('Rename goal', g.name); if (name) save({name}); }},
      ...GOAL_OFTEN.filter(([n]) => n !== g.target_per_week)
        .map(([n, word]) => ({label: word, run: () => save({target_per_week: n})})),
      {divider: true},
      ...journeyGoalPlaces(g, s),
      {divider: true},
      {label: 'Delete', danger: true, run: () => softDelete({key: 'goal:' + g.id, label: 'Daily goal',
        remove: () => api('/api/habits/' + g.id, {method: 'DELETE'}), rerender: journeyRerender})},
    ];
  }

  // The journey page's own daily goals: ones for the whole journey and ones
  // for a single path. A step's own goals live on its page.
  function journeyDailyGoals(data) {
    const sec = tEl('section', 'jday');
    sec.appendChild(tEl('h3', 'jstep-label', 'Daily goals'));
    const box = tEl('div', 'jgoals');
    (data.goals || []).forEach(g => box.appendChild(journeyGoalRow(g, data.today, null)));
    box.appendChild(journeyPageGoalAdd());
    sec.appendChild(box);
    return sec;
  }

  function journeyPageGoalAdd() {
    const form = tEl('form', 'jgoal-add');
    const input = tEl('input', 'jroute-add-input');
    input.placeholder = 'Add a daily goal…';
    input.setAttribute('aria-label', 'Add a daily goal');
    const clearDraft = keepDraft(input, journeyData.project_id + ':goal');
    const often = tEl('select', 'jgoal-often');
    often.setAttribute('aria-label', 'How often');
    GOAL_OFTEN.forEach(([n, word]) => { const o = tEl('option', '', word); o.value = n; often.appendChild(o); });
    const scope = tEl('select', 'jgoal-often');
    scope.setAttribute('aria-label', 'Applies to');
    [['', 'Whole journey'], ...journeyPaths().map(t => [t.id, 'All of ' + t.name])]
      .forEach(([v, word]) => { const o = tEl('option', '', word); o.value = v; scope.appendChild(o); });
    form.append(input, often, scope);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!input.value.trim()) return;
      const res = await jsonSend('/api/journey/goals', {name: input.value, per_week: Number(often.value),
        scope: scope.value ? 'path' : 'journey', track_id: scope.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      clearDraft();
      await renderJourney();
    };
    return form;
  }

  // "Applies to" choices for a goal: this step, a path, or the journey.
  function journeyGoalPlaces(g, s) {
    const kind = (g.scope || {kind: 'step'}).kind;
    const move = async body => {
      const res = await jsonSend('/api/journey/goals/' + g.id + '/scope', body);
      if (res.error) toast(res.error, {error: true});
      await renderJourney();
    };
    const paths = s ? (s.shared ? [] : [{id: s.track_id, name: s.track}]) : journeyPaths();
    return [
      ...(s && kind !== 'step' ? [{label: 'Only for this step', run: () => move({scope: 'step', node_id: s.id})}] : []),
      ...paths.filter(t => !(kind === 'path' && (g.track_id ? g.track_id === t.id : !!s)))
        .map(t => ({label: 'For all of ' + t.name, run: () => move({scope: 'path', track_id: t.id})})),
      ...(kind !== 'journey' ? [{label: 'For the whole journey',
        run: () => move({scope: 'journey', node_id: s ? s.id : ''})}] : []),
    ];
  }

  // Sends what they typed for the AI to fill out; the box shows it's
  // working meanwhile. The reply, or null after showing an error.
  async function journeyFillAdd(input, url, body) {
    const typed = input.value;
    input.disabled = true;
    input.value = 'Adding…';
    const res = await jsonSend(url, body);
    input.disabled = false;
    input.value = typed;
    if (res.error) { toast(res.error, {error: true}); return null; }
    if (!res.filled) toast('Couldn\'t reach the AI, so it was saved as typed.');
    return res;
  }

  function journeyGoalAdd(s) {
    const form = tEl('form', 'jgoal-add');
    const input = tEl('input', 'jroute-add-input');
    input.placeholder = 'Add a daily goal… e.g. stretch 3x a week';
    input.setAttribute('aria-label', 'Add a daily goal');
    const clearDraft = keepDraft(input, s.id + ':goal');
    form.appendChild(input);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!input.value.trim()) return;
      const res = await journeyFillAdd(input, '/api/journey/steps/' + s.id + '/goals', {name: input.value, fill: true});
      if (!res) return;
      clearDraft();
      await renderJourney();
    };
    return form;
  }

  // ---------- the route ----------

  // "Next" is the unfinished stop due soonest, else the first unfinished one.
  function journeyNextStop(tasks) {
    const open = tasks.filter(t => !t.done);
    const dated = open.filter(t => t.due).sort((a, b) => a.due.localeCompare(b.due));
    return dated[0] || open[0];
  }

  // A long route shows what's next until you ask for the rest.
  const ROUTE_SHOWN = 3;
  const journeyRouteOpen = new Set();   // step ids whose whole route is shown

  function journeyRouteVisible(s, tasks, next) {
    if (tasks.length <= ROUTE_SHOWN || journeyRouteOpen.has(s.id)) return tasks;
    const open = tasks.filter(t => !t.done);
    const shown = open.slice(0, ROUTE_SHOWN);
    if (next && !shown.includes(next)) shown[shown.length - 1] = next;
    return tasks.filter(t => shown.includes(t));
  }

  function journeyRoute(s, tasks) {
    const route = tEl('ol', 'jroute');
    const today = localIsoDate(new Date());
    const next = journeyNextStop(tasks);
    const visible = journeyRouteVisible(s, tasks, next);
    visible.forEach(t => route.appendChild(journeyRouteStop(s, t, tasks, tasks.indexOf(t), {
      isNext: t === next, isOverdue: !t.done && t.due && t.due < today})));
    if (visible.length < tasks.length || journeyRouteOpen.has(s.id)) {
      const li = tEl('li', 'jroute-showall');
      const done = tasks.filter(t => t.done).length;
      const more = tEl('button', 'btn-plain', journeyRouteOpen.has(s.id) ? 'Show less'
        : 'Show all ' + tasks.length + (done ? ' · ' + done + ' done' : ''));
      more.type = 'button';
      more.onclick = () => {
        if (journeyRouteOpen.has(s.id)) journeyRouteOpen.delete(s.id); else journeyRouteOpen.add(s.id);
        renderJourney();
      };
      li.appendChild(more);
      route.appendChild(li);
    }
    if (!tasks.length) route.appendChild(journeyRouteEmpty(s));
    route.appendChild(journeyRouteAdd(s));
    if (tasks.length) route.appendChild(journeyRouteGoal(s, tasks));
    return route;
  }

  function journeyRouteStop(s, t, tasks, index, {isNext, isOverdue}) {
    const stop = tEl('li', 'jroute-stop' + (t.done ? ' done' : '') + (isNext ? ' next' : '') + (isOverdue ? ' overdue' : ''));
    stop.dataset.key = 'task:' + t.id;

    const dot = tEl('button', 'jroute-dot', t.done ? '✓' : '');
    dot.type = 'button';
    dot.dataset.focus = 'task:' + t.id;
    dot.setAttribute('aria-label', (t.done ? 'Mark not done: ' : 'Mark done: ') + t.title);
    dot.onclick = async () => {
      const patch = {done: !t.done};
      // A stop that asks for a result can't be ticked off without one.
      if (!t.done && t.needs && !t.result) {
        const value = await askText(t.needs + (t.unit ? ' (' + t.unit + ')' : ''), '',
          'A number, or roughly - e.g. touches the rim');
        if (!value) return;
        patch.result = value;
      }
      stop.classList.toggle('done', !t.done);
      dot.textContent = t.done ? '' : '✓';
      const res = await jsonSend('/api/journey/tasks/' + t.id, patch, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderJourney();
      if (res.step === 'done') journeyStepFinished(s);
      else if (res.step === 'reopened') toast('“' + s.title + '” is open again');
      else if (patch.result && !res.error) offerRouteUpdate(s, t, patch.result);
    };

    const body = tEl('div', 'jroute-body');
    const top = tEl('div', 'jroute-top');
    top.appendChild(tEl('span', 'jroute-title', t.title));
    if (isNext) top.appendChild(tEl('span', 'jroute-tag', 'Next'));
    body.appendChild(top);
    // Only the next stop spells itself out; the rest are a title and a date.
    const due = t.due ? tEl('span', 'jroute-due', (isOverdue ? 'Was due ' : 'By ') + shortDay(t.due)) : null;
    if (isNext && t.detail) body.appendChild(tEl('div', 'jroute-detail', t.detail));
    if (due && isNext) body.appendChild(due);
    else if (due) { due.classList.add('inline'); top.appendChild(due); }
    if (t.needs) {
      // "touches the rim" isn't in inches; only a number gets the unit.
      const unit = t.unit && /^[\d.,\s]+$/.test(t.result) ? ' ' + t.unit : '';
      body.appendChild(tEl('span', 'jroute-result' + (t.result ? ' has' : ''),
        t.result ? t.needs + ': ' + t.result + unit : 'Record ' + t.needs.toLowerCase() + (t.unit ? ' (' + t.unit + ')' : '')));
    }
    makeClickable(body, () => journeyTaskSheet(t));
    if (isNext) {
      const walk = tEl('button', 'jroute-walk', 'Walk me through it');
      walk.type = 'button';
      walk.onclick = e => { e.stopPropagation(); walkThrough(s, t); };
      walk.onkeydown = e => e.stopPropagation();   // Enter here is this button's, not the row's
      body.appendChild(walk);
    }

    const move = by => {
      const ids = tasks.map(x => x.id);
      ids.splice(index, 1);
      ids.splice(index + by, 0, t.id);
      journeySaveOrder(s, ids);
    };
    const menu = () => [
      {label: 'Walk me through it', run: () => walkThrough(s, t)},
      {label: 'Edit…', run: () => journeyTaskSheet(t)},
      {label: t.done ? 'Mark not done' : 'Mark done', run: () => dot.click()},
      ...(index > 0 ? [{label: 'Move up', run: () => move(-1)}] : []),
      ...(index < tasks.length - 1 ? [{label: 'Move down', run: () => move(1)}] : []),
      {divider: true},
      {label: 'Delete', danger: true, run: () => softDelete({key: 'task:' + t.id, label: 'Sub-step',
        remove: () => api('/api/journey/tasks/' + t.id, {method: 'DELETE'}), rerender: journeyRerender})},
    ];
    const more = tEl('button', 'jhead-more jroute-more', '⋯');
    more.type = 'button';
    more.dataset.focus = 'task-more:' + t.id;
    more.setAttribute('aria-label', 'Options for ' + t.title);
    more.onclick = () => showMenuFrom(more, menu());
    stop.append(dot, body, more);
    onRightClick(stop, e => showMenu(e, menu()));
    journeyRouteDrag(stop, s, t, tasks);
    return stop;
  }

  // Drag a stop up or down the route; a line shows where it lands.
  function journeyRouteDrag(stop, s, t, tasks) {
    stop.draggable = true;
    stop.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', t.id);
      e.dataTransfer.effectAllowed = 'move';
      stop.classList.add('dragging');
    });
    stop.addEventListener('dragend', () => stop.classList.remove('dragging'));
    const side = e => {
      const r = stop.getBoundingClientRect();
      return e.clientY < r.top + r.height / 2 ? 'before' : 'after';
    };
    stop.addEventListener('dragover', e => {
      e.preventDefault();
      stop.classList.toggle('drop-before', side(e) === 'before');
      stop.classList.toggle('drop-after', side(e) === 'after');
    });
    stop.addEventListener('dragleave', () => stop.classList.remove('drop-before', 'drop-after'));
    stop.addEventListener('drop', async e => {
      e.preventDefault();
      stop.classList.remove('drop-before', 'drop-after');
      const moved = e.dataTransfer.getData('text/plain');
      if (!moved || moved === t.id) return;
      const ids = tasks.map(x => x.id).filter(id => id !== moved);
      ids.splice(ids.indexOf(t.id) + (side(e) === 'after' ? 1 : 0), 0, moved);
      await journeySaveOrder(s, ids);
    });
  }

  function journeyRouteEmpty(s) {
    const li = tEl('li', 'jroute-empty');
    li.appendChild(tEl('div', 'jroute-empty-title', 'Not sure where to begin?'));
    li.appendChild(tEl('div', 'jroute-empty-sub',
      'The assistant asks a few quick questions about where you are now, then lays out the route one small step at a time.'));
    const row = tEl('div', 'jroute-empty-actions');
    const guide = tEl('button', 'btn-tinted', 'Start with a guide');
    guide.type = 'button';
    guide.onclick = () => startGuide(s);
    const plan = tEl('button', 'jroute-empty-skip', 'Just plan it');
    plan.type = 'button';
    plan.onclick = () => askJourneyAssistant(planPrompt(s), {fresh: true, title: 'Plan: ' + s.title, hint: ASK_FIRST});
    row.append(guide, plan);
    li.appendChild(row);
    return li;
  }

  function journeyRouteAdd(s) {
    const li = tEl('li', 'jroute-stop jroute-add');
    li.appendChild(tEl('span', 'jroute-dot', '+'));
    const form = tEl('form', 'jroute-add-form');
    const input = tEl('input', 'jroute-add-input');
    input.placeholder = 'Add a sub-step… e.g. measure my jump by Friday';
    input.setAttribute('aria-label', 'Add a sub-step');
    const clearDraft = keepDraft(input, s.id + ':task');
    form.appendChild(input);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!input.value.trim()) return;
      const res = await journeyFillAdd(input, '/api/journey/steps/' + s.id + '/tasks', {title: input.value, fill: true});
      if (!res) return;
      clearDraft();
      await renderJourney();
    };
    li.appendChild(form);
    return li;
  }

  // The end of the route: the step itself.
  function journeyRouteGoal(s, tasks) {
    const li = tEl('li', 'jroute-stop jroute-goal' + (s.status === 'done' ? ' done' : ''));
    li.appendChild(tEl('span', 'jroute-dot', s.status === 'done' ? '✓' : '⚑'));
    const body = tEl('div', 'jroute-body');
    body.appendChild(tEl('div', 'jroute-title', s.title));
    const allDone = tasks.length && tasks.every(t => t.done);
    if (s.status === 'done') {
      body.appendChild(tEl('div', 'jroute-detail', 'Step done'));
    } else if (allDone) {
      const finish = tEl('button', 'btn-primary jroute-finish', 'Mark the step done');
      finish.type = 'button';
      finish.onclick = async () => {
        const res = await jsonSend('/api/roadmap-node/' + s.id, {status: 'done'}, 'PATCH');
        if (res.error) toast(res.error, {error: true});
        await renderJourney([s.id]);
      };
      body.appendChild(finish);
    } else {
      body.appendChild(tEl('div', 'jroute-detail', 'Where this route ends'));
    }
    li.appendChild(body);
    return li;
  }

  async function journeyTaskSheet(t) {
    const body = tEl('div', 'jsheet');
    const title = tEl('input', 'job-field-input');
    title.value = t.title;
    body.appendChild(inspectorField('Sub-step', title));
    const detail = tEl('textarea', 'modal-textarea');
    detail.value = t.detail;
    detail.placeholder = 'How to do it';
    body.appendChild(inspectorField('Details', detail));
    const due = tEl('input', 'job-field-input');
    due.type = 'date';
    due.value = t.due;
    body.appendChild(inspectorField('Do by', due));
    const needs = tEl('input', 'job-field-input');
    needs.value = t.needs || '';
    needs.placeholder = 'Nothing - or e.g. Vertical jump';
    body.appendChild(inspectorField('Asks you to record', needs));
    const unit = tEl('input', 'job-field-input');
    unit.value = t.unit || '';
    unit.placeholder = 'e.g. in, min, kg';
    body.appendChild(inspectorField('Unit', unit));
    const result = tEl('input', 'job-field-input');
    result.value = t.result || '';
    result.placeholder = 'What you got';
    body.appendChild(inspectorField('Result', result));
    const del = tEl('button', 'btn-tinted btn-danger-tinted', 'Delete sub-step');
    del.type = 'button';
    let deleted = false;
    del.onclick = () => { deleted = true; del.closest('.modal').querySelector('.modal-actions .btn-primary').click(); };
    body.appendChild(del);
    if (!(await modal({title: 'Sub-step', body, confirmLabel: 'Save', multiline: true}))) return;
    if (deleted) {
      softDelete({key: 'task:' + t.id, label: 'Sub-step',
        remove: () => api('/api/journey/tasks/' + t.id, {method: 'DELETE'}), rerender: journeyRerender});
      return;
    }
    const res = await jsonSend('/api/journey/tasks/' + t.id,
      {title: title.value, detail: detail.value, due: due.value, needs: needs.value, unit: unit.value,
       result: result.value}, 'PATCH');
    if (res.error) toast(res.error, {error: true});
    await renderJourney();
    const step = journeyFindStep(t.node_id);
    if (!res.error && step && result.value.trim() && result.value.trim() !== (t.result || '')) {
      offerRouteUpdate(step, {...t, needs: needs.value || t.needs, unit: unit.value}, result.value.trim());
    }
  }

  // After a result is recorded, offer to rebuild the rest of the route from it.
  function offerRouteUpdate(s, t, value) {
    const what = (t.needs || 'Result') + ': ' + value + (t.unit && /^[\d.,\s]+$/.test(value) ? ' ' + t.unit : '');
    toast('Recorded ' + what, {action: {label: 'Update the route', run: () => askJourneyAssistant(
      'I recorded ' + what + ' for "' + t.title + '". Update the rest of the route for "' + s.title
      + '" based on that: keep what I\'ve done, adjust what\'s left.', {fresh: true, title: 'Update: ' + s.title})}});
  }
