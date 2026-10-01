
  // ---------- focus timer ----------
  // Declarations only, loaded before app.js (see the note atop jobs.js).
  //
  // The running timer lives in prefs, not memory, so a reload or a closed
  // tab doesn't lose it - resumeFocus() picks it up on boot, and a timer
  // that ended while the tab was closed is logged then. The countdown is
  // plain text updated once a second: nothing animates on a timer you
  // glance at all day.

  const FOCUS_LENGTHS = [25, 50, 15];
  const FOCUS_MIN_LOG = 5;  // a stop before this many minutes isn't worth logging
  let focusTick = null;

  async function startFocus(opts) {
    opts = opts || {};
    if (prefs.get('focusTimer', null)) { toast('A focus session is already running'); return; }
    const label = opts.label || await askText('Focus on…', '', 'e.g. IBM interview prep');
    if (!label) return;
    const minutes = await modal({title: 'How long?', confirmLabel: 'Start', value: 25,
      select: FOCUS_LENGTHS.map(m => ({value: m, label: m + ' minutes'}))});
    if (minutes === null) return;
    prefs.set('focusTimer', {started_at: new Date().toISOString(), minutes: Number(minutes),
                             label, task_id: opts.task_id || ''});
    resumeFocus();
  }

  function focusRemainingMs(t) {
    return new Date(t.started_at).getTime() + t.minutes * 60000 - Date.now();
  }

  async function logFocus(t, minutes) {
    prefs.set('focusTimer', null);
    clearInterval(focusTick);
    focusTick = null;
    renderFocusPill(null);
    if (minutes < FOCUS_MIN_LOG) { toast('Focus session discarded'); return; }
    const res = await jsonSend('/api/focus', {started_at: t.started_at, minutes,
                                              label: t.label, task_id: t.task_id});
    toast(res.error ? 'Couldn’t log focus: ' + res.error : 'Logged ' + minutes + ' min of focus');
    if ($('dashboard-view').classList.contains('open')) openDashboardView();
  }

  function resumeFocus() {
    const t = prefs.get('focusTimer', null);
    if (!t) return;
    if (focusRemainingMs(t) <= 0) { logFocus(t, t.minutes); return; }
    renderFocusPill(t);
    clearInterval(focusTick);
    focusTick = setInterval(() => {
      if (focusRemainingMs(t) <= 0) logFocus(t, t.minutes);
      else renderFocusPill(t);
    }, 1000);
  }

  function renderFocusPill(t) {
    let pill = $('focus-pill');
    if (!t) { if (pill) pill.remove(); return; }
    if (!pill) {
      pill = document.createElement('div');
      pill.id = 'focus-pill';
      pill.setAttribute('role', 'timer');
      const label = document.createElement('span');
      label.className = 'focus-label';
      const time = document.createElement('span');
      time.className = 'focus-time';
      const stop = document.createElement('button');
      stop.className = 'nav-btn focus-stop';
      stop.textContent = 'Stop';
      stop.onclick = () => {
        const cur = prefs.get('focusTimer', null);
        if (!cur) return;
        const elapsed = Math.floor((Date.now() - new Date(cur.started_at).getTime()) / 60000);
        logFocus(cur, Math.min(elapsed, cur.minutes));
      };
      pill.appendChild(label);
      pill.appendChild(time);
      pill.appendChild(stop);
      $('topbar').appendChild(pill);
    }
    const ms = Math.max(focusRemainingMs(t), 0);
    const mm = Math.floor(ms / 60000), ss = Math.floor(ms / 1000) % 60;
    pill.querySelector('.focus-label').textContent = t.label;
    pill.querySelector('.focus-time').textContent = mm + ':' + String(ss).padStart(2, '0');
  }
