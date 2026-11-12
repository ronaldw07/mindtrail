  // ---------- journey: the path map ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // For journeys that don't run on school terms. Each path is a colored
  // line of its steps in order, first to last, ending at what the path is
  // aiming for. Click a stop to open its page, tick its circle when it's
  // done, drag it along its line (or onto another line) to reorder.

  const journeyIsMap = () => journeyData && journeyData.layout === 'map';
  const journeyInOrder = steps => [...steps].sort((a, b) =>
    a.position - b.position || (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
  let journeyMapDragging = null;   // {step, track} while a stop is being dragged

  function journeyMap() {
    const map = tEl('div', 'jmap');
    const hidden = journeyHidden();
    // "Every path" only gets a line of its own once it has steps.
    const lines = journeyData.tracks.filter(t => t.shared ? t.steps.length : !hidden.includes(t.id));
    lines.forEach(t => map.appendChild(journeyMapLine(t)));
    return map;
  }

  function journeyMapLine(t) {
    const line = tEl('section', 'jmap-line');
    line.style.setProperty('--c', journeyTrackColor(t));
    const steps = journeyInOrder(t.steps);
    const done = steps.filter(s => s.status === 'done').length;

    const head = tEl('div', 'jmap-head');
    head.appendChild(tEl('span', 'jmap-swatch'));
    head.appendChild(tEl('span', 'jmap-name', t.shared ? 'Every path' : t.name));
    if (steps.length) head.appendChild(tEl('span', 'jmap-count', done + ' of ' + steps.length + ' done'));
    if (!t.shared) {
      const more = tEl('button', 'jhead-more jmap-line-more', '⋯');
      more.type = 'button';
      more.setAttribute('aria-label', t.name + ' options');
      more.onclick = () => showMenuFrom(more, journeyTrackMenu(t.id));
      head.appendChild(more);
      onRightClick(head, e => showMenu(e, journeyTrackMenu(t.id)));
    }
    line.appendChild(head);

    const stops = tEl('ol', 'jmap-stops');
    // Where you are on this line: the first stop not done (or skipped) yet.
    const here = steps.find(s => s.status !== 'done' && s.status !== 'rejected');
    steps.forEach((s, i) => stops.appendChild(journeyMapStop(t, s, steps, i, s === here)));
    stops.appendChild(journeyMapAdd(t));
    if (!t.shared) stops.appendChild(journeyMapEnd(t, steps));
    journeyMapDropZone(stops, t, steps);
    line.appendChild(stops);
    return line;
  }

  function journeyMapStop(t, s, steps, index, isHere) {
    const full = {...s, track: t.name, shared: t.shared, color: journeyTrackColor(t)};
    const stop = tEl('li', 'jmap-stop ' + s.status + (isHere ? ' here' : '') +
      (journeyChanged.has(s.id) ? ' just-changed' : ''));
    stop.dataset.key = 'step:' + s.id;
    stop.dataset.id = s.id;

    const next = JOURNEY_CYCLE[s.status] || 'accepted';
    const dot = tEl('button', 'jmap-dot', s.status === 'done' ? '✓' : '');
    dot.type = 'button';
    dot.dataset.focus = 'mapdot:' + s.id;
    dot.setAttribute('aria-label', s.title + ': ' + JOURNEY_STATUS_WORD[s.status] + '. Mark ' +
      JOURNEY_STATUS_WORD[next]);
    dot.title = JOURNEY_STATUS_WORD[s.status] + ' · click for ' + JOURNEY_STATUS_WORD[next];
    dot.onclick = async () => {
      stop.classList.replace(s.status, next);
      dot.textContent = next === 'done' ? '✓' : '';
      const res = await jsonSend('/api/roadmap-node/' + s.id, {status: next}, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderJourney(res.error ? [] : [s.id]);
    };

    const body = tEl('div', 'jmap-body');
    const title = tEl('div', 'jmap-title', s.title);
    if (isHere) title.prepend(tEl('span', 'jmap-here', 'Next'));
    body.appendChild(title);
    const meta = [];
    if (s.due_date) meta.push('By ' + shortDay(s.due_date));
    const [doneSubs, totalSubs] = s.progress || [0, 0];
    if (totalSubs) meta.push(doneSubs + '/' + totalSubs + ' sub-steps');
    if (meta.length) body.appendChild(tEl('div', 'jmap-meta', meta.join(' · ')));
    makeClickable(body, () => openJourneyStep(s.id));
    body.title = s.detail || 'Open';

    const move = by => journeyMapSaveOrder(s, t, (() => {
      const ids = steps.map(x => x.id).filter(id => id !== s.id);
      ids.splice(index + by, 0, s.id);
      return ids;
    })());
    const menu = () => {
      const base = journeyStepMenu(full);
      const moves = [...(index > 0 ? [{label: 'Move earlier', run: () => move(-1)}] : []),
                     ...(index < steps.length - 1 ? [{label: 'Move later', run: () => move(1)}] : [])];
      return [...base.slice(0, 3), ...moves, ...base.slice(3)];
    };
    const more = tEl('button', 'jhead-more jmap-more', '⋯');
    more.type = 'button';
    more.dataset.focus = 'mapmore:' + s.id;
    more.setAttribute('aria-label', 'Options for ' + s.title);
    more.onclick = () => showMenuFrom(more, menu());
    onRightClick(stop, e => showMenu(e, menu()));

    stop.draggable = true;
    stop.addEventListener('dragstart', e => {
      journeyMapDragging = {step: s, track: t};
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', s.id);
      stop.classList.add('dragging');
    });
    stop.addEventListener('dragend', () => {
      journeyMapDragging = null;
      stop.classList.remove('dragging');
      document.querySelectorAll('.jmap .drop-before').forEach(n => n.classList.remove('drop-before'));
    });

    stop.append(dot, more, body);
    return stop;
  }

  // Where a dragged stop would land: before the first stop whose middle is
  // past the pointer (on the same row), else at the end of the line.
  function journeyMapDropTarget(stops, x, y) {
    const items = [...stops.querySelectorAll('.jmap-stop:not(.dragging)')];
    return items.find(n => {
      const r = n.getBoundingClientRect();
      return y < r.bottom && (y < r.top || x < r.left + r.width / 2);
    }) || stops.querySelector('.jmap-add');
  }

  function journeyMapDropZone(stops, t, steps) {
    stops.addEventListener('dragover', e => {
      if (!journeyMapDragging) return;
      e.preventDefault();
      const target = journeyMapDropTarget(stops, e.clientX, e.clientY);
      document.querySelectorAll('.jmap .drop-before').forEach(n => { if (n !== target) n.classList.remove('drop-before'); });
      if (target) target.classList.add('drop-before');
    });
    stops.addEventListener('dragleave', e => {
      if (!stops.contains(e.relatedTarget)) stops.querySelectorAll('.drop-before').forEach(n => n.classList.remove('drop-before'));
    });
    stops.addEventListener('drop', e => {
      if (!journeyMapDragging) return;
      e.preventDefault();
      const {step} = journeyMapDragging;
      const target = journeyMapDropTarget(stops, e.clientX, e.clientY);
      const ids = steps.map(x => x.id).filter(id => id !== step.id);
      const at = target && target.dataset.id ? ids.indexOf(target.dataset.id) : ids.length;
      ids.splice(at, 0, step.id);
      journeyMapSaveOrder(step, t, ids);
    });
  }

  async function journeyMapSaveOrder(s, t, ids) {
    const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: s.term, track_id: t.id, order: ids});
    if (res.error) toast(res.error, {error: true});
    await renderJourney([s.id]);
  }

  function journeyMapAdd(t) {
    const li = tEl('li', 'jmap-add');
    const add = tEl('button', 'jmap-add-btn', '+');
    add.type = 'button';
    add.dataset.focus = 'mapadd:' + t.id;
    add.setAttribute('aria-label', 'Add a step to ' + (t.shared ? 'every path' : t.name));
    add.title = 'Add a step';
    add.onclick = async () => {
      const title = await askText('Add to ' + (t.shared ? 'every path' : t.name), '', 'e.g. Buy running shoes');
      if (!title) return;
      const res = await jsonSend('/api/journey/steps', {track_id: t.id, title});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderJourney([res.step.id]);
    };
    li.appendChild(add);
    return li;
  }

  // The end of the line: what the path is aiming for. Click to change it.
  function journeyMapEnd(t, steps) {
    const reached = steps.length && steps.every(s => s.status === 'done' || s.status === 'rejected');
    const li = tEl('li', 'jmap-end' + (reached ? ' reached' : ''));
    li.appendChild(tEl('span', 'jmap-flag', reached ? '✓' : '⚑'));
    const goal = tEl('div', 'jmap-goal', t.goal || 'Set a goal');
    goal.title = 'Change what this path is aiming for';
    makeClickable(goal, async () => {
      const value = await askText('What is ' + t.name + ' aiming for?', t.goal);
      if (!value || value === t.goal) return;
      const res = await jsonSend('/api/journey/tracks/' + t.id, {goal: value}, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderJourney();
    });
    li.appendChild(goal);
    return li;
  }
