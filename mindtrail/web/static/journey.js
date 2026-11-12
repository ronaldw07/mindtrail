
  // ---------- journey: the 4-year timeline ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // You can have several journeys (Career, Health...), one open at a time.
  // Each holds several tracks (paths); each track's steps sit in terms. This file is the timeline itself; the side panel (next up,
  // suggestions, chat) is in journey_panel.js.

  const JOURNEY_COLORS = ['#3987e5', '#d95926', '#199e70', '#9a5bd3', '#c98a14', '#d1478f'];
  const JOURNEY_SHARED_COLOR = '#8e8e93';
  const JOURNEY_STATUSES = [['accepted', 'Planned'], ['proposed', 'Suggested'], ['done', 'Done'], ['rejected', 'Skipped']];

  let journeyData = null;
  let journeyChanged = new Set();     // step ids that just changed, to light up
  const journeyOpenNotes = new Set(); // terms whose "what I did" box is open
  const journeyOpenReviews = new Set();

  // Paths are toggled on and off per journey; what's on is drawn together.
  // journeyTab() names the single path on (new steps go there), or 'all'.
  const journeyHidden = () => (prefs.get('journeyHidden', {})[journeyData.project_id] || []);
  function setJourneyHidden(ids) {
    prefs.set('journeyHidden', {...prefs.get('journeyHidden', {}), [journeyData.project_id]: ids});
  }
  const journeyPaths = () => journeyData.tracks.filter(t => !t.shared);
  const journeyShown = () => journeyPaths().filter(t => !journeyHidden().includes(t.id));
  function journeyTab() {
    const shown = journeyShown();
    return shown.length === 1 && journeyPaths().length > 1 ? shown[0].id : 'all';
  }
  // Show just one path, e.g. one the assistant just made.
  function journeyOnly(id) { setJourneyHidden(journeyPaths().filter(t => t.id !== id).map(t => t.id)); }

  function journeyTrackColor(track) {
    if (track.shared) return JOURNEY_SHARED_COLOR;
    const own = journeyData.tracks.filter(t => !t.shared);
    return JOURNEY_COLORS[own.findIndex(t => t.id === track.id) % JOURNEY_COLORS.length];
  }

  // Every step visible on the current tab, tagged with its track.
  function journeyVisibleSteps() {
    const hidden = journeyHidden();
    const out = [];
    journeyData.tracks.forEach(t => {
      if (!t.shared && hidden.includes(t.id)) return;
      t.steps.forEach(s => out.push({...s, track: t.name, shared: t.shared, color: journeyTrackColor(t)}));
    });
    return out;
  }

  // The sidebar's Journey opens the page of journey boxes; Career's Plan
  // tab (and a box) go straight into one journey.
  async function openJourneyView(opts) {
    journeyFocus = (opts && opts.step) || null;
    currentProject = null;
    current = null;
    setActiveView('journey');
    prefs.set('lastView', {type: 'journey'});
    $('breadcrumb').textContent = 'Journey';
    if (opts && opts.detail) await renderJourney();
    else await renderJourneyHome();
  }

  // After a delete's undo runs out: redraw the Journey page that's showing
  // now, which may not be the one the delete started on.
  async function journeyRerender() {
    if (activeView !== 'journey') return;
    if (document.querySelector('#journey-view .jhome')) await renderJourneyHome();
    else await renderJourney();
  }

  async function renderJourney(changed) {
    journeyData = await api('/api/journey');
    journeyChanged = new Set(changed || []);
    const view = $('journey-view');
    if (!journeyData.setup) { hideJourneyDock(); commitView(view, journeySetup(journeyData)); return; }
    // Forget toggles for paths that no longer exist.
    const ids = journeyPaths().map(t => t.id);
    if (journeyHidden().some(id => !ids.includes(id))) setJourneyHidden(journeyHidden().filter(id => ids.includes(id)));
    const focused = journeyFocus && journeyFindStep(journeyFocus);
    if (focused) { await renderJourneyStep(view, focused); if (activeView === 'journey') showJourneyDock(); return; }
    journeyFocus = null;

    const goals = await api('/api/journey/goals');
    const layout = tEl('div', 'journey-layout');
    const main = tEl('div', 'journey-main');
    main.appendChild(journeyCrumb());
    main.appendChild(journeyHead());
    main.appendChild(journeyTabs());
    if (!goals.error) main.appendChild(journeyDailyGoals(goals));
    if (journeyIsMap()) main.appendChild(journeyMap());
    else {
      const steps = journeyVisibleSteps();
      journeyData.years.forEach(y => main.appendChild(journeyYear(y, steps)));
      const loose = steps.filter(s => !s.term);
      if (loose.length) main.appendChild(journeyLoose(loose));
    }
    layout.appendChild(main);
    layout.appendChild(journeyRail());
    commitView(view, layout);
    if (activeView === 'journey') showJourneyDock();   // not when a late undo redraws it elsewhere
    const first = layout.querySelector('.jchip.just-changed');
    if (first) first.scrollIntoView({block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth'});
  }

  // ---------- making a journey ----------

  // The first-run screen, and the "+ New journey" form once there is one.
  function journeySetup(data) {
    const first = !data.setup;
    const hasCareer = (data.journeys || []).some(j => j.kind === 'career');
    let kind = hasCareer ? 'general' : 'career';

    const box = tEl('div', 'journey-setup');
    box.appendChild(tEl('div', 'proj-title', first ? 'Start your first journey' : 'New journey'));
    box.appendChild(tEl('p', 'journey-lede',
      'A journey is a timeline of terms with a path for each direction you’re considering - ' +
      'a career, your health, anything. Add, rename and copy paths any time, and ask the ' +
      'assistant to reshape them.'));

    const kindRow = tEl('div', '');
    const name = tEl('input', 'job-field-input');
    name.setAttribute('aria-label', 'Journey name');
    const purpose = tEl('textarea', 'job-field-input journey-purpose');
    purpose.rows = 2;
    purpose.setAttribute('aria-label', 'What this journey is for');
    const syncKind = () => {
      name.placeholder = kind === 'career' ? 'Career' : 'e.g. Health, Music, Grad school';
      purpose.placeholder = kind === 'career'
        ? 'e.g. Land an AI/ML internship by summer 2027, without burning out'
        : 'e.g. Run a half marathon and sleep 8 hours most nights';
      picksField.hidden = kind !== 'career' || !data.candidates.length;
    };
    kindRow.appendChild(segmented([{value: 'career', label: 'Career (CS)'}, {value: 'general', label: 'Anything else'}],
      kind, v => { kind = v; syncKind(); }, 'Kind of journey'));
    box.appendChild(inspectorField('What kind?', kindRow,
      tEl('div', 'journey-hint', 'Career starts with internship paths and recruiting dates; anything else starts with one empty path.')));
    box.appendChild(inspectorField('Name', name));
    box.appendChild(inspectorField('What’s it for? The assistant plans from this.', purpose));

    const year = tEl('select', 'job-field-input');
    year.setAttribute('aria-label', 'First year of the timeline');
    // Most people open this after their first year, so first run defaults to
    // last fall; a later journey lines up with the open one.
    const around = first ? data.start_year - 1 : data.start_year;
    for (let y = around - 2; y <= around + 2; y++) {
      const o = tEl('option', '', 'Fall ' + y + ' – Spring ' + (y + 4));
      o.value = y;
      year.appendChild(o);
    }
    year.value = around;
    box.appendChild(inspectorField('Timeline', year));

    const picks = tEl('div', 'journey-picks');
    (data.candidates || []).forEach(c => {
      const row = tEl('label', 'journey-pick');
      const cb = tEl('input');
      cb.type = 'checkbox';
      cb.value = c.roadmap_id;
      cb.checked = first && /career/i.test(c.project) && c.steps > 0;
      row.appendChild(cb);
      const text = tEl('span', '');
      text.appendChild(tEl('b', '', c.project));
      text.appendChild(document.createTextNode(' — ' + (c.goal || 'roadmap') + ' · ' + c.steps + ' steps'));
      row.appendChild(text);
      picks.appendChild(row);
    });
    const picksField = inspectorField('Bring in an existing roadmap as its own path (the original stays as it is)', picks);
    box.appendChild(picksField);
    syncKind();

    const buttons = tEl('div', 'journey-setup-buttons');
    const go = tEl('button', 'btn-primary', 'Create journey');
    go.onclick = async () => {
      setButtonBusy(go, 'Creating…');
      const res = await jsonSend('/api/journey/setup', {
        kind, name: name.value.trim(), purpose: purpose.value.trim(), start_year: Number(year.value),
        copy_roadmap_ids: kind === 'career'
          ? Array.from(picks.querySelectorAll('input:checked')).map(i => i.value) : [],
      });
      if (res.error) { setButtonIdle(go, 'Create journey'); toast(res.error, {error: true}); return; }
      await renderJourney();
    };
    buttons.appendChild(go);
    if (!first) {
      const cancel = tEl('button', 'btn-ghost', 'Cancel');
      cancel.onclick = () => renderJourneyHome();
      buttons.appendChild(cancel);
    }
    box.appendChild(buttons);
    setTimeout(() => name.focus());
    return box;
  }

  // ---------- back to all journeys ----------

  // The back button: its arrow hangs in the margin so the words line up
  // with the title under it.
  function journeyBackButton(label, onclick) {
    const back = tEl('button', 'jcrumb-back');
    back.type = 'button';
    back.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>';
    back.appendChild(tEl('span', '', label));
    back.setAttribute('aria-label', 'Back to ' + label);
    back.onclick = onclick;
    return back;
  }

  function journeyCrumb() {
    const bar = tEl('div', 'jcrumb');
    bar.appendChild(journeyBackButton('Journeys', () => openJourneyView()));
    return bar;
  }

  function journeyMenu() {
    const save = async patch => {
      const res = await jsonSend('/api/journey', patch, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return; }
      await Promise.all([renderJourney(), loadSidebar()]);
    };
    return [
      {label: 'Rename…', run: async () => {
        const name = await askText('Rename journey', journeyData.name);
        if (name) await save({name});
      }},
      {label: 'Edit what it’s for…', run: async () => {
        const purpose = await askText('What is this journey for?', journeyData.purpose,
                                      'The assistant plans from this');
        if (purpose !== null && purpose !== undefined) await save({purpose});
      }},
      {label: journeyIsMap() ? 'Show as school terms' : 'Show as a path map', run: async () => {
        const res = await jsonSend('/api/journey/layout',
          {project_id: journeyData.project_id, layout: journeyIsMap() ? 'terms' : 'map'});
        if (res.error) { toast(res.error, {error: true}); return; }
        await renderJourney();
      }},
      {divider: true},
      {label: 'Delete journey…', danger: true, run: async () => {
        const ok = await askConfirm('Delete ' + journeyData.name + '?',
          'Its paths and steps go with it. Chats filed in its project are kept.', 'Delete');
        if (!ok) return;
        const res = await api('/api/projects/' + journeyData.project_id, {method: 'DELETE'});
        if (res && res.error) { toast(res.error, {error: true}); return; }
        toast('Deleted ' + journeyData.name);
        await Promise.all([openJourneyView(), loadSidebar()]);
      }},
    ];
  }

  // ---------- header and tabs ----------

  function journeyHead() {
    const head = tEl('div', 'jhead');
    const title = tEl('div', 'jhead-text');
    const row = tEl('div', 'jhead-title');
    row.appendChild(tEl('div', 'proj-title', journeyData.name));
    const more = tEl('button', 'jhead-more', '\u22ef');
    more.type = 'button';
    more.title = 'Journey options';
    more.setAttribute('aria-label', 'Journey options');
    more.onclick = () => showMenuFrom(more, journeyMenu());
    row.appendChild(more);
    title.appendChild(row);
    if (journeyData.purpose) title.appendChild(tEl('div', 'jhead-purpose', journeyData.purpose));
    const all = journeyData.tracks.flatMap(t => t.steps).filter(s => s.status !== 'rejected');
    title.appendChild(tEl('div', 'jhead-sub', journeyIsMap()
      ? 'Path map · ' + all.filter(s => s.status === 'done').length + ' of ' + all.length + ' steps done'
      : journeyData.current_label + ' · Year ' + journeyData.current_year + ' of 4'));
    head.appendChild(title);
    // The career journey is also Career's Plan tab, so it carries the same switch.
    if (journeyData.kind === 'career') head.appendChild(careerSwitch('plan'));
    return head;
  }

  // "All paths" turns every path on; each path pill toggles itself.
  function journeyTabs() {
    const bar = tEl('div', 'jtabs');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Paths to show');
    const hidden = journeyHidden();
    const all = tEl('button', 'jtab' + (hidden.length ? '' : ' active'), 'All paths');
    all.type = 'button';
    all.setAttribute('aria-pressed', String(!hidden.length));
    all.onclick = () => { setJourneyHidden([]); renderJourney(); };
    bar.appendChild(all);
    journeyPaths().forEach(t => {
      const on = !hidden.includes(t.id);
      const b = tEl('button', 'jtab jtoggle' + (on ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Hide ' + t.name : 'Show ' + t.name;
      const dot = tEl('span', 'jdot');
      dot.style.setProperty('--c', journeyTrackColor(t));
      b.append(dot, tEl('span', '', t.name));
      const more = tEl('span', 'jtab-more', '\u22ef');
      more.setAttribute('aria-label', t.name + ' options');
      more.onclick = e => { e.stopPropagation(); showMenuFrom(more, journeyTrackMenu(t.id)); };
      b.appendChild(more);
      onRightClick(b, e => showMenu(e, journeyTrackMenu(t.id)));
      b.onclick = () => {
        if (on && journeyShown().length === 1) { toast('Keep at least one path on'); return; }
        setJourneyHidden(on ? [...hidden, t.id] : hidden.filter(id => id !== t.id));
        renderJourney();
      };
      bar.appendChild(b);
    });
    const plus = tEl('button', 'jtab jtab-add', '+');
    plus.type = 'button';
    plus.setAttribute('aria-label', 'New path');
    plus.onclick = async () => {
      const name = await askText('New path', '', 'e.g. School, Research, Startup');
      if (!name) return;
      const res = await jsonSend('/api/journey/tracks', {name});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderJourney();
    };
    bar.appendChild(plus);
    return bar;
  }

  function journeyTrackMenu(id) {
    const track = journeyData.tracks.find(t => t.id === id);
    return [
      {label: 'Show only this', run: () => { journeyOnly(id); renderJourney(); }},
      {label: 'Rename…', run: async () => {
        const name = await askText('Rename path', track.name);
        if (!name) return;
        const res = await jsonSend('/api/journey/tracks/' + id, {name}, 'PATCH');
        if (res.error) toast(res.error, {error: true}); else await renderJourney();
      }},
      {label: 'Edit goal…', run: async () => {
        const goal = await askText('What is this path aiming at?', track.goal);
        if (!goal) return;
        const res = await jsonSend('/api/journey/tracks/' + id, {goal}, 'PATCH');
        if (res.error) toast(res.error, {error: true}); else await renderJourney();
      }},
      {label: 'Duplicate', run: async () => {
        const res = await jsonSend('/api/journey/tracks/' + id + '/duplicate', {});
        if (res.error) { toast(res.error, {error: true}); return; }
        await renderJourney();
      }},
      {label: 'Delete path…', run: async () => {
        if (!await askConfirm('Delete ' + track.name + '?',
            'Its ' + track.steps.length + ' steps go with it.', 'Delete')) return;
        const res = await api('/api/journey/tracks/' + id, {method: 'DELETE'});
        if (res.error) { toast(res.error, {error: true}); return; }
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
    if (year.number <= now) head.appendChild(journeyReviewButtons(year));
    sec.appendChild(head);
    if (journeyOpenReviews.has(year.number) && journeyData.reviews[year.number]) {
      sec.appendChild(journeyReviewCard(journeyData.reviews[year.number]));
    }
    const grid = tEl('div', 'jterms');
    year.terms.forEach(t => grid.appendChild(journeyTerm(t, steps.filter(s => s.term === t.term))));
    sec.appendChild(grid);
    return sec;
  }

  // A review reads your term notes, so it's only offered once a term has some.
  function journeyReviewButtons(year) {
    const number = year.number;
    const wrap = tEl('div', 'jyear-actions');
    const saved = journeyData.reviews[number];
    const hasNotes = year.terms.some(t => (journeyData.reflections[t.term] || '').trim());
    if (!saved && !hasNotes) {
      wrap.appendChild(tEl('span', 'jyear-hint', 'Add term notes to review this year'));
      return wrap;
    }
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
    const foot = tEl('div', 'jreview-foot', 'Reviewed ' + new Date(review.created_at).toLocaleDateString() + ' · ');
    const del = tEl('button', 'jreview-del', 'Delete review');
    del.type = 'button';
    del.onclick = async () => {
      if (!await askConfirm('Delete this review?', 'You can review the year again any time.', 'Delete')) return;
      const res = await jsonSend('/api/journey/review/delete', {year: review.year});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderJourney();
    };
    foot.appendChild(del);
    card.appendChild(foot);
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
    onRightClick(cell, e => showMenu(e, [
      {label: 'Add a step…', run: () => journeyAddStep(t.term)},
      ...(t.past || t.current ? [{label: 'Notes…', run: () => { journeyOpenNotes.add(t.term); renderJourney(); }}] : []),
    ]));
    head.appendChild(tools);
    cell.appendChild(head);

    if (journeyOpenNotes.has(t.term)) cell.appendChild(journeyReflectionBox(t));
    else if (journeyData.reflections[t.term]) {
      cell.appendChild(tEl('div', 'jterm-note', journeyData.reflections[t.term]));
    }
    // Drag order within the term; equal positions keep their old order.
    [...steps].sort((a, b) => (a.position || 0) - (b.position || 0))
      .forEach(s => cell.appendChild(journeyChip(s)));
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
    // Drag order within the term; equal positions keep their old order.
    [...steps].sort((a, b) => (a.position || 0) - (b.position || 0))
      .forEach(s => cell.appendChild(journeyChip(s)));
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
    chip.appendChild(journeyStatusMark(chip, s));
    chip.appendChild(tEl('span', 'jchip-title', s.title));
    if (s.shared && journeyTab() === 'all') chip.appendChild(tEl('span', 'jchip-tag', 'all'));
    const [done, total] = s.progress || [0, 0];
    if (total) {
      chip.appendChild(tEl('span', 'jchip-count', done + '/' + total));
      chip.classList.add('has-route');
      chip.style.setProperty('--p', Math.round(done / total * 100) + '%');
    }
    // ⋯ shows on hover: the same menu as a right-click, so editing and
    // deleting a step don't depend on knowing to right-click.
    const more = tEl('span', 'jchip-more', '\u22ef');
    more.setAttribute('aria-hidden', 'true');
    more.title = 'Edit, move or delete';
    more.onclick = e => { e.stopPropagation(); showMenuFrom(more, journeyStepMenu(s)); };
    chip.appendChild(more);
    chip.onclick = () => { if (chip._wasDragged) { chip._wasDragged = false; return; } openJourneyStep(s.id); };
    journeyEnableDrag(chip, s);
    onRightClick(chip, e => showMenu(e, journeyStepMenu(s)));
    return chip;
  }

  function journeyStepMenu(s) {
    const setStatus = async status => {
      const res = await jsonSend('/api/roadmap-node/' + s.id, {status}, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderJourney([s.id]);
    };
    return [
      {label: 'Open', run: () => openJourneyStep(s.id)},
      {label: 'Rename…', run: () => journeyRenameStep(s)},
      {label: 'Edit…', run: () => journeyStepSheet(s)},
      ...JOURNEY_STATUSES.filter(([v]) => v !== s.status)
        .map(([v, word]) => ({label: 'Mark ' + word, run: () => setStatus(v)})),
      {divider: true},
      {label: 'Delete', danger: true, run: () => softDelete({key: 'step:' + s.id, label: 'Step',
        remove: () => api('/api/roadmap-node/' + s.id, {method: 'DELETE'}), rerender: journeyRerender})},
    ];
  }

  async function journeyRenameStep(s) {
    const title = await askText('Rename step', s.title);
    if (!title || title === s.title) return;
    const res = await jsonSend('/api/roadmap-node/' + s.id, {title, detail: s.detail}, 'PATCH');
    if (res.error) toast(res.error, {error: true});
    await renderJourney([s.id]);
  }

  // The circle steps through Suggested → Planned → Done (and back to
  // Suggested). The chip updates at once; the save and redraw follow.
  const JOURNEY_CYCLE = {proposed: 'accepted', accepted: 'done', done: 'accepted', rejected: 'proposed'};
  const JOURNEY_STATUS_WORD = Object.fromEntries(JOURNEY_STATUSES);

  function journeyStatusMark(chip, s) {
    const mark = tEl('span', 'jmark', s.status === 'done' ? '✓' : '');
    const next = JOURNEY_CYCLE[s.status] || 'accepted';
    mark.title = JOURNEY_STATUS_WORD[s.status] + ' · click for ' + JOURNEY_STATUS_WORD[next];
    mark.onpointerdown = e => e.stopPropagation();   // a click here never starts a drag
    mark.onclick = async e => {
      e.stopPropagation();
      chip.classList.remove(s.status);
      chip.classList.add(next);
      mark.textContent = next === 'done' ? '✓' : '';
      const res = await jsonSend('/api/roadmap-node/' + s.id, {status: next}, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await renderJourney(res.error ? [] : [s.id]);
    };
    return mark;
  }

  // Drag a step to another term, or up and down within one; a line shows
  // where it will land.
  function journeyEnableDrag(chip, s) {
    chip.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.pointerType === 'touch') return;
      const sx = e.clientX, sy = e.clientY;
      let ghost = null, over = null, before = null;
      const line = tEl('div', 'jdrop-line');
      const cellAt = ev => document.elementsFromPoint(ev.clientX, ev.clientY)
        .find(n => n.classList && n.classList.contains('jterm')) || null;
      const others = cell => [...cell.querySelectorAll('.jchip')].filter(c => c !== chip);
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
          if (over && over.dataset.term !== s.term) over.classList.add('drop-target');
        }
        if (!over) { line.remove(); before = null; return; }
        before = others(over).find(c => {
          const r = c.getBoundingClientRect();
          return ev.clientY < r.top + r.height / 2;
        }) || null;
        const list = others(over);
        if (before) over.insertBefore(line, before);
        else if (list.length) list[list.length - 1].after(line);
        else over.appendChild(line);
      };
      const end = async ev => {
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', end);
        document.removeEventListener('pointercancel', end);
        line.remove();
        if (!ghost) return;
        chip._wasDragged = true;
        setTimeout(() => { chip._wasDragged = false; }, 0);
        ghost.remove();
        chip.classList.remove('drag-source');
        if (over) over.classList.remove('drop-target');
        if (!over || ev.type === 'pointercancel') return;
        const ids = others(over).map(c => c.dataset.key.slice('step:'.length));
        const at = before ? ids.indexOf(before.dataset.key.slice('step:'.length)) : ids.length;
        const order = [...ids.slice(0, at), s.id, ...ids.slice(at)];
        const current = [...over.querySelectorAll('.jchip')].map(c => c.dataset.key.slice('step:'.length));
        if (over.dataset.term === s.term && order.join() === current.join()) return;
        const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: over.dataset.term, order});
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

  // A day, a start time and a length, then one click makes the block.
  function journeyCalendarRow(s) {
    const row = tEl('div', 'jcal-row');
    const day = tEl('input');
    day.type = 'date';
    const tomorrow = new Date(Date.now() + 864e5);
    day.value = tomorrow.getFullYear() + '-' + String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
      String(tomorrow.getDate()).padStart(2, '0');
    day.setAttribute('aria-label', 'Day');
    const time = tEl('input');
    time.type = 'time';
    time.value = '09:00';
    time.setAttribute('aria-label', 'Start time');
    const length = tEl('select');
    length.setAttribute('aria-label', 'Length');
    [[30, '30 min'], [60, '1 hr'], [90, '1.5 hr'], [120, '2 hr'], [180, '3 hr']].forEach(([v, l]) => {
      const o = tEl('option', '', l);
      o.value = v;
      length.appendChild(o);
    });
    length.value = '60';
    const add = tEl('button', 'btn-tinted', 'Add block');
    add.type = 'button';
    add.onclick = async () => {
      setButtonBusy(add, 'Adding…');
      const res = await jsonSend('/api/journey/steps/' + s.id + '/calendar',
        {date: day.value, time: time.value, minutes: Number(length.value)});
      setButtonIdle(add, 'Add block');
      if (res.error) { toast(res.error, {error: true}); return; }
      toast('Added to your Google Calendar');
    };
    row.append(day, time, length, add);
    return row;
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
    const due = tEl('input', 'job-field-input');
    due.type = 'date';
    due.value = s.due_date || '';
    if (journeyIsMap()) field('Date', due); else field('Term', term);

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

    field('Put on Google Calendar', journeyCalendarRow(s));

    const del = tEl('button', 'btn-tinted btn-danger-tinted', 'Delete step');
    body.appendChild(del);
    let deleted = false;
    del.onclick = () => { deleted = true; del.closest('.modal').querySelector('.modal-actions .btn-primary').click(); };

    const ok = await modal({title: 'Step', body, confirmLabel: 'Save', multiline: true});
    if (!ok) return;
    if (deleted) {
      if (journeyFocus === s.id) journeyFocus = null;
      await renderJourney();
      softDelete({key: 'step:' + s.id, label: 'Step',
        remove: () => api('/api/roadmap-node/' + s.id, {method: 'DELETE'}), rerender: journeyRerender});
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
    if (!failed && due.value !== (s.due_date || '')) {
      const res = await jsonSend('/api/roadmap-node/' + s.id, {due_date: due.value}, 'PATCH');
      if (res.error) failed = res.error;
    }
    if (!failed && (term.value !== s.term || track.value !== s.track_id)) {
      const res = await jsonSend('/api/journey/steps/' + s.id + '/move', {term: term.value, track_id: track.value});
      if (res.error) failed = res.error;
    }
    if (failed) toast(failed, {error: true});
    await renderJourney([s.id]);
  }
