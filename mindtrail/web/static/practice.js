
  // ---------- practice log ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Coding problems you've done, brought back after 1, 3, 7 and 21 days.

  const DIFFICULTY_OPTIONS = [{value: 'easy', label: 'Easy'}, {value: 'medium', label: 'Medium'}, {value: 'hard', label: 'Hard'}];
  const OUTCOME_OPTIONS = [{value: 'solo', label: 'On my own'}, {value: 'help', label: 'With help'}, {value: 'stuck', label: 'Stuck'}];
  const OUTCOME_LABEL = {solo: 'On my own', help: 'With help', stuck: 'Stuck'};
  const PRACTICE_BLUE = '#3987e5';  // first validated categorical slot

  async function openPracticeView() {
    currentProject = null;
    current = null;
    setActiveView('practice');
    prefs.set('lastView', {type: 'practice'});
    $('breadcrumb').textContent = 'Practice';
    await renderPracticeView();
  }

  async function renderPracticeView() {
    const data = await api('/api/practice');
    const view = $('practice-view');
    const layout = tEl('div', 'brief-wrap practice-wrap');
    layout.appendChild(tEl('div', 'proj-title', 'Practice'));
    layout.appendChild(practiceAddForm(data));

    const due = data.problems.filter(p => p.due);
    if (due.length) {
      const section = tEl('section', 'group-section');
      section.appendChild(tEl('div', 'group-title due', 'Review today · ' + due.length));
      const list = tEl('div', 'group-list');
      due.forEach(p => list.appendChild(reviewRow(p)));
      section.appendChild(list);
      layout.appendChild(section);
    }
    if (data.coverage.length) layout.appendChild(coverageChart(data.coverage));

    if (data.problems.length) {
      const section = tEl('section', 'group-section');
      section.appendChild(tEl('div', 'group-title', 'Everything you’ve done · ' + data.problems.length));
      const list = tEl('div', 'group-list');
      data.problems.forEach(p => list.appendChild(problemRow(p)));
      section.appendChild(list);
      layout.appendChild(section);
    } else {
      layout.appendChild(emptyState('jobs', 'No problems yet',
        'Log each problem you solve. It comes back after 1, 3, 7 and 21 days so it sticks.'));
    }
    commitView(view, layout);
    loadBadges();
  }

  function practiceAddForm(data) {
    const form = tEl('form', 'practice-form card');
    let difficulty = 'medium';
    let outcome = 'solo';
    const title = tEl('input', 'jobs-link-input');
    title.placeholder = 'Problem — e.g. Two Sum';
    title.setAttribute('aria-label', 'Problem');
    const url = tEl('input', 'jobs-link-input');
    url.type = 'url';
    url.placeholder = 'Link (optional)';
    url.setAttribute('aria-label', 'Link');
    const topic = tEl('input', 'jobs-link-input');
    topic.placeholder = 'Topic — arrays, graphs, dp…';
    topic.setAttribute('aria-label', 'Topic');
    topic.setAttribute('list', 'practice-topics');
    const topics = tEl('datalist');
    topics.id = 'practice-topics';
    data.coverage.forEach(c => topics.appendChild(Object.assign(tEl('option'), {value: c.topic})));
    form.appendChild(title);
    const row = tEl('div', 'practice-form-row');
    row.appendChild(url);
    row.appendChild(topic);
    form.appendChild(row);
    const controls = tEl('div', 'practice-form-row');
    controls.appendChild(segmented(DIFFICULTY_OPTIONS, difficulty, v => { difficulty = v; }, 'Difficulty'));
    controls.appendChild(segmented(OUTCOME_OPTIONS, outcome, v => { outcome = v; }, 'How it went'));
    const add = tEl('button', 'btn-primary jobs-btn', 'Log it');
    add.type = 'submit';
    controls.appendChild(add);
    form.appendChild(controls);
    form.appendChild(topics);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!title.value.trim()) return;
      const res = await jsonSend('/api/practice', {title: title.value, url: url.value, topic: topic.value,
                                                   difficulty, outcome});
      if (res.error) { toast(res.error, {error: true}); return; }
      await renderPracticeView();
    };
    return form;
  }

  function problemLink(p) {
    if (!p.url || !/^https?:\/\//.test(p.url)) return tEl('span', 'problem-title', p.title);
    const a = tEl('a', 'problem-title', p.title);
    a.href = p.url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }

  function reviewRow(p) {
    const row = tEl('div', 'group-row problem-row');
    row.dataset.key = 'problem:' + p.id;
    const body = tEl('div', 'task-body');
    body.appendChild(problemLink(p));
    body.appendChild(tEl('span', 'job-chip', p.difficulty));
    if (p.topic) body.appendChild(tEl('span', 'task-due', p.topic));
    row.appendChild(body);
    [['solo', 'Solved it', 'btn-tinted'], ['help', 'Needed help', 'btn-plain'], ['stuck', 'Stuck', 'btn-plain']]
      .forEach(([outcome, label, cls]) => {
        const b = tEl('button', cls, label);
        b.onclick = async () => {
          const res = await jsonSend('/api/practice/' + p.id + '/review', {outcome});
          if (res.error) { toast(res.error, {error: true}); return; }
          await renderPracticeView();
        };
        row.appendChild(b);
      });
    return row;
  }

  function problemRow(p) {
    const row = tEl('div', 'group-row problem-row');
    row.dataset.key = 'problem:' + p.id;
    const body = tEl('div', 'task-body');
    body.appendChild(problemLink(p));
    body.appendChild(tEl('span', 'job-chip', p.difficulty));
    if (p.topic) body.appendChild(tEl('span', 'task-due', p.topic));
    body.appendChild(tEl('span', 'task-due', OUTCOME_LABEL[p.outcome]));
    row.appendChild(body);
    row.appendChild(tEl('span', 'problem-next' + (p.due ? ' due' : ''),
      p.next_review ? (p.due ? 'Due now' : 'Next ' + fmtShortDate(p.next_review)) : 'Done'));
    const del = tEl('button', 'menu-btn task-more', '×');
    del.setAttribute('aria-label', 'Delete ' + p.title);
    del.onclick = () => softDelete({key: 'problem:' + p.id, label: p.title,
      remove: () => api('/api/practice/' + p.id, {method: 'DELETE'}), rerender: renderPracticeView});
    row.appendChild(del);
    return row;
  }

  // One hue (the first validated categorical slot): solid is solved on your
  // own, the lighter remainder is everything that needed help or got stuck.
  // The counts are written out, so the colors carry no information alone.
  function coverageChart(coverage) {
    const section = tEl('section', 'group-section');
    section.appendChild(tEl('div', 'group-title', 'By topic'));
    const box = tEl('div', 'group-list coverage');
    const max = Math.max(...coverage.map(c => c.total));
    coverage.forEach(c => {
      const row = tEl('div', 'coverage-row');
      row.appendChild(tEl('span', 'coverage-label', c.topic));
      const track = tEl('div', 'coverage-track');
      const all = tEl('div', 'coverage-all');
      all.style.width = (c.total / max * 100) + '%';
      all.style.setProperty('--bar', PRACTICE_BLUE);
      const solo = tEl('div', 'coverage-solo');
      solo.style.width = (c.solo / c.total * 100) + '%';
      all.appendChild(solo);
      track.appendChild(all);
      row.appendChild(track);
      row.appendChild(tEl('span', 'coverage-count', c.total + ' · ' + c.solo + ' alone'));
      box.appendChild(row);
    });
    section.appendChild(box);
    return section;
  }
