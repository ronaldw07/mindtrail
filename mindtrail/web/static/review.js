
  // ---------- weekly review ----------
  // Declarations only, loaded before app.js (see the note atop jobs.js).
  // Reuses Today's section layout (t-section / t-label) so the two pages
  // read as one product.

  let weekOffset = 0;

  async function openWeekView(offset) {
    currentProject = null;
    current = null;
    setActiveView('week');
    prefs.set('lastView', {type: 'week'});
    $('breadcrumb').textContent = 'Week';
    weekOffset = offset || 0;
    await renderWeekView();
  }

  const fmtRange = (a, b) => fmtShortDate(a) + ' – ' + fmtShortDate(b);

  async function renderWeekView() {
    const w = await api('/api/week?offset=' + weekOffset);
    const view = $('week-view');
    view.innerHTML = '';
    if (w.error) { view.appendChild(tEl('div', 't-empty', w.error)); return; }
    const page = tEl('div', 't-page');

    const head = tEl('div', 'week-head');
    const prev = tEl('button', 'nav-btn', '←');
    prev.setAttribute('aria-label', 'Previous week');
    prev.onclick = () => openWeekView(weekOffset - 1);
    const next = tEl('button', 'nav-btn', '→');
    next.setAttribute('aria-label', 'Next week');
    next.disabled = weekOffset >= 0;
    next.onclick = () => openWeekView(weekOffset + 1);
    const title = tEl('h1', 'week-title');
    title.appendChild(tEl('span', 't-title-the', w.is_current ? 'This week' : 'The week of'));
    title.appendChild(tEl('span', 'week-range', fmtRange(w.week_start, w.week_end)));
    head.appendChild(prev);
    head.appendChild(title);
    head.appendChild(next);
    page.appendChild(head);

    page.appendChild(section('In a few words', weekSummary(w)));
    if (w.priorities.length) page.appendChild(section('Priorities you set', plainList(w.priorities)));
    page.appendChild(section('Finished', doneList(w)));
    if (w.slipped.length) page.appendChild(section('Slipped', slippedList(w)));
    page.appendChild(section('Habits', habitBars(w.habits)));
    page.appendChild(section('Mood & energy', moodSummary(w.mood)));
    page.appendChild(section('Job search', jobsSummary(w.jobs)));
    page.appendChild(section('Where your focus went', focusByArea(w.focus)));
    if (w.is_current) page.appendChild(section('Next week’s top three', priorityForm(w)));
    view.appendChild(page);
  }

  function weekSummary(w) {
    const box = tEl('div', 't-list');
    const text = tEl('p', 't-brief', w.summary || '');
    box.appendChild(text);
    const btn = tEl('button', 't-link', w.summary ? 'Rewrite' : 'Summarize my week');
    btn.onclick = async () => {
      text.classList.add('pending');
      text.textContent = 'Reading your week…';
      const res = await jsonSend('/api/week/summary', {offset: weekOffset});
      text.classList.remove('pending');
      text.textContent = res.text || 'Couldn’t summarize: ' + res.error;
      btn.textContent = 'Rewrite';
    };
    box.appendChild(btn);
    return box;
  }

  function plainList(items) {
    const list = tEl('div', 't-list');
    items.forEach(p => list.appendChild(todoItem({title: p, sub: ''})));
    return list;
  }

  function doneList(w) {
    const list = tEl('div', 't-list');
    if (!w.done.length) list.appendChild(tEl('div', 't-empty', 'No to-dos checked off this week.'));
    w.done.forEach(d => {
      const row = todoItem({title: d.title, sub: 'Done'});
      row.classList.add('finished');
      list.appendChild(row);
    });
    return list;
  }

  function slippedList(w) {
    const list = tEl('div', 't-list');
    w.slipped.forEach(s => list.appendChild(todoItem({title: s.title, overdue: true,
      sub: 'Was due ' + fmtShortDate(s.due_date)})));
    if (w.is_current) {
      const btn = tEl('button', 'btn-primary jobs-btn t-carry', 'Move all to Monday');
      btn.onclick = async () => {
        const res = await jsonSend('/api/tasks/roll', {to: addDays(w.week_end, 1)});
        if (res.error) { toast(res.error, {error: true}); return; }
        toast('Moved ' + res.moved + ' to Monday');
        renderWeekView();
      };
      list.appendChild(btn);
    }
    return list;
  }

  // One bar per habit: check-ins against its target, in the habit's
  // area color, labeled with the count so color is never the only cue.
  function habitBars(h) {
    const box = tEl('div', 't-list');
    if (!h.rows.length) { box.appendChild(tEl('div', 't-empty', 'No habits yet.')); return box; }
    box.appendChild(tEl('div', 'week-rate', Math.round(h.rate * 100) + '% of check-ins hit'));
    h.rows.forEach(r => {
      const row = tEl('div', 'week-bar-row');
      row.appendChild(tEl('span', 'week-bar-label', r.name));
      const track = tEl('div', 'week-bar-track');
      const fill = tEl('div', 'week-bar-fill');
      fill.style.width = Math.min(r.done / Math.max(r.target, 1), 1) * 100 + '%';
      fill.style.background = habitColor(r);
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(tEl('span', 'week-bar-value', r.done + ' / ' + r.target));
      box.appendChild(row);
    });
    return box;
  }

  function moodSummary(m) {
    const box = tEl('div', 't-list');
    if (m.avg_mood === null && m.avg_energy === null) {
      box.appendChild(tEl('div', 't-empty', 'No ratings in the journal this week.'));
      return box;
    }
    const delta = m.avg_mood !== null && m.prev_avg_mood !== null
      ? (m.avg_mood > m.prev_avg_mood ? ', up from ' : m.avg_mood < m.prev_avg_mood ? ', down from '
         : ', same as ') + m.prev_avg_mood + ' last week' : '';
    if (m.avg_mood !== null) box.appendChild(tEl('div', 't-item-title', 'Mood ' + m.avg_mood + ' / 5' + delta));
    if (m.avg_energy !== null) box.appendChild(tEl('div', 't-item-sub', 'Energy ' + m.avg_energy + ' / 5'));
    box.appendChild(tEl('div', 't-item-sub', m.entries + ' journal entr' + (m.entries === 1 ? 'y' : 'ies')));
    return box;
  }

  function jobsSummary(j) {
    const box = tEl('div', 't-list');
    box.appendChild(tEl('div', 't-item-title', j.applied.length
      ? 'Applied to ' + j.applied.length + ': ' + j.applied.join(', ') : 'No new applications'));
    if (j.moved.length) {
      box.appendChild(tEl('div', 't-item-sub', 'Moving forward: ' +
        j.moved.map(m => m.company + ' (' + JOB_STAGE_LABELS[m.stage] + ')').join(', ')));
    }
    return box;
  }

  // Horizontal bars, one per area, longest first. Categorical: each bar
  // wears its area's color from the validated palette, and the area name
  // and time sit beside it in text colors.
  function focusByArea(f) {
    const box = tEl('div', 't-list');
    if (!f.total) {
      box.appendChild(tEl('div', 't-empty', 'No focus sessions this week.'));
      const start = tEl('button', 't-link', 'Start one');
      start.onclick = () => startFocus();
      box.appendChild(start);
      return box;
    }
    box.appendChild(tEl('div', 'week-rate', fmtMinutes(f.total) + ' focused'));
    const max = Math.max(...f.by_area.map(a => a.minutes));
    f.by_area.forEach(a => {
      const area = areaById(a.area_id);
      const row = tEl('div', 'week-bar-row');
      row.appendChild(tEl('span', 'week-bar-label', area ? area.name : 'No area'));
      const track = tEl('div', 'week-bar-track');
      const fill = tEl('div', 'week-bar-fill');
      fill.style.width = (a.minutes / max) * 100 + '%';
      fill.style.background = area ? area.color : 'var(--text-muted)';
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(tEl('span', 'week-bar-value', fmtMinutes(a.minutes)));
      box.appendChild(row);
    });
    return box;
  }

  function priorityForm(w) {
    const form = tEl('form', 'week-priorities');
    const inputs = [0, 1, 2].map(i => {
      const input = tEl('input', 'jobs-link-input');
      input.value = w.next_priorities[i] || '';
      input.placeholder = ['The one thing that matters most', 'Second', 'Third'][i];
      input.setAttribute('aria-label', 'Priority ' + (i + 1));
      form.appendChild(input);
      return input;
    });
    const save = tEl('button', 'btn-primary jobs-btn', 'Save');
    save.type = 'submit';
    form.appendChild(save);
    form.onsubmit = async e => {
      e.preventDefault();
      const res = await jsonSend('/api/week/priorities', {
        week_start: addDays(w.week_end, 1), items: inputs.map(i => i.value)});
      toast(res.error ? res.error : 'Saved for next week');
    };
    return form;
  }
