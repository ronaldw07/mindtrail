
  // ---------- ui: appearance, and fluid view updates ----------
  // Loaded before every other script and made only of declarations (plus
  // the two listeners at the bottom). Nothing here touches app bindings
  // (prefs, toast...) until a function actually runs.

  const ACCENTS = [
    {key: 'blue', label: 'Blue', swatch: '#0a84ff'},
    {key: 'purple', label: 'Purple', swatch: '#af52de'},
    {key: 'pink', label: 'Pink', swatch: '#ff2d6f'},
    {key: 'red', label: 'Red', swatch: '#ff453a'},
    {key: 'orange', label: 'Orange', swatch: '#ff9500'},
    {key: 'green', label: 'Green', swatch: '#30b050'},
    {key: 'teal', label: 'Teal', swatch: '#20b2c0'},
    {key: 'graphite', label: 'Graphite', swatch: '#8e8e93'},
  ];
  const APPEARANCES = [
    {value: 'system', label: 'Auto'}, {value: 'light', label: 'Light'}, {value: 'dark', label: 'Dark'},
  ];

  function applyAppearance() {
    const mode = prefs.get('appearance', 'system');
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const root = document.documentElement;
    root.dataset.theme = mode === 'system' ? (dark ? 'dark' : 'light') : mode;
    root.dataset.accent = prefs.get('accent', 'blue');
  }
  function setAppearance(mode) { prefs.set('appearance', mode); applyAppearance(); }
  function setAccent(key) { prefs.set('accent', key); applyAppearance(); }

  // True when the person asked their Mac to cut motion down. Animations
  // here are all decoration or orientation - none carries information
  // that isn't also on screen afterwards - so they simply don't run.
  const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Keyboard-driven changes are repeated hundreds of times a day and
  // should land instantly; only pointer-driven ones glide.
  const keyboardDriven = () => document.documentElement.dataset.input === 'keyboard';

  const cssVarMs = (name, fallback) => {
    const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
    return Number.isFinite(v) ? v : fallback;
  };

  // Swap a view's contents for a freshly built tree without the jump a bare
  // `innerHTML = ''` + append causes:
  //   - scroll position is kept,
  //   - keyboard focus lands back on the same control,
  //   - rows tagged data-key that moved glide to their new place (FLIP),
  //   - new keyed rows fade in, and removed ones fade out where they stood.
  // The new tree is built by the caller exactly as before (fresh nodes,
  // fresh handlers), so no event wiring can go stale.
  function commitView(view, wrap) {
    const scrollTop = view.scrollTop;
    const active = document.activeElement;
    const focusKey = active && view.contains(active) ? focusSignature(active) : null;

    const animate = !reducedMotion() && !keyboardDriven() && view.classList.contains('open');
    const oldNodes = new Map();
    const oldRects = new Map();
    if (animate) {
      view.querySelectorAll('[data-key]').forEach(n => {
        oldNodes.set(n.dataset.key, n);
        oldRects.set(n.dataset.key, n.getBoundingClientRect());
      });
    }
    const hadRows = oldNodes.size > 0;

    view.replaceChildren(wrap);
    view.scrollTop = scrollTop;

    if (focusKey) {
      const target = Array.from(view.querySelectorAll('input, button, select, textarea, [tabindex]'))
        .find(n => focusSignature(n) === focusKey);
      if (target) target.focus({preventScroll: true});
    }
    if (!animate || !hadRows) return;

    const dur = cssVarMs('--dur-spring-smooth', 380);
    const ease = getComputedStyle(document.documentElement).getPropertyValue('--spring-smooth').trim() || 'ease-out';
    const viewRect = view.getBoundingClientRect();
    const seen = new Set();

    view.querySelectorAll('[data-key]').forEach(n => {
      const key = n.dataset.key;
      seen.add(key);
      const was = oldRects.get(key);
      if (!was) {
        n.animate([{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'none'}],
                  {duration: 200, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
        return;
      }
      const now = n.getBoundingClientRect();
      const dx = was.left - now.left;
      const dy = was.top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      n.animate([{transform: `translate(${dx}px, ${dy}px)`}, {transform: 'none'}],
                {duration: dur, easing: ease});
    });

    // Rows that are gone: leave a faded ghost where they stood.
    if (getComputedStyle(view).position === 'static') view.style.position = 'relative';
    oldNodes.forEach((node, key) => {
      if (seen.has(key)) return;
      const was = oldRects.get(key);
      const ghost = node;
      ghost.style.position = 'absolute';
      ghost.style.left = (was.left - viewRect.left + view.scrollLeft) + 'px';
      ghost.style.top = (was.top - viewRect.top + view.scrollTop) + 'px';
      ghost.style.width = was.width + 'px';
      ghost.style.pointerEvents = 'none';
      view.appendChild(ghost);
      const fade = ghost.animate([{opacity: 1, transform: 'none'}, {opacity: 0, transform: 'scale(0.98)'}],
                                 {duration: 160, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
      fade.onfinish = () => ghost.remove();
    });
  }

  // Enough to find "the same control" in the rebuilt tree.
  function focusSignature(node) {
    return [node.tagName, node.id, node.getAttribute('aria-label') || '', node.dataset.key || '',
            node.getAttribute('placeholder') || '', node.className].join('|');
  }

  // Show the change now, save it after; if the save fails, undo the
  // change and say so. `apply` and `revert` touch the DOM or local state.
  async function optimistic(apply, request, revert, failMessage) {
    apply();
    let res;
    try { res = await request(); } catch (err) { res = {error: String(err)}; }
    if (res && res.error) {
      revert();
      toast(failMessage || res.error, {error: true});
    }
    return res;
  }

  // Delete with an undo instead of a confirm dialog. The row disappears at
  // once; the real delete only happens when the undo toast runs out, so
  // "undo" never has to re-create anything. `key` is the row's data-key.
  function softDelete({key, label, remove, rerender}) {
    const node = document.querySelector('main [data-key="' + key + '"]');
    const hide = () => {
      if (!node) return;
      node.classList.add('removing');
      setTimeout(() => { if (node.classList.contains('removing')) node.hidden = true; }, 180);
    };
    const show = () => {
      if (!node) return;
      node.hidden = false;
      requestAnimationFrame(() => node.classList.remove('removing'));
    };
    hide();
    toast(label + ' deleted', {
      undo: async () => { show(); },
      onExpire: async () => { await remove(); if (rerender) await rerender(); },
      seconds: 5,
    });
  }

  // Count a number up/down to its new value. Only used when a stat
  // changes while you're looking at it, never on first paint.
  function rollNumber(node, to, {suffix = '', duration = 450} = {}) {
    const from = parseFloat(node.dataset.value || '0');
    node.dataset.value = String(to);
    if (reducedMotion() || from === to) { node.textContent = to + suffix; return; }
    const start = performance.now();
    const step = now => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      node.textContent = Math.round(from + (to - from) * eased) + suffix;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyAppearance);
  // Track how the last input arrived, so motion can skip keyboard actions.
  ['pointerdown', 'mousedown', 'touchstart'].forEach(type =>
    document.addEventListener(type, () => { document.documentElement.dataset.input = 'pointer'; },
                              {capture: true, passive: true}));
  document.addEventListener('keydown', () => { document.documentElement.dataset.input = 'keyboard'; },
                            {capture: true});

  // ---------- toolbar ----------

  // Big-title views: the toolbar shows the view's name only once the big
  // title has scrolled out from under it, like a native large title.
  function updateToolbarTitle() {
    const bar = $('topbar');
    const view = document.querySelector('main > div.open:not(#roadmap-view)');
    const large = bar.dataset.title === 'large';
    const scrolled = !!view && view.scrollTop > 28;
    bar.classList.toggle('scrolled', large ? scrolled : false);
    bar.classList.toggle('title-hidden', large && !scrolled);
  }
  document.addEventListener('scroll', e => {
    if (e.target && e.target.nodeType === 1 && e.target.matches('main > div')) updateToolbarTitle();
  }, {capture: true, passive: true});

  // Counts on the sidebar rows: to-dos due, people due a nudge, jobs to review.
  async function loadBadges() {
    const counts = await api('/api/badges');
    if (!counts || counts.error) return;
    document.querySelectorAll('.side-badge').forEach(b => {
      const n = counts[b.dataset.badge] || 0;
      b.hidden = n === 0;
      b.textContent = n > 99 ? '99+' : String(n);
    });
  }

  // A menu that grows out of the button that opened it.
  function showMenuFrom(button, items) {
    const r = button.getBoundingClientRect();
    showMenu({clientX: r.right - 190, clientY: r.bottom + 6}, items);
    $('menu').style.transformOrigin = 'top right';
  }

  // ---------- components ----------

  // Segmented control with a thumb that slides to the chosen option.
  // options: [{value, label}]. onChange(value) runs after the thumb moves.
  function segmented(options, value, onChange, label) {
    const root = document.createElement('div');
    root.className = 'seg';
    root.setAttribute('role', 'radiogroup');
    if (label) root.setAttribute('aria-label', label);
    root.style.setProperty('--seg-count', String(options.length));
    const thumb = document.createElement('div');
    thumb.className = 'seg-thumb';
    root.appendChild(thumb);
    const buttons = options.map((opt, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'seg-opt';
      b.setAttribute('role', 'radio');
      b.textContent = opt.label;
      b.onclick = () => select(i, true);
      root.appendChild(b);
      return b;
    });
    function select(i, notify) {
      root.style.setProperty('--seg-index', String(i));
      buttons.forEach((b, j) => {
        b.setAttribute('aria-checked', j === i ? 'true' : 'false');
        b.tabIndex = j === i ? 0 : -1;
      });
      if (notify) onChange(options[i].value);
    }
    root.addEventListener('keydown', e => {
      const at = buttons.findIndex(b => b.getAttribute('aria-checked') === 'true');
      const next = e.key === 'ArrowRight' ? at + 1 : e.key === 'ArrowLeft' ? at - 1 : null;
      if (next === null || next < 0 || next >= buttons.length) return;
      e.preventDefault();
      select(next, true);
      buttons[next].focus();
    });
    select(Math.max(0, options.findIndex(o => o.value === value)), false);
    return root;
  }

  // iOS-style switch.
  function switchEl(checked, onChange, label) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'switch';
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-checked', checked ? 'true' : 'false');
    if (label) b.setAttribute('aria-label', label);
    const knob = document.createElement('span');
    knob.className = 'switch-knob';
    b.appendChild(knob);
    b.onclick = () => {
      const on = b.getAttribute('aria-checked') !== 'true';
      b.setAttribute('aria-checked', on ? 'true' : 'false');
      onChange(on);
    };
    return b;
  }

  // The 8 system-style accent colors as a row of swatches.
  function accentPicker() {
    const row = document.createElement('div');
    row.className = 'accent-row';
    row.setAttribute('role', 'radiogroup');
    row.setAttribute('aria-label', 'Accent color');
    const current = prefs.get('accent', 'blue');
    ACCENTS.forEach(a => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'accent-dot';
      b.style.setProperty('--dot', a.swatch);
      b.title = a.label;
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-label', a.label);
      b.setAttribute('aria-checked', a.key === current ? 'true' : 'false');
      b.onclick = () => {
        setAccent(a.key);
        row.querySelectorAll('.accent-dot').forEach(d =>
          d.setAttribute('aria-checked', d === b ? 'true' : 'false'));
      };
      row.appendChild(b);
    });
    return row;
  }

  // A labelled row inside a grouped list: label on the left, control on the right.
  function settingRow(label, control, hint) {
    const row = document.createElement('div');
    row.className = 'setting-row';
    const text = document.createElement('div');
    text.className = 'setting-text';
    const l = document.createElement('div');
    l.className = 'setting-label';
    l.textContent = label;
    text.appendChild(l);
    if (hint) {
      const h = document.createElement('div');
      h.className = 'setting-hint';
      h.textContent = hint;
      text.appendChild(h);
    }
    row.appendChild(text);
    row.appendChild(control);
    return row;
  }

  function appearanceCard() {
    const c = card('Appearance', null, null);
    c.appendChild(settingRow('Theme',
      segmented(APPEARANCES, prefs.get('appearance', 'system'), setAppearance, 'Theme'),
      'Auto follows your Mac.'));
    c.appendChild(settingRow('Accent color', accentPicker()));
    return c;
  }

  // ---------- avatars and empty states ----------

  // A colored initial. The color is picked from the name, so the same
  // person or company always looks the same.
  const AVATAR_COLORS = ['#0071e3', '#8944ab', '#d00041', '#995900', '#217837', '#15757f', '#c4271c', '#636366'];
  function avatar(name, size) {
    const a = document.createElement('span');
    a.className = 'avatar';
    let h = 0;
    for (const ch of name || '?') h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    a.style.setProperty('--avatar', AVATAR_COLORS[h % AVATAR_COLORS.length]);
    if (size) a.style.setProperty('--avatar-size', size + 'px');
    a.textContent = ((name || '?').trim()[0] || '?').toUpperCase();
    a.setAttribute('aria-hidden', 'true');
    return a;
  }

  const EMPTY_ICONS = {
    todo: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    habit: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18"/><path d="M8 14h2"/><path d="M14 14h2"/>',
    people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14c2.2.6 3.5 2.8 3.5 6"/>',
    jobs: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    journal: '<path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="M8 9h8"/><path d="M8 13h6"/>',
  };
  // An icon, a title, one line, and at most one button.
  function emptyState(icon, title, text, actionLabel, onAction) {
    const box = document.createElement('div');
    box.className = 'empty-card';
    box.innerHTML = '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
      + 'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + (EMPTY_ICONS[icon] || EMPTY_ICONS.todo) + '</svg>';
    const t = document.createElement('div');
    t.className = 'empty-title';
    t.textContent = title;
    const p = document.createElement('div');
    p.className = 'empty-text';
    p.textContent = text;
    box.appendChild(t);
    box.appendChild(p);
    if (actionLabel) {
      const b = document.createElement('button');
      b.className = 'btn-tinted';
      b.textContent = actionLabel;
      b.onclick = onAction;
      box.appendChild(b);
    }
    return box;
  }

  // Run `mutate` (a DOM move) and glide every node in `nodes` from where it
  // was to where it ended up.
  function flipNodes(nodes, mutate) {
    const before = new Map(nodes.map(n => [n, n.getBoundingClientRect()]));
    mutate();
    if (reducedMotion()) return;
    nodes.forEach(n => {
      const was = before.get(n);
      const now = n.getBoundingClientRect();
      const dx = was.left - now.left;
      const dy = was.top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      n.animate([{transform: `translate(${dx}px, ${dy}px)`}, {transform: 'none'}],
                {duration: 220, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
    });
  }

  // − / + control for a small whole number. format(n) is the label shown.
  function stepper(value, min, max, format, onChange, label) {
    const root = document.createElement('div');
    root.className = 'stepper';
    root.setAttribute('role', 'group');
    if (label) root.setAttribute('aria-label', label);
    const minus = document.createElement('button');
    const plus = document.createElement('button');
    const text = document.createElement('span');
    text.className = 'stepper-label';
    text.setAttribute('aria-live', 'polite');
    [minus, plus].forEach(b => { b.type = 'button'; b.className = 'stepper-btn'; });
    minus.textContent = '−';
    plus.textContent = '+';
    minus.setAttribute('aria-label', 'Less');
    plus.setAttribute('aria-label', 'More');
    const paint = () => {
      text.textContent = format(value);
      minus.disabled = value <= min;
      plus.disabled = value >= max;
    };
    const step = by => () => { value = Math.max(min, Math.min(max, value + by)); paint(); onChange(value); };
    minus.onclick = step(-1);
    plus.onclick = step(1);
    root.appendChild(minus);
    root.appendChild(text);
    root.appendChild(plus);
    paint();
    return root;
  }
