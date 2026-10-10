
  // ---------- recruiting extras inside Jobs and Today ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Interview rounds and the offer details live in the job's detail panel;
  // offers sit side by side under the board; Today gets reminders.

  const ROUND_KINDS = [['phone', 'Phone screen'], ['technical', 'Technical'], ['behavioral', 'Behavioral'],
                       ['onsite', 'Onsite'], ['other', 'Other']];
  const roundKindLabel = k => (ROUND_KINDS.find(r => r[0] === k) || ['', 'Round'])[1];
  const fmtMoney = n => n ? '$' + Number(n).toLocaleString('en-US') : '–';

  function roundsSection(a) {
    const box = el('div', 'rounds');
    box.appendChild(el('div', 'brief-section-label', 'Interview rounds'));
    const save = async (id, fields, redraw) => {
      const res = await jsonSend('/api/rounds/' + id, fields, 'PATCH');
      if (res.error) toast(res.error, {error: true});
      else if (redraw) await reloadJobs();
    };
    a.rounds.forEach(r => {
      const card = el('div', 'round-card');
      card.dataset.key = 'round:' + r.id;
      const top = el('div', 'round-top');
      const kind = el('select', 'job-field-input');
      kind.setAttribute('aria-label', 'Kind of round');
      ROUND_KINDS.forEach(([value, label]) => {
        const o = el('option', '', label);
        o.value = value;
        kind.appendChild(o);
      });
      kind.value = r.kind;
      kind.onchange = () => save(r.id, {kind: kind.value}, true);
      const date = el('input', 'job-field-input');
      date.type = 'date';
      date.value = r.date;
      date.setAttribute('aria-label', 'Date');
      date.onchange = () => save(r.id, {date: date.value}, true);
      const del = el('button', 'menu-btn task-more', '×');
      del.setAttribute('aria-label', 'Delete round');
      del.style.opacity = '1';
      del.onclick = () => softDelete({key: 'round:' + r.id, label: 'Round',
        remove: () => api('/api/rounds/' + r.id, {method: 'DELETE'}), rerender: reloadJobs});
      top.appendChild(kind);
      top.appendChild(date);
      top.appendChild(del);
      card.appendChild(top);
      const who = el('input', 'job-field-input');
      who.value = r.interviewer;
      who.placeholder = 'Interviewer';
      who.setAttribute('aria-label', 'Interviewer');
      who.onchange = () => save(r.id, {interviewer: who.value}, false);
      card.appendChild(who);
      [['prep_notes', 'Prep notes — what to review'], ['questions', 'Questions they asked']].forEach(([key, hint]) => {
        const t = el('textarea', 'job-field-input round-text');
        t.value = r[key];
        t.placeholder = hint;
        t.setAttribute('aria-label', hint);
        t.onchange = () => save(r.id, {[key]: t.value}, false);
        card.appendChild(t);
      });
      box.appendChild(card);
    });
    const add = el('button', 'btn-tinted', a.rounds.length ? 'Add another round' : 'Add a round');
    add.onclick = async () => {
      const res = await jsonSend('/api/jobs/' + a.id + '/rounds', {kind: 'phone'});
      if (res.error) toast(res.error, {error: true}); else await reloadJobs();
    };
    box.appendChild(add);
    return box;
  }

  // Compensation for an application that reached the offer stage. The first
  // year total updates as you type; it's saved when you leave the field.
  function offerSection(a) {
    const box = el('div', 'offer-section');
    box.appendChild(el('div', 'brief-section-label', 'Offer'));
    const total = el('div', 'offer-total');
    const fields = {};
    const sum = () => ['base', 'bonus', 'equity_per_year', 'signing']
      .reduce((n, k) => n + (parseInt(String(fields[k].value).replace(/[^0-9]/g, ''), 10) || 0), 0);
    const paint = () => { total.textContent = 'First year: ' + fmtMoney(sum()); };
    const grid = el('div', 'offer-grid');
    [['base', 'Base salary'], ['bonus', 'Bonus'], ['equity_per_year', 'Equity per year'], ['signing', 'Signing bonus']]
      .forEach(([key, label]) => {
        const input = el('input', 'job-field-input');
        input.inputMode = 'numeric';
        input.placeholder = '0';
        input.setAttribute('aria-label', label);
        fields[key] = input;
        input.oninput = paint;
        input.onchange = () => saveOffer(a.id, {[key]: input.value});
        const f = el('label', 'job-field');
        f.appendChild(el('span', 'job-field-label', label));
        f.appendChild(input);
        grid.appendChild(f);
      });
    box.appendChild(grid);
    box.appendChild(total);
    [['location', 'Location', 'text'], ['start_date', 'Start date', 'date']].forEach(([key, label, type]) => {
      const input = el('input', 'job-field-input');
      input.type = type;
      input.setAttribute('aria-label', label);
      fields[key] = input;
      input.onchange = () => saveOffer(a.id, {[key]: input.value});
      const f = el('label', 'job-field');
      f.appendChild(el('span', 'job-field-label', label));
      f.appendChild(input);
      box.appendChild(f);
    });
    api('/api/offers').then(d => {
      const mine = (d.offers || []).find(o => o.application_id === a.id);
      if (mine) {
        ['base', 'bonus', 'equity_per_year', 'signing'].forEach(k => { fields[k].value = mine[k] || ''; });
        fields.location.value = mine.location;
        fields.start_date.value = mine.start_date;
      }
      paint();
    });
    paint();
    return box;
  }

  async function saveOffer(applicationId, fields) {
    const res = await jsonSend('/api/offers/' + applicationId, fields);
    if (res.error) { toast(res.error, {error: true}); return; }
    const panel = document.querySelector('.offers-panel');
    if (panel) fillOffersPanel(panel);
  }

  // Offers side by side. Hidden until there's an offer with numbers in it.
  function offersPanel() {
    const panel = el('section', 'offers-panel');
    panel.hidden = true;
    fillOffersPanel(panel);
    return panel;
  }

  async function fillOffersPanel(panel) {
    const data = await api('/api/offers');
    const offers = (data.offers || []).filter(o => o.first_year > 0);
    panel.hidden = offers.length === 0;
    panel.innerHTML = '';
    if (!offers.length) return;
    panel.appendChild(el('div', 'group-title', 'Offers side by side'));
    const table = el('table', 'offer-table');
    const best = Math.max(...offers.map(o => o.first_year));
    const head = el('tr');
    head.appendChild(el('th', ''));
    offers.forEach(o => head.appendChild(el('th', '', o.company)));
    table.appendChild(head);
    [['Base', o => fmtMoney(o.base)], ['Bonus', o => fmtMoney(o.bonus)],
     ['Equity / year', o => fmtMoney(o.equity_per_year)], ['Signing', o => fmtMoney(o.signing)],
     ['First year', o => fmtMoney(o.first_year), true],
     ['Location', o => o.location || '–'], ['Start', o => o.start_date ? fmtShortDate(o.start_date) : '–']]
      .forEach(([label, get, total]) => {
        const tr = el('tr', total ? 'offer-total-row' : '');
        tr.appendChild(el('th', '', label));
        offers.forEach(o => {
          const td = el('td', total && o.first_year === best && offers.length > 1 ? 'offer-best' : '', get(o));
          tr.appendChild(td);
        });
        table.appendChild(tr);
      });
    panel.appendChild(table);
  }

  // ---------- Today ----------

  // Interviews in the next week, and problems due a second look. One
  // request feeds both widgets; each hides itself when it has nothing.
  let recruitingTodayPromise = null;
  const loadRecruitingToday = () => (recruitingTodayPromise = api('/api/recruiting/today'));

  function interviewsTile() {
    const tile = glanceTile('Interviews', () => openJobsView());
    tile.hidden = true;
    loadRecruitingToday().then(d => {
      if (!d.interviews || !d.interviews.length) return;
      tile.hidden = false;
      d.interviews.slice(0, 4).forEach(r => {
        const when = r.days_away === 0 ? 'Today' : r.days_away === 1 ? 'Tomorrow' : 'In ' + r.days_away + ' days';
        const item = tEl('div', 't-item');
        const body = tEl('div', 't-item-body');
        body.appendChild(tEl('div', 't-item-title', r.company + ' · ' + roundKindLabel(r.kind)));
        body.appendChild(tEl('div', 't-item-sub', when + (r.prep_notes ? ' · prep notes ready' : ' · no prep notes yet')));
        item.appendChild(body);
        makeClickable(item, () => openJobsView(r.application_id));
        tile.appendChild(item);
      });
    });
    return tile;
  }

  function practiceTile() {
    const tile = glanceTile('Practice to review', () => openPracticeView());
    tile.hidden = true;
    loadRecruitingToday().then(d => {
      const due = d.practice_due || [];
      if (!due.length) return;
      tile.hidden = false;
      due.slice(0, 4).forEach(p => {
        const item = tEl('div', 't-item');
        const body = tEl('div', 't-item-body');
        body.appendChild(tEl('div', 't-item-title', p.title));
        body.appendChild(tEl('div', 't-item-sub', p.difficulty + (p.topic ? ' · ' + p.topic : '')));
        item.appendChild(body);
        makeClickable(item, () => openPracticeView());
        tile.appendChild(item);
      });
      if (due.length > 4) tile.appendChild(tEl('div', 't-note', '+ ' + (due.length - 4) + ' more'));
    });
    return tile;
  }
