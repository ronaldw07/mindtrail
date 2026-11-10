  // ---------- journey: every journey as a box ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // The first thing Journey shows: one box per journey with what it's for,
  // its paths and how far along it is, and a box to start another.

  const JOURNEY_PATHS_SHOWN = 3;

  let journeyBadges = null;

  async function renderJourneyHome() {
    [journeyData, journeyBadges] = await Promise.all([api('/api/journey'), api('/api/badges')]);
    const view = $('journey-view');
    $('breadcrumb').textContent = 'Journey';
    hideJourneyDock();
    if (!journeyData.setup) { commitView(view, journeySetup(journeyData)); return; }

    const page = tEl('div', 'jhome');
    const head = tEl('div', 'jhome-head');
    head.appendChild(tEl('div', 'proj-title', 'Journeys'));
    head.appendChild(tEl('div', 'jhome-sub',
      'Each one is a plan over time. Open one to see its timeline and talk it through with the assistant.'));
    page.appendChild(head);

    const grid = tEl('div', 'jhome-grid');
    journeyData.journeys.forEach((j, i) => grid.appendChild(journeyBox(j, i)));
    grid.appendChild(journeyNewBox());
    page.appendChild(grid);
    commitView(view, page);
  }

  function journeyBox(j, index) {
    const box = tEl('div', 'jbox');
    box.style.setProperty('--jbox-color', JOURNEY_COLORS[index % JOURNEY_COLORS.length]);
    box.appendChild(tEl('div', 'jbox-kind', j.kind === 'career' ? 'Career' : 'Journey'));
    box.appendChild(tEl('div', 'jbox-name', j.name));
    box.appendChild(tEl('div', 'jbox-purpose' + (j.purpose ? '' : ' empty'),
      j.purpose || 'No purpose yet. Open it and add one so the assistant knows what to plan for.'));

    const paths = tEl('div', 'jbox-paths');
    j.paths.slice(0, JOURNEY_PATHS_SHOWN).forEach(name => paths.appendChild(tEl('span', 'jbox-path', name)));
    if (j.paths.length > JOURNEY_PATHS_SHOWN) {
      paths.appendChild(tEl('span', 'jbox-path more', '+' + (j.paths.length - JOURNEY_PATHS_SHOWN)));
    }
    box.appendChild(paths);

    const foot = tEl('div', 'jbox-foot');
    const bar = tEl('div', 'jbox-bar');
    const fill = tEl('div', 'jbox-fill');
    fill.style.width = (j.steps ? Math.round(j.done / j.steps * 100) : 0) + '%';
    bar.appendChild(fill);
    foot.appendChild(bar);
    foot.appendChild(tEl('div', 'jbox-count', j.steps
      ? j.done + ' of ' + j.steps + ' steps done'
      : 'No steps yet'));
    box.appendChild(foot);

    if (j.kind === 'career') box.appendChild(careerBoxLinks());

    makeClickable(box, () => openJourneyBox(j.project_id));
    onRightClick(box, e => showMenu(e, journeyBoxMenu(j)));
    box.setAttribute('aria-label', 'Open ' + j.name);
    return box;
  }

  // Rename and purpose edits go to the open journey, so pick this one first.
  function journeyBoxMenu(j) {
    const save = async patch => {
      const sel = await jsonSend('/api/journey/select', {project_id: j.project_id});
      if (sel.error) { toast(sel.error, {error: true}); return; }
      const res = await jsonSend('/api/journey', patch, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      await Promise.all([renderJourneyHome(), loadSidebar()]);
    };
    return [
      {label: 'Open', run: () => openJourneyBox(j.project_id)},
      {label: 'Rename…', run: async () => {
        const name = await askText('Rename journey', j.name);
        if (name) await save({name});
      }},
      {label: 'Edit what it’s for…', run: async () => {
        const purpose = await askText('What is this journey for?', j.purpose, 'The assistant plans from this');
        if (purpose !== null && purpose !== undefined) await save({purpose});
      }},
      {divider: true},
      {label: 'Delete journey…', danger: true, run: async () => {
        const ok = await askConfirm('Delete ' + j.name + '?',
          'Its paths and steps go with it. Chats filed in its project are kept.', 'Delete');
        if (!ok) return;
        const res = await api('/api/projects/' + j.project_id, {method: 'DELETE'});
        if (res && res.error) { toast(res.error, {error: true}); return; }
        await Promise.all([renderJourneyHome(), loadSidebar()]);
        toast('Deleted ' + j.name);
      }},
    ];
  }

  // Jobs and Practice live in the Career journey; these jump straight there.
  function careerBoxLinks() {
    const row = tEl('div', 'jbox-links');
    [['jobs', 'Jobs', () => openJobsView()], ['practice', 'Practice', () => openPracticeView()]]
      .forEach(([key, label, open]) => {
        const b = tEl('button', 'jbox-link', label);
        b.type = 'button';
        const n = (journeyBadges || {})[key] || 0;
        if (n) b.appendChild(tEl('span', 'jbox-link-count', String(n)));
        b.onclick = e => { e.stopPropagation(); prefs.set('careerTab', key); open(); };
        row.appendChild(b);
      });
    return row;
  }

  async function openJourneyBox(projectId) {
    if (projectId !== journeyData.project_id) {
      const res = await jsonSend('/api/journey/select', {project_id: projectId});
      if (res.error) { toast(res.error, {error: true}); return; }
    }
    await renderJourney();
  }

  function journeyNewBox() {
    const box = tEl('div', 'jbox jbox-new');
    box.appendChild(tEl('div', 'jbox-plus', '+'));
    box.appendChild(tEl('div', 'jbox-new-label', 'New journey'));
    box.appendChild(tEl('div', 'jbox-new-sub', 'Health, a language, a side project…'));
    makeClickable(box, () => { hideJourneyDock(); commitView($('journey-view'), journeySetup(journeyData)); });
    return box;
  }
