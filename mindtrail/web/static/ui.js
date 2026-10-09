
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
