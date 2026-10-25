
  // ---------- Settings: the Measure card ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Log minutes spent planning or re-finding research, mark when you
  // started using Mind Trail, and see the weekly average before and after.

  const MEASURE_KINDS = [['planning', 'Planning'], ['refinding', 'Re-finding research']];

  function measureLine(label, before, after, change, unit) {
    const row = tEl('div', 'measure-line');
    row.appendChild(tEl('div', 'measure-label', label));
    const nums = tEl('div', 'measure-nums');
    nums.appendChild(tEl('span', '', before === null ? '—' : before + ' → ' + (after === null ? '—' : after) + ' ' + unit));
    if (change !== null && change !== undefined) {
      nums.appendChild(tEl('span', 'measure-change' + (change > 0 ? ' good' : ''),
        (label === 'Tasks done per day' ? (change >= 0 ? '+' : '') + change + '%' : Math.abs(change) + '% ' + (change >= 0 ? 'less' : 'more'))));
    }
    row.appendChild(nums);
    return row;
  }

  function measureCard() {
    const c = card('Measure', null, null);
    const body = tEl('div', 'measure-body');
    c.appendChild(body);

    const paint = data => {
      body.innerHTML = '';
      const today = data.today;

      const kind = tEl('select', 'job-field-input');
      MEASURE_KINDS.forEach(([v, l]) => { const o = tEl('option', '', l); o.value = v; kind.appendChild(o); });
      kind.setAttribute('aria-label', 'What you spent time on');
      const mins = tEl('input', 'jobs-link-input measure-mins');
      mins.type = 'number'; mins.min = 1; mins.max = 600; mins.placeholder = 'Minutes';
      mins.setAttribute('aria-label', 'Minutes');
      const day = tEl('input', 'job-field-input');
      day.type = 'date'; day.value = today;
      day.setAttribute('aria-label', 'Day');
      const log = tEl('button', 'btn-tinted', 'Log');
      log.onclick = async () => {
        const res = await jsonSend('/api/measure/log', {kind: kind.value, minutes: mins.value, day: day.value});
        if (res.error) { toast(res.error, {error: true}); return; }
        paint(await api('/api/measure'));
      };
      mins.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); log.click(); } };
      const form = tEl('div', 'task-add habit-add measure-form');
      [kind, mins, day, log].forEach(n => form.appendChild(n));
      body.appendChild(settingRow('Log time', form,
        'Planning: working out what to do next. Re-finding: looking for something you already researched. ' +
        'Log a normal week the old way first, then a week with Mind Trail.'));

      const split = tEl('input', 'job-field-input');
      split.type = 'date'; split.value = data.split || '';
      split.setAttribute('aria-label', 'First day using Mind Trail');
      split.onchange = async () => {
        const res = await jsonSend('/api/measure/split', {day: split.value});
        if (res.error) { toast(res.error, {error: true}); return; }
        paint(await api('/api/measure'));
      };
      body.appendChild(settingRow('Started using Mind Trail', split,
        'Logs before this day are the baseline; this day and after are the comparison.'));

      const results = tEl('div', 'measure-results');
      if (!data.split) {
        results.appendChild(tEl('div', 'measure-empty', 'Pick the day you started to see before and after.'));
      } else {
        const b = data.before, a = data.after;
        const nb = b.weeks, na = a.weeks;
        MEASURE_KINDS.forEach(([k, l]) => results.appendChild(
          measureLine(l, b.avg[k], a.avg[k], data.change[k], 'min / week')));
        results.appendChild(measureLine('Tasks done per day', b.tasks_per_day, a.tasks_per_day,
          data.change.tasks, 'per day'));
        results.appendChild(tEl('div', 'measure-foot',
          'Based on ' + nb + ' baseline week' + (nb === 1 ? '' : 's') + ' and ' + na + ' week' + (na === 1 ? '' : 's') +
          ' with Mind Trail. A week only counts once it has ended.'));
      }
      body.appendChild(results);

      if (data.recent.length) {
        const list = tEl('div', 'measure-recent');
        data.recent.forEach(r => {
          const row = tEl('div', 'measure-row');
          row.appendChild(tEl('span', '', r.day + ' · ' + (r.kind === 'planning' ? 'Planning' : 'Re-finding') + ' · ' + r.minutes + ' min'));
          const del = tEl('button', 'btn-plain', 'Remove');
          del.onclick = async () => {
            await api('/api/measure/log/' + r.id, {method: 'DELETE'});
            paint(await api('/api/measure'));
          };
          row.appendChild(del);
          list.appendChild(row);
        });
        body.appendChild(list);
      }
    };
    api('/api/measure').then(paint);
    return c;
  }
