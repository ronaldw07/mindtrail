
  // ---------- story bank ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Behavioral stories as situation / task / action / result, tagged by
  // theme, with a note of where each has been used.

  const STORY_PARTS = [
    ['situation', 'Situation', 'What was going on?'],
    ['task', 'Task', 'What were you responsible for?'],
    ['action', 'Action', 'What did you do, specifically?'],
    ['result', 'Result', 'What happened? Numbers help.'],
  ];
  const THEME_IDEAS = ['leadership', 'conflict', 'failure', 'teamwork', 'ownership', 'deadline', 'ambiguity'];
  let storiesSelectedId = null;
  let storiesTheme = '';

  async function openStoriesView() {
    currentProject = null;
    current = null;
    setActiveView('stories');
    prefs.set('lastView', {type: 'stories'});
    $('breadcrumb').textContent = 'Stories';
    await renderStoriesView();
  }

  async function renderStoriesView() {
    const data = await api('/api/stories');
    const view = $('stories-view');
    if (storiesTheme && !data.themes.some(t => t.theme === storiesTheme)) storiesTheme = '';
    if (storiesSelectedId && !data.stories.some(s => s.id === storiesSelectedId)) storiesSelectedId = null;

    const layout = tEl('div', 'tasks-layout');
    const main = tEl('div', 'tasks-main');
    const head = tEl('div', 'jobs-head');
    head.appendChild(tEl('div', 'proj-title', 'Stories'));
    const add = tEl('button', 'btn-primary jobs-btn', 'New story');
    add.onclick = async () => {
      const title = await askText('New story', '', 'e.g. Led the database migration');
      if (!title) return;
      const res = await jsonSend('/api/stories', {title});
      if (res.error) { toast(res.error, {error: true}); return; }
      storiesSelectedId = res.story.id;
      await renderStoriesView();
    };
    head.appendChild(add);
    main.appendChild(head);

    if (data.themes.length) {
      const chips = tEl('div', 'theme-chips');
      const all = tEl('button', 'theme-chip' + (storiesTheme ? '' : ' active'), 'All');
      all.onclick = () => { storiesTheme = ''; renderStoriesView(); };
      chips.appendChild(all);
      data.themes.forEach(t => {
        const b = tEl('button', 'theme-chip' + (storiesTheme === t.theme ? ' active' : ''), t.theme + ' · ' + t.count);
        b.onclick = () => { storiesTheme = storiesTheme === t.theme ? '' : t.theme; renderStoriesView(); };
        chips.appendChild(b);
      });
      main.appendChild(chips);
    }

    const shown = data.stories.filter(s => !storiesTheme || s.theme_list.includes(storiesTheme));
    if (shown.length) {
      const list = tEl('div', 'group-list');
      shown.forEach(s => list.appendChild(storyRow(s)));
      main.appendChild(list);
    } else {
      main.appendChild(emptyState('journal', 'No stories yet',
        'Write 5–6 stories once, tag them by theme, and reuse them across interviews.',
        'New story', () => add.click()));
    }
    layout.appendChild(main);
    const selected = data.stories.find(s => s.id === storiesSelectedId);
    if (selected) layout.appendChild(storyInspector(selected));
    commitView(view, layout);
  }

  function storyRow(s) {
    const row = tEl('div', 'group-row story-row' + (s.id === storiesSelectedId ? ' selected' : ''));
    row.dataset.key = 'story:' + s.id;
    const body = tEl('div', 'story-body');
    body.appendChild(tEl('div', 'story-title', s.title));
    const preview = s.result || s.action || s.situation;
    if (preview) body.appendChild(tEl('div', 'story-preview', preview));
    if (s.theme_list.length) {
      const tags = tEl('div', 'story-tags');
      s.theme_list.forEach(t => tags.appendChild(tEl('span', 'job-chip', t)));
      body.appendChild(tags);
    }
    row.appendChild(body);
    makeClickable(row, () => {
      storiesSelectedId = storiesSelectedId === s.id ? null : s.id;
      renderStoriesView();
    });
    return row;
  }

  function storyInspector(s) {
    const panel = tEl('aside', 'inspector story-inspector');
    const head = tEl('div', 'inspector-head');
    head.appendChild(tEl('div', 'inspector-kicker', 'Story'));
    const close = tEl('button', 'btn-plain', 'Done');
    close.onclick = () => { storiesSelectedId = null; renderStoriesView(); };
    head.appendChild(close);
    panel.appendChild(head);

    // Edits save when you leave the field; the list redraws only for the
    // things it shows (title, themes), so typing in a long field never
    // gets interrupted.
    const save = async (fields, redraw) => {
      const res = await jsonSend('/api/stories/' + s.id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      else if (redraw) await renderStoriesView();
    };
    const title = tEl('input', 'inspector-title');
    title.value = s.title;
    title.setAttribute('aria-label', 'Title');
    title.onchange = () => { if (title.value.trim()) save({title: title.value}, true); };
    panel.appendChild(title);

    STORY_PARTS.forEach(([key, label, hint]) => {
      const box = tEl('textarea', 'job-field-input story-field');
      box.value = s[key];
      box.placeholder = hint;
      box.setAttribute('aria-label', label);
      box.onchange = () => save({[key]: box.value}, key === 'result' || key === 'action' || key === 'situation');
      panel.appendChild(inspectorField(label, box));
    });
    const themes = tEl('input', 'job-field-input');
    themes.value = s.theme_list.join(', ');
    themes.placeholder = 'leadership, conflict…';
    themes.setAttribute('aria-label', 'Themes');
    themes.setAttribute('list', 'story-themes');
    const ideas = tEl('datalist');
    ideas.id = 'story-themes';
    THEME_IDEAS.forEach(t => ideas.appendChild(Object.assign(tEl('option'), {value: t})));
    themes.onchange = () => save({themes: themes.value}, true);
    panel.appendChild(inspectorField('Themes', themes, ideas));
    const used = tEl('textarea', 'job-field-input');
    used.value = s.used_in;
    used.placeholder = 'Where you’ve told it — e.g. Stripe phone screen';
    used.setAttribute('aria-label', 'Used in');
    used.onchange = () => save({used_in: used.value}, false);
    panel.appendChild(inspectorField('Used in', used));

    const del = tEl('button', 'btn-tinted btn-danger-tinted', 'Delete');
    del.onclick = () => {
      storiesSelectedId = null;
      renderStoriesView().then(() => softDelete({key: 'story:' + s.id, label: 'Story',
        remove: () => api('/api/stories/' + s.id, {method: 'DELETE'}), rerender: renderStoriesView}));
    };
    const actions = tEl('div', 'inspector-actions');
    actions.appendChild(del);
    panel.appendChild(actions);
    return panel;
  }
