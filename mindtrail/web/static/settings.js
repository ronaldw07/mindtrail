
  // ---------- settings cards: setup checklist, backups, data ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.

  function setupCard() {
    const c = card('Setup', null, null);
    const body = tEl('div', 'setup-body');
    c.appendChild(body);
    api('/api/connections').then(data => {
      if (data.error) { body.textContent = data.error; return; }
      body.innerHTML = '';
      const head = tEl('div', 'setup-head');
      head.appendChild(tEl('div', 'setup-count', data.done + ' of ' + data.total + ' set up'));
      const track = tEl('div', 'week-bar-track setup-track');
      const fill = tEl('div', 'week-bar-fill setup-fill');
      fill.style.width = (data.done / data.total * 100) + '%';
      track.appendChild(fill);
      head.appendChild(track);
      body.appendChild(head);
      data.checklist.forEach(item => {
        const row = tEl('div', 'setup-row' + (item.done ? ' done' : ''));
        const mark = tEl('span', 'setup-mark');
        mark.innerHTML = item.done
          ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" '
            + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>'
          : '';
        row.appendChild(mark);
        const text = tEl('div', 'setup-text');
        text.appendChild(tEl('div', 'setup-label', item.label));
        text.appendChild(tEl('div', 'setup-detail', item.detail));
        row.appendChild(text);
        body.appendChild(row);
      });
    });
    return c;
  }

  function fmtBytes(n) {
    return n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  }

  function backupsCard() {
    const c = card('Backups', null, null);
    c.appendChild(tEl('div', 'muted area-hint',
      'A copy of your to-dos, habits, journal and the rest is saved once a day while Mind Trail is open, '
      + 'and the newest 14 are kept. Pick a folder you trust - iCloud Drive keeps a copy off this Mac.'));
    const body = tEl('div', 'backup-body');
    c.appendChild(body);

    const paint = data => {
      body.innerHTML = '';
      if (data.error) { body.appendChild(tEl('div', 'canvas-error', data.error)); return; }
      body.appendChild(settingRow('Daily backups', switchEl(data.enabled, async on => {
        const res = await jsonSend('/api/backups/enable', {enabled: on});
        if (res.error) toast(res.error, {error: true});
        paint(res.error ? data : res);
      }, 'Daily backups'), data.enabled ? 'On' : 'Off - nothing is written until you turn this on'));
      body.appendChild(settingRow('Folder', (() => {
        const change = tEl('button', 'btn-tinted', 'Change…');
        change.onclick = async () => {
          const path = await askText('Backup folder', data.folder, '/Users/you/Backups');
          if (path) paint(await jsonSend('/api/backups/folder', {path}));
        };
        return change;
      })(), data.folder));
      body.appendChild(settingRow('Last backup', (() => {
        const now = tEl('button', 'btn-tinted', 'Back up now');
        now.onclick = async () => {
          setButtonBusy(now, 'Backing up…');
          const res = await jsonSend('/api/backups/run', {});
          if (res.error) toast(res.error, {error: true}); else toast('Backed up');
          paint(res.error ? data : res);
        };
        return now;
      })(), data.last ? fmtShortDate(data.last) : 'Never'));
      if (data.backups.length) {
        body.appendChild(tEl('div', 'widget-head', 'Restore from'));
        const list = tEl('div', 'group-list');
        data.backups.forEach(b => {
          const row = tEl('div', 'widget-row');
          row.appendChild(tEl('span', 'widget-name', fmtShortDate(b.date)));
          row.appendChild(tEl('span', 'muted', fmtBytes(b.life_bytes + b.db_bytes)));
          const restore = tEl('button', 'btn-plain', 'Restore');
          restore.disabled = !b.life_bytes;
          restore.onclick = async () => {
            const ok = await modal({title: 'Restore ' + fmtShortDate(b.date) + '?',
              message: 'Anything deleted or changed since then comes back. Things you added after '
                + 'that day are kept.', confirmLabel: 'Restore'});
            if (!ok) return;
            const res = await jsonSend('/api/backups/restore', {date: b.date});
            if (res.error) { toast(res.error, {error: true}); return; }
            toast('Restored ' + res.restored + ' items' + (res.failed ? ' (' + res.failed + ' failed)' : ''));
            loadBadges();
          };
          row.appendChild(restore);
          list.appendChild(row);
        });
        body.appendChild(list);
      }
    };
    api('/api/backups').then(paint);
    return c;
  }

  function dataCard() {
    const c = card('Data', null, null);
    const btn = tEl('button', 'btn-tinted', 'Export everything…');
    btn.onclick = () => exportData(btn);
    c.appendChild(settingRow('Export as Markdown', btn,
      'Chats, projects, roadmaps and journal as plain files you can keep anywhere.'));
    return c;
  }
