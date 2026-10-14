
  // ---------- journey: the 4-year timeline ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // One project holds several career tracks; each track's steps sit in school
  // terms. This file is the timeline itself; the side panel (next up,
  // suggestions, chat) is in journey_panel.js.

  const JOURNEY_COLORS = ['#3987e5', '#d95926', '#199e70', '#9a5bd3', '#c98a14', '#d1478f'];
  const JOURNEY_SHARED_COLOR = '#8e8e93';
  const JOURNEY_STATUSES = [['accepted', 'Planned'], ['proposed', 'Suggested'], ['done', 'Done'], ['rejected', 'Skipped']];

  let journeyData = null;
  let journeyChanged = new Set();     // step ids that just changed, to light up
  const journeyOpenNotes = new Set(); // terms whose "what I did" box is open
  const journeyOpenReviews = new Set();

  const journeyTab = () => prefs.get('journeyTab', 'all');

  function journeyTrackColor(track) {
    if (track.shared) return JOURNEY_SHARED_COLOR;
    const own = journeyData.tracks.filter(t => !t.shared);
    return JOURNEY_COLORS[own.findIndex(t => t.id === track.id) % JOURNEY_COLORS.length];
  }

  // Every step visible on the current tab, tagged with its track.
  function journeyVisibleSteps() {
    const tab = journeyTab();
    const out = [];
    journeyData.tracks.forEach(t => {
      if (tab !== 'all' && !t.shared && t.id !== tab) return;
      t.steps.forEach(s => out.push({...s, track: t.name, shared: t.shared, color: journeyTrackColor(t)}));
    });
    return out;
  }

  async function openJourneyView() {
    currentProject = null;
    current = null;
    setActiveView('journey');
    prefs.set('lastView', {type: 'journey'});
    $('breadcrumb').textContent = 'Journey';
    await renderJourney();
  }

  async function renderJourney(changed) {
    journeyData = await api('/api/journey');
    journeyChanged = new Set(changed || []);
    const view = $('journey-view');
    if (!journeyData.setup) { commitView(view, journeySetup(journeyData)); return; }
    if (journeyTab() !== 'all' && !journeyData.tracks.some(t => t.id === journeyTab())) prefs.set('journeyTab', 'all');

    const layout = tEl('div', 'journey-layout');
    const main = tEl('div', 'journey-main');
    main.appendChild(journeyHead());
    main.appendChild(journeyTabs());
    const steps = journeyVisibleSteps();
    journeyData.years.forEach(y => main.appendChild(journeyYear(y, steps)));
    const loose = steps.filter(s => !s.term);
    if (loose.length) main.appendChild(journeyLoose(loose));
    layout.appendChild(main);
    layout.appendChild(journeyRail());
    commitView(view, layout);
    const first = layout.querySelector('.jchip.just-changed');
    if (first) first.scrollIntoView({block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth'});
  }

  // ---------- first run ----------

  function journeySetup(data) {
    const box = tEl('div', 'journey-setup');
    box.appendChild(tEl('div', 'proj-title', 'Plan your four years'));
    box.appendChild(tEl('p', 'journey-lede',
      'A timeline of school terms with a track for each direction you’re considering. ' +
      'You can add, rename and copy tracks any time, and ask the assistant to reshape them.'));

    const year = tEl('select', 'job-field-input');
    year.setAttribute('aria-label', 'First year of school');
    for (let y = data.start_year - 3; y <= data.start_year + 1; y++) {
      const o = tEl('option', '', 'Fall ' + y + ' – Spring ' + (y + 4));
      o.value = y;
      year.appendChild(o);
    }
    // Most people open this after their first year, so default to last fall.
    year.value = data.start_year - 1;
    box.appendChild(inspectorField('When did you start?', year));

    const picks = tEl('div', 'journey-picks');
    data.candidates.forEach(c => {
      const row = tEl('label', 'journey-pick');
      const cb = tEl('input');
      cb.type = 'checkbox';
      cb.value = c.roadmap_id;
      cb.checked = /career/i.test(c.project) && c.steps > 0;
      row.appendChild(cb);
      const text = tEl('span', '');
      text.appendChild(tEl('b', '', c.project));
      text.appendChild(document.createTextNode(' — ' + (c.goal || 'roadmap') + ' · ' + c.steps + ' steps'));
      row.appendChild(text);
      picks.appendChild(row);
    });
    if (data.candidates.length) {
      const f = inspectorField('Bring in an existing roadmap as its own track (the original stays as it is)', picks);
      box.appendChild(f);
    }

    const go = tEl('button', 'btn-primary', 'Create my journey');
    go.onclick = async () => {
      setButtonBusy(go, 'Creating…');
      const res = await jsonSend('/api/journey/setup', {
        start_year: Number(year.value),
        copy_roadmap_ids: Array.from(picks.querySelectorAll('input:checked')).map(i => i.value),
      });
      if (res.error) { setButtonIdle(go, 'Create my journey'); toast(res.error, {error: true}); return; }
      await renderJourney();
    };
    box.appendChild(go);
    return box;
  }

  // ---------- header and tabs ----------

  function journeyHead() {
    const head = tEl('div', 'jhead');
    const title = tEl('div', '');
    title.appendChild(tEl('div', 'proj-title', 'Journey'));
    title.appendChild(tEl('div', 'jhead-sub',
      journeyData.current_label + ' · Year ' + journeyData.current_year + ' of 4'));
    head.appendChild(title);
    return head;
  }

  function journeyTabs() {
    const bar = tEl('div', 'jtabs');
    bar.setAttribute('role', 'tablist');
    const tab = journeyTab();
    const add = (id, label, color) => {
      const b = tEl('button', 'jtab' + (tab === id ? ' active' : ''));
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', tab === id ? 'true' : 'false');
      if (color) {
        const dot = tEl('span', 'jdot');
        dot.style.background = color;
        b.appendChild(dot);
      }
      b.appendChild(document.createTextNode(label));
      b.onclick = () => {
        if (tab === id && id !== 'all') { showMenuFrom(b, journeyTrackMenu(id)); return; }
        prefs.set('journeyTab', id);
        renderJourney();
      };
      bar.appendChild(b);
    };
    add('all', 'All tracks');
    journeyData.tracks.filter(t => !t.shared).forEach(t => add(t.id, t.name, journeyTrackColor(t)));
    const plus = tEl('button', 'jtab jtab-add', '+');
    plus.type = 'button';
    plus.setAttribute('aria-label', 'New track');
    plus.onclick = async () => {
      const name = await askText('New track', '', 'e.g. Research, Startup, Grad school');
      if (!name) return;
      const res = await jsonSend('/api/journey/tracks', {name});
      if (res.error) { toast(res.error, {error: true}); return; }
      prefs.set('journeyTab', res.track_id);
      await renderJourney();
    };
    bar.appendChild(plus);
    return bar;
  }

  function journeyTrackMenu(id) {
    const track = journeyData.tracks.find(t => t.id === id);
    return [
      {label: 'Rename…', run: async () => {
        const name = await askText('Rename track', track.name);
        if (!name) return;
        const res = await jsonSend('/api/journey/tracks/' + id, {name}, 'PATCH');
        if (res.error) toast(res.error, {error: true}); else await renderJourney();
      }},
      {label: 'Edit goal…', run: async () => {
        const goal = await askText('What is this track aiming at?', track.goal);
        if (!goal) return;
        const res = await jsonSend('/api/journey/tracks/' + id, {goal}, 'PATCH');
        if (res.error) toast(res.error, {error: true}); else await renderJourney();
      }},
      {label: 'Duplicate', run: async () => {
        const res = await jsonSend('/api/journey/tracks/' + id + '/duplicate', {});
        if (res.error) { toast(res.error, {error: true}); return; }
        prefs.set('journeyTab', res.track_id);
        await renderJourney();
      }},
      {label: 'Delete track…', run: async () => {
        if (!await askConfirm('Delete ' + track.name + '?',
            'Its ' + track.steps.length + ' steps go with it.', 'Delete')) return;
        const res = await api('/api/journey/tracks/' + id, {method: 'DELETE'});
        if (res.error) { toast(res.error, {error: true}); return; }
        prefs.set('journeyTab', 'all');
        await renderJourney();
      }},
    ];
  }

  // ---------- years and terms ----------

  function journeyYear(year, steps) {
    const sec = tEl('section', 'jyear');
    const now = journeyData.current_year;
    const head = tEl('div', 'jyear-head');
    head.appendChild(tEl('div', 'jyear-title', year.label));
    head.appendChild(tEl('div', 'jyear-span', year.span));
    if (year.number === now) head.appendChild(tEl('span', 'jpill now', 'Now'));
    else if (year.number < now) head.appendChild(tEl('span', 'jpill', 'Done'));
    if (year.number <= now) head.appendChild(journeyReviewButtons(year.number));
    sec.appendChild(head);
    if (journeyOpenReviews.has(year.number) && journeyData.reviews[year.number]) {
      sec.appendChild(journeyReviewCard(journeyData.reviews[year.number]));
    }
    const grid = tEl('div', 'jterms');
    year.terms.forEach(t => grid.appendChild(journeyTerm(t, steps.filter(s => s.term === t.term))));
    sec.appendChild(grid);
    return sec;
  }

  function journeyReviewButtons(number) {
    const wrap = tEl('div', 'jyear-actions');
    const saved = journeyData.reviews[number];
    if (saved) {
      const read = tEl('button', 'btn-plain', journeyOpenReviews.has(number) ? 'Hide review' : 'Read review');
      read.onclick = () => {
        if (journeyOpenReviews.has(number)) journeyOpenReviews.delete(number); else journeyOpenReviews.add(number);
        renderJourney();
      };
      wrap.appendChild(read);
    }
    const run = tEl('button', 'btn-tinted', saved ? 'Review again' : 'Review Year ' + number);
    run.title = 'Reads what you wrote in this year’s terms and sends it to the AI model';
    run.onclick = async () => {
      setButtonBusy(run, 'Reviewing…');
      const res = await jsonSend('/api/journey/review', {year: number});
      if (res.error) { setButtonIdle(run, saved ? 'Review again' : 'Review Year ' + number); toast(res.error, {error: true}); return; }
      journeyOpenReviews.add(number);
      prefs.set('journeyRail', 'suggestions');
      toast('Review saved. ' + res.suggestions.length + ' suggestions are waiting.');
      await renderJourney();
    };
    wrap.appendChild(run);
    return wrap;
  }

  function journeyReviewCard(review) {
    const b = review.body;
    const card = tEl('div', 'jreview');
    card.appendChild(tEl('p', 'jreview-summary', b.summary));
    const list = (label, items) => {
      if (!items || !items.length) return;
      card.appendChild(tEl('div', 'jreview-label', label));
      const ul = tEl('ul', 'jreview-list');
      items.forEach(i => ul.appendChild(tEl('li', '', i)));
      card.appendChild(ul);
    };
    list('Went well', b.went_well);
    list('Gaps', b.gaps);
    if (b.tracks && b.tracks.length) {
      card.appendChild(tEl('div', 'jreview-label', 'By track'));
      b.tracks.forEach(t => {
        const row = tEl('p', 'jreview-track');
        row.appendChild(tEl('b', '', t.track + ': '));
        row.appendChild(document.createTextNode(t.verdict));
        card.appendChild(row);
      });
    }
    card.appendChild(tEl('div', 'jreview-foot', 'Reviewed ' + new Date(review.created_at).toLocaleDateString()));
    return card;
  }

  function journeyTerm(t, steps) {
    const cell = tEl('div', 'jterm' + (t.past ? ' past' : '') + (t.current ? ' current' : ''));
    cell.dataset.term = t.term;
    const head = tEl('div', 'jterm-head');
    head.appendChild(tEl('span', 'jterm-name', t.label));
    if (t.current) head.appendChild(tEl('span', 'jpill now', 'Now'));
    const tools = tEl('span', 'jterm-tools');
    if (t.past || t.current) {
      const text = journeyData.reflections[t.term] || '';
      const note = tEl('button', 'jtool' + (text ? ' has-text' : ''), '✎');
      note.title = t.past ? 'What I actually did' : 'Notes on this term';
      note.setAttribute('aria-label', note.title);
      note.onclick = () => {
        if (journeyOpenNotes.has(t.term)) journeyOpenNotes.delete(t.term); else journeyOpenNotes.add(t.term);
        renderJourney();
      };
      tools.appendChild(note);
    }
    const plus = tEl('button', 'jtool', '+');
    plus.title = 'Add a step';
    plus.setAttribute('aria-label', 'Add a step in ' + t.label);
    plus.onclick = () => journeyAddStep(t.term);
    tools.appendChild(plus);
    head.appendChild(tools);
    cell.appendChild(head);

    if (journeyOpenNotes.has(t.term)) cell.appendChild(journeyReflectionBox(t));
    else if (journeyData.reflections[t.term]) {
      cell.appendChild(tEl('div', 'jterm-note', journeyData.reflections[t.term]));
    }
    steps.forEach(s => cell.appendChild(journeyChip(s)));
    if (!steps.length && !journeyOpenNotes.has(t.term) && !journeyData.reflections[t.term]) {
      cell.appendChild(tEl('div', 'jterm-empty', t.past ? 'Nothing recorded' : '—'));
    }
    return cell;
  }

  function journeyReflectionBox(t) {
    const box = tEl('textarea', 'jreflect');
    box.placeholder = t.past
      ? 'What did you actually do? Classes, projects, clubs, jobs, what went badly.'
      : 'Notes on this term';
    box.value = journeyData.reflections[t.term] || '';
    box.setAttribute('aria-label', 'What I did in ' + t.label);
    let saved = box.value;
    box.onblur = async () => {
      if (box.value === saved) return;
      saved = box.value;
      const res = await jsonSend('/api/journey/reflection', {term: t.term, text: box.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      journeyData.reflections[t.term] = box.value;
    };
    return box;
  }

  function journeyLoose(steps) {
    const sec = tEl('section', 'jyear');
    sec.appendChild(tEl('div', 'jyear-head', 'No term yet'));
    const cell = tEl('div', 'jterm loose');
    cell.dataset.term = '';
    steps.forEach(s => cell.appendChild(journeyChip(s)));
    sec.appendChild(cell);
    return sec;
  }

  // ---------- step chips ----------

  function journeyChip(s) {
    const chip = tEl('button', 'jchip ' + s.status + (journeyChanged.has(s.id) ? ' just-changed' : ''));
    chip.type = 'button';
    chip.dataset.key = 'step:' + s.id;
    chip.style.setProperty('--c', s.color);
    chip.title = s.track + (s.detail ? ' — ' + s.detail : '');
    const mark = tEl('span', 'jmark', s.status === 'done' ? '✓' : '');
    chip.appendChild(mark);
    chip.appendChild(tEl('span', 'jchip-title', s.title));
    if (s.shared && journeyTab() === 'all') chip.appendChild(tEl('span', 'jchip-tag', 'all'));
    chip.onclick = () => { if (chip._wasDragged) { chip._wasDragged = false; return; } journeyStepSheet(s); };
    journeyEnableDrag(chip, s);
    return chip;
  }

  function journeyEnableDrag(chip, s) {
    chip.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.pointerType === 'touch') return;
      const sx = e.clientX, sy = e.clientY;
      let ghost = null, over = null;
      const cellAt = ev => document.elementsFromPoint(ev.clientX, ev.clientY)
        .find(n => n.classList && n.classList.contains('jterm')) || null;
      const move = ev => {
        if (!ghost) {
          if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 5) return;
          const r = chip.getBoundingClientRect();
          ghost = chip.cloneNode(true);
          ghost.classList.add('jchip-ghost');
          ghost.style.cssText = 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;';
          document.body.appendChild(ghost);
          chip.classList.add('drag-source');
        }
        ghost.style.transform = 'translate(' + (ev.clientX - sx) + 'px,' + (ev.clientY - sy) + 'px) scale(1.04)';
        const cell = cellAt(ev);
        if (cell !== over) {
          if (over) over.classList.remove('drop-target');
          over = cell;
          if (over) over.classList.add('drop-target');
        }
      };
      const end = async ev => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', end);
        document.removeEventListener('pointercancel', end);
        if (!ghost) return;
        chip._wasDragged = true;
        setTimeout(() => { chip._wasDragged = false; }, 0);
        ghost.remove();
        chip.classList.remove('drag-source');
        if (over) over.classList.remove('drop-target');
        if (!over || ev.type === 'pointercancel' || over.dataset.term === s.term) return;
        const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: over.dataset.term});
        if (res.error) { toast(res.error, {error: true}); return; }
        await renderJourney([s.id]);
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', end);
      document.addEventListener('pointercancel', end);
    });
  }

  async function journeyAddStep(term) {
    const tab = journeyTab();
    const track = journeyData.tracks.find(t => t.id === tab) || journeyData.tracks.find(t => t.shared);
    const title = await askText('Add to ' + (tab === 'all' ? 'every track' : track.name), '',
      'e.g. Take CS 161, Apply to summer internships');
    if (!title) return;
    const res = await jsonSend('/api/journey/steps', {track_id: track.id, title, term});
    if (res.error) { toast(res.error, {error: true}); return; }
    await renderJourney([res.step.id]);
  }

  // The full editor for one step, in a sheet.
  async function journeyStepSheet(s) {
    const body = tEl('div', 'jsheet');
    const field = (label, el) => body.appendChild(inspectorField(label, el));

    const title = tEl('input', 'job-field-input');
    title.value = s.title;
    field('Title', title);

    const detail = tEl('textarea', 'modal-textarea');
    detail.value = s.detail;
    detail.placeholder = 'What this involves';
    field('Details', detail);

    const status = tEl('select', 'job-field-input');
    JOURNEY_STATUSES.forEach(([v, l]) => { const o = tEl('option', '', l); o.value = v; status.appendChild(o); });
    status.value = s.status;
    field('Status', status);

    const term = tEl('select', 'job-field-input');
    const none = tEl('option', '', 'No term yet');
    none.value = '';
    term.appendChild(none);
    journeyData.years.forEach(y => y.terms.forEach(t => {
      const o = tEl('option', '', y.label + ' · ' + t.label);
      o.value = t.term;
      term.appendChild(o);
    }));
    term.value = s.term;
    field('Term', term);

    const track = tEl('select', 'job-field-input');
    journeyData.tracks.forEach(t => {
      const o = tEl('option', '', t.shared ? 'Every track' : t.name);
      o.value = t.id;
      track.appendChild(o);
    });
    track.value = s.track_id;
    field('Track', track);

    const note = tEl('textarea', 'modal-textarea');
    note.value = s.note;
    note.placeholder = 'Your own notes';
    field('Notes', note);

    const del = tEl('button', 'btn-tinted btn-danger-tinted', 'Delete step');
    body.appendChild(del);
    let deleted = false;
    del.onclick = () => { deleted = true; del.closest('.modal').querySelector('.modal-actions .btn-primary').click(); };

    const ok = await modal({title: 'Step', body, confirmLabel: 'Save', multiline: true});
    if (!ok) return;
    if (deleted) {
      await renderJourney();
      softDelete({key: 'step:' + s.id, label: 'Step',
        remove: () => api('/api/roadmap-node/' + s.id, {method: 'DELETE'}), rerender: renderJourney});
      return;
    }
    const patch = {};
    if (title.value.trim() && title.value !== s.title) patch.title = title.value;
    if (detail.value !== s.detail) patch.detail = detail.value;
    if (status.value !== s.status) patch.status = status.value;
    if (note.value !== s.note) patch.note = note.value;
    let failed = '';
    if (Object.keys(patch).length) {
      // The node endpoint renames with the detail alongside, so send both.
      if (patch.title !== undefined || patch.detail !== undefined) {
        patch.title = patch.title !== undefined ? patch.title : s.title;
        patch.detail = patch.detail !== undefined ? patch.detail : detail.value;
      }
      const res = await jsonSend('/api/roadmap-node/' + s.id, patch, 'PATCH');
      if (res.error) failed = res.error;
    }
    if (!failed && (term.value !== s.term || track.value !== s.track_id)) {
      const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: term.value, track_id: track.value});
      if (res.error) failed = res.error;
    }
    if (failed) toast(failed, {error: true});
    await renderJourney([s.id]);
  }
