  // ---------- journey: every journey as a box ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // The first thing Journey shows: one box per journey with what it's for,
  // its paths and how far along it is, and a box to start another.

  const JOURNEY_PATHS_SHOWN = 3;

  let journeyBadges = null;

  async function renderJourneyHome() {
    let profile;
    [journeyData, journeyBadges, profile] = await Promise.all([api('/api/journey'), api('/api/badges'),
                                                               api('/api/profile')]);
    const view = $('journey-view');
    $('breadcrumb').textContent = 'Journey';
    if (!journeyData.setup) { hideJourneyDock(); commitView(view, journeySetup(journeyData)); return; }

    const page = tEl('div', 'jhome');
    const head = tEl('div', 'jhome-head');
    head.appendChild(tEl('div', 'proj-title', 'Journeys'));
    head.appendChild(tEl('div', 'jhome-sub',
      'Each one is a plan over time. Open one to see its timeline and talk it through with the assistant.'));
    page.appendChild(head);

    // Journeys without a folder first, then one section per folder. Colors
    // follow the journey's place in the full list, so filing one doesn't
    // repaint the others.
    const all = journeyData.journeys;
    const grid = tEl('div', 'jhome-grid');
    all.forEach((j, i) => { if (!j.folder) grid.appendChild(journeyBox(j, i)); });
    grid.appendChild(journeyNewBox());
    page.appendChild(grid);
    (journeyData.folders || []).forEach(name => {
      page.appendChild(journeyFolder(name, all.map((j, i) => [j, i]).filter(([j]) => j.folder === name)));
    });
    page.appendChild(journeyAbout(profileFacts(profile.content || '')));
    commitView(view, page);
    if (activeView === 'journey') showJourneyDock('home');
  }

  // ---------- what the assistant knows about you ----------
  // The profile, one fact per line, same split as profile_facts() on the
  // server. Every assistant reads it; each fact can be edited or deleted
  // here, and the assistant can propose new ones as you talk.

  const factOf = line => line.split(/\s+/).filter(Boolean).join(' ');
  const profileFacts = text => text.split('\n').map(factOf).filter(Boolean);

  // Change one fact in the saved text, leaving every other line (blank
  // lines and spacing included) as it was. to === null removes it; with
  // no fact given, to is added at the end.
  async function saveFact(fact, to, focusKey) {
    const text = (await api('/api/profile')).content || '';
    const lines = text.split('\n');
    const at = fact === null ? -1 : lines.findIndex(l => factOf(l) === fact);
    let next;
    if (at < 0) next = to && !profileFacts(text).includes(to) ? text.replace(/\s*$/, '') + (text.trim() ? '\n' : '') + to : text;
    else if (to) next = lines.map((l, i) => i === at ? to : l).join('\n');
    else next = lines.filter((_, i) => i !== at).join('\n');
    const res = await jsonSend('/api/profile', {content: next});
    if (res.error) toast(res.error, {error: true});
    await renderJourneyHome();
    const back = focusKey && document.querySelector('[data-focus="' + focusKey + '"]');
    if (back) back.focus();
  }

  function journeyAbout(facts) {
    const sec = tEl('section', 'jabout');
    const head = tEl('div', 'jabout-head');
    const text = tEl('div', 'jabout-text');
    text.appendChild(tEl('h2', 'jabout-title', 'What I know about you'));
    text.appendChild(tEl('div', 'jabout-sub', facts.length
      ? 'Every assistant reads these. Click one to change it.'
      : 'Nothing yet. Add facts here, or tell the assistant about yourself and it offers to remember them.'));
    head.appendChild(text);
    if (facts.length) {
      const sum = tEl('button', 'btn-tinted', 'Summarize me');
      sum.type = 'button';
      sum.onclick = () => askJourneyAssistant('Summarize who I am from what you know about me.',
                                              {fresh: true, title: 'About me', scope: 'home'});
      head.appendChild(sum);
    }
    sec.appendChild(head);
    const list = tEl('ul', 'jabout-list');
    facts.forEach((fact, i) => list.appendChild(journeyFact(fact, i)));
    sec.appendChild(list);
    sec.appendChild(journeyFactAdd());
    return sec;
  }

  function journeyFact(fact, i) {
    const row = tEl('li', 'jabout-fact');
    row.dataset.key = 'fact:' + i;
    const label = tEl('span', 'jabout-fact-text', fact);
    label.dataset.focus = 'fact:' + i;
    makeClickable(label, () => editFact(row, label, fact));
    const del = tEl('button', 'jabout-del', '×');
    del.type = 'button';
    del.setAttribute('aria-label', 'Forget: ' + fact);
    del.title = 'Forget this';
    del.onclick = () => softDelete({key: 'fact:' + i, label: 'Fact',
      remove: () => saveFact(fact, null)});
    row.append(label, del);
    return row;
  }

  function editFact(row, label, fact) {
    const input = tEl('input', 'jabout-input');
    input.value = fact;
    input.setAttribute('aria-label', 'Edit fact');
    let done = false;
    const finish = async save => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      if (!save || value === fact) { input.replaceWith(label); label.focus(); return; }
      await saveFact(fact, value || null, label.dataset.focus);
    };
    input.onkeydown = e => {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
    };
    input.onblur = () => finish(true);
    label.replaceWith(input);
    input.focus();
  }

  function journeyFactAdd() {
    const form = tEl('form', 'jabout-add');
    const input = tEl('input', 'jabout-input');
    input.placeholder = 'Add something about you…';
    input.setAttribute('aria-label', 'Add a fact about you');
    keepDraft(input, 'fact-add');
    form.appendChild(input);
    form.onsubmit = async e => {
      e.preventDefault();
      const value = input.value.trim();
      if (!value) return;
      journeyDrafts['fact-add'] = '';
      await saveFact(null, factOf(value));
      const next = document.querySelector('.jabout-add .jabout-input');
      if (next) next.focus();
    };
    return form;
  }

  const FOLDER_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 ' +
    '2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';

  function journeyFolder(name, members) {
    const closed = prefs.get('journeyFoldersClosed', []).includes(name);
    const sec = tEl('section', 'jfolder' + (closed ? ' collapsed' : ''));
    sec.dataset.key = 'folder:' + name;
    const head = tEl('div', 'jfolder-head');
    const icon = tEl('span', 'jfolder-icon');
    icon.innerHTML = FOLDER_ICON;
    head.append(icon, tEl('span', 'jfolder-name', name), tEl('span', 'jfolder-count', String(members.length)),
                tEl('span', 'jfolder-caret', '▾'));
    head.setAttribute('aria-expanded', String(!closed));
    makeClickable(head, () => {
      const list = prefs.get('journeyFoldersClosed', []);
      const nowClosed = !sec.classList.contains('collapsed');
      prefs.set('journeyFoldersClosed', nowClosed ? [...list, name] : list.filter(n => n !== name));
      sec.classList.toggle('collapsed', nowClosed);
      head.setAttribute('aria-expanded', String(!nowClosed));
    });
    onRightClick(head, e => showMenu(e, journeyFolderMenu(name)));
    const bar = tEl('div', 'jfolder-bar');
    const more = tEl('button', 'jhead-more jfolder-more', '\u22ef');
    more.type = 'button';
    more.setAttribute('aria-label', name + ' folder options');
    more.onclick = () => showMenuFrom(more, journeyFolderMenu(name));
    bar.append(head, more);
    sec.appendChild(bar);
    const grid = tEl('div', 'jhome-grid');
    members.forEach(([j, i]) => grid.appendChild(journeyBox(j, i)));
    sec.appendChild(grid);
    return sec;
  }

  function journeyFolderMenu(name) {
    const rename = async to => {
      const res = await jsonSend('/api/journey/folders/rename', {old: name, new: to});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderJourneyHome();
    };
    return [
      {label: 'Rename folder…', run: async () => {
        const to = await askText('Rename folder', name);
        if (to) await rename(to);
      }},
      {label: 'Ungroup', run: () => rename('')},
    ];
  }

  async function setJourneyFolder(projectId, folder) {
    const res = await jsonSend('/api/journey/folder', {project_id: projectId, folder});
    if (res.error) { toast(res.error, {error: true}); return; }
    await renderJourneyHome();
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
    if (j.next && j.next.length) box.appendChild(tEl('div', 'jbox-next', 'Next: ' + j.next[0]));

    if (j.kind === 'career') box.appendChild(careerBoxLinks());

    const more = tEl('button', 'jhead-more jbox-more', '\u22ef');
    more.type = 'button';
    more.dataset.focus = 'box-more:' + j.project_id;
    more.setAttribute('aria-label', j.name + ' options');
    more.onclick = e => { e.stopPropagation(); showMenuFrom(more, journeyBoxMenu(j)); };
    box.appendChild(more);

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
      ...(journeyData.folders || []).filter(f => f !== j.folder)
        .map(f => ({label: 'Move to ' + f, run: () => setJourneyFolder(j.project_id, f)})),
      {label: 'New folder…', run: async () => {
        const folder = await askText('New folder', '', 'e.g. Health, School, Side projects');
        if (folder) await setJourneyFolder(j.project_id, folder);
      }},
      ...(j.folder ? [{label: 'Remove from folder', run: () => setJourneyFolder(j.project_id, '')}] : []),
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
