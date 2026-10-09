
  const $ = id => document.getElementById(id);

  // ---------- prefs (localStorage) ----------
  // Safari private mode throws on touching localStorage at all, and a
  // full quota throws on write - this is the one place in the app where
  // swallowing the error is deliberately correct. A failed read just
  // falls back to the caller's default; a failed write is silently
  // skipped, so a pref that can't be saved never breaks the feature it
  // belongs to. Every key is namespaced so the app never collides with
  // anything else sharing this origin.
  const PREFS_PREFIX = 'mindtrail:';
  const prefs = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(PREFS_PREFIX + key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (err) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(PREFS_PREFIX + key, JSON.stringify(value));
      } catch (err) {
        // ignored - see note above
      }
    },
  };

  const log = $('log'), input = $('input'), send = $('send'), status = $('status');
  const menu = $('menu'), overlay = $('overlay');
  // Restored before the sidebar or composer ever render, so there is no
  // collapsed-then-expanded (or draft-then-empty) flash on reload.
  if (prefs.get('sidebarCollapsed', false)) $('sidebar').classList.add('collapsed');
  input.value = prefs.get('draft', '');
  let current = null;
  let currentProject = null;
  let pendingProject = null;   // project a not-yet-created chat belongs to
  let sidebar = {projects: [], unfiled: []};
  let projectsOpen = prefs.get('projectsOpen', false);
  let chatsOpen = prefs.get('chatsOpen', true);
  // {role: 'user'|'assistant', content, actions?}[] for the roadmap,
  // project, and profile chat panels - reset when their screen is
  // freshly opened (not on a background refresh), never persisted.
  let roadmapChatLog = [];
  let projectChatLog = [];
  let profileChatLog = [];
  // Roadmap canvas viewport. Module-scope because every node edit
  // re-renders the whole canvas, and losing the user's zoom/pan on each
  // accept or note would be maddening. The default here only matters
  // before a roadmap screen has actually loaded and restored (or
  // fit) its own viewport.
  let roadmapView = {zoom: 1, panX: 0, panY: 0};
  const MIN_ZOOM = 0.2, MAX_ZOOM = 2;
  const openProjects = new Set(prefs.get('openProjects', []));

  // A small fixed set rather than a free-form number input - "every 9
  // days" isn't a habit anyone actually wants, and a short list is
  // faster to pick from than typing a day count.
  const REPEAT_CHOICES = [
    {days: 0, label: 'Never'},
    {days: 1, label: 'Daily'},
    {days: 7, label: 'Weekly'},
    {days: 14, label: 'Fortnightly'},
    {days: 30, label: 'Monthly'},
  ];
  const repeatLabel = days =>
    (REPEAT_CHOICES.find(c => c.days === days) || {label: 'Every ' + days + ' days'}).label;

  // ---------- roadmap canvas selection (module scope, on purpose) ----------
  // renderRoadmap tears the whole canvas down (view.innerHTML = '') and
  // rebuilds it from scratch on every single node edit - 11 call sites,
  // including every status change. Selection state living in the DOM (a
  // class on a node element) would silently vanish on the very next
  // render. Keeping it here, outside renderRoadmap, and reapplying it at
  // the end of every render is what makes "select six, accept all"
  // actually work instead of half-working and reading as a flake.
  const selectedNodeIds = new Set();
  let selectedEdge = null; // {nodeId, depId} of the currently-selected dependency edge, or null

  // Set once per renderRoadmap call so the module-level keyboard handlers
  // below (registered a single time, not per-render) can reach whatever
  // the current render's canvas needs without re-registering a new
  // document listener - and leaking the old one - on every rebuild.
  let activeRoadmapCtx = null;
  const isRoadmapViewOpen = () => $('roadmap-view').classList.contains('open');

  // Shared by the Space-drag-to-pan tracker and the selection keyboard
  // handlers below, so neither one hijacks typing in a real field.
  const isTypingTarget = el =>
    !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);

  // ---------- topmost layer stack ----------
  // Before this, Escape was handled by N independent document-level
  // keydown listeners (the modal, the sidebar search dropdown) with a
  // third (the palette, below) about to join them - none stopped
  // propagation, so one Escape press closed every open layer at once
  // instead of just the top one. A layer registers here when it opens
  // and unregisters when it closes; the single document listener below
  // dismisses only whatever is currently on top.
  const layerStack = [];

  function pushLayer(onEscape) {
    const layer = {onEscape};
    layerStack.push(layer);
    return function popLayer() {
      const idx = layerStack.indexOf(layer);
      if (idx !== -1) layerStack.splice(idx, 1);
    };
  }

  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape' || !layerStack.length) return;
    ev.preventDefault();
    ev.stopPropagation();
    layerStack[layerStack.length - 1].onEscape();
  });

  let spaceHeld = false;
  document.addEventListener('keydown', ev => {
    if (ev.code === 'Space' && !spaceHeld && !isTypingTarget(ev.target) && isRoadmapViewOpen()) {
      spaceHeld = true;
      ev.preventDefault(); // stop the page from scrolling on Space
      if (activeRoadmapCtx) activeRoadmapCtx.scroll.style.cursor = 'grab';
    }
  });
  document.addEventListener('keyup', ev => {
    if (ev.code === 'Space') {
      spaceHeld = false;
      if (activeRoadmapCtx) activeRoadmapCtx.scroll.style.cursor = '';
    }
  });

  // Escape clears the canvas selection; Delete/Backspace removes a
  // selected edge. Both are no-ops outside the roadmap view or while
  // typing, so they can never hijack an unrelated field. Also a no-op
  // whenever a layer (modal, search dropdown, palette) is on top - that
  // Escape belongs to the layer stack above, not to the canvas
  // underneath it.
  document.addEventListener('keydown', ev => {
    if (layerStack.length) return;
    if (!isRoadmapViewOpen() || !activeRoadmapCtx || isTypingTarget(ev.target)) return;
    if (ev.key === 'Escape') {
      if (selectedNodeIds.size || selectedEdge) {
        ev.preventDefault();
        selectedNodeIds.clear();
        selectedEdge = null;
        activeRoadmapCtx.refresh();
      }
    } else if (ev.key === 'Delete' || ev.key === 'Backspace') {
      if (selectedEdge) {
        ev.preventDefault();
        activeRoadmapCtx.removeSelectedEdge();
      }
    }
  });

  // Fresh reachability check - NOT the cycle guard inside _grid_positions
  // on the server, which is cycle *tolerance* fused to column assignment
  // (it stops recursion so layout doesn't hang, but never reports whether
  // a cycle exists). This mirrors the same check api.py does server-side,
  // so a bad drag never even round-trips before the user sees why it was
  // rejected.
  function createsCycle(nodeId, dependsOn, allNodes) {
    const adjacency = {};
    allNodes.forEach(n => { adjacency[n.id] = n.depends_on || []; });
    adjacency[nodeId] = dependsOn;
    const visited = new Set(), stack = new Set();
    function visit(id) {
      if (stack.has(id)) return true;
      if (visited.has(id)) return false;
      visited.add(id); stack.add(id);
      for (const dep of (adjacency[id] || [])) {
        if (visit(dep)) return true;
      }
      stack.delete(id);
      return false;
    }
    return visit(nodeId);
  }

  const api = async (path, opts) => (await fetch(path, opts)).json();
  const jsonSend = (path, body, method) => api(path, {
    method: method || 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const setStatus = m => { status.textContent = m || ''; };

  // ---------- modal ----------

  function modal(opts) {
    return new Promise(resolve => {
      overlay.innerHTML = '';
      const box = document.createElement('div');
      box.className = 'modal';

      const h = document.createElement('h3');
      h.textContent = opts.title;
      box.appendChild(h);

      if (opts.message) {
        const p = document.createElement('p');
        p.textContent = opts.message;
        box.appendChild(p);
      }

      let field = null;
      if (opts.select) {
        // A plain <select> - natively keyboard-operable (Tab, arrows,
        // Enter) with no extra wiring, which is why this reuses the
        // modal rather than inventing a bespoke list-picker for the
        // node overflow menu's "Depends on..." action.
        field = document.createElement('select');
        opts.select.forEach(o => {
          const optEl = document.createElement('option');
          optEl.value = o.value;
          optEl.textContent = o.label;
          field.appendChild(optEl);
        });
        if (opts.value !== undefined) field.value = String(opts.value);
        box.appendChild(field);
      } else if (opts.input) {
        field = document.createElement(opts.multiline ? 'textarea' : 'input');
        if (opts.multiline) field.className = 'modal-textarea';
        else field.type = opts.inputType || 'text';
        field.value = opts.value || '';
        field.placeholder = opts.placeholder || '';
        box.appendChild(field);
      }

      const actions = document.createElement('div');
      actions.className = 'modal-actions';
      const cancel = document.createElement('button');
      cancel.className = 'btn-ghost';
      cancel.textContent = 'Cancel';
      const ok = document.createElement('button');
      ok.className = opts.danger ? 'btn-danger' : 'btn-primary';
      ok.textContent = opts.confirmLabel || 'OK';
      actions.appendChild(cancel);
      actions.appendChild(ok);
      box.appendChild(actions);

      overlay.appendChild(box);
      overlay.classList.add('open');

      // Focus trap + focus restoration: previously Tab could walk out of
      // the modal into the sidebar behind it, and closing never gave
      // focus back to whatever opened it - a keyboard user was stranded
      // wherever the browser's default focus landed. trigger is captured
      // before anything else steals focus (the field.focus() call below).
      const trigger = document.activeElement;
      let close; // assigned below; pushLayer needs the reference first
      const popLayer = pushLayer(() => close(null));

      close = result => {
        overlay.classList.remove('open');
        overlay.innerHTML = '';
        document.removeEventListener('keydown', onKey);
        popLayer();
        if (trigger && typeof trigger.focus === 'function') trigger.focus();
        resolve(result);
      };
      const submit = () => close(
        opts.select ? field.value : (opts.input ? (field.value.trim() || null) : true)
      );
      const focusable = () => Array.from(
        box.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])')
      ).filter(el => !el.disabled);
      const onKey = e => {
        // Escape is deliberately not handled here - the layer stack
        // above owns dismissal so only the topmost open layer closes.
        if (e.key === 'Tab') {
          const items = focusable();
          if (!items.length) return;
          const first = items[0], last = items[items.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
          }
        }
        // Enter submits a single-line field; a textarea needs it to
        // insert a newline instead, so only Cmd/Ctrl+Enter submits.
        else if (e.key === 'Enter' && (!opts.multiline || e.metaKey || e.ctrlKey)) {
          e.preventDefault(); submit();
        }
      };

      cancel.onclick = () => close(null);
      ok.onclick = submit;
      overlay.onclick = e => { if (e.target === overlay) close(null); };
      document.addEventListener('keydown', onKey);
      if (field) { field.focus(); if (typeof field.select === 'function') field.select(); }
      else ok.focus();
    });
  }

  // ---------- markdown ----------
  // Answers come back as markdown. Escaping happens first and the
  // converter only ever emits a fixed set of tags, so model output (which
  // includes text fetched from arbitrary web pages) cannot inject markup.

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
  }

  function inlineMarkdown(t) {
    return t
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/__([^_]+)__/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }

  const TABLE_ROW = /^\s*\|(.+)\|\s*$/;
  const TABLE_RULE = /^\s*\|?[\s:-]*-[\s:|-]*$/;

  function tableCells(line) {
    return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
               .split('|').map(c => c.trim());
  }

  function renderMarkdown(src) {
    const lines = escapeHtml(src || '').split('\n');
    let html = '', list = null;
    const closeList = () => { if (list) { html += '</' + list + '>'; list = null; } };

    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i];
      const line = raw.replace(/\s+$/, '');
      if (!line.trim()) { closeList(); continue; }

      // Comparison answers come back as pipe tables; without this they
      // render as a wall of literal pipes.
      if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
        closeList();
        const head = tableCells(line);
        html += '<table><thead><tr>' +
                head.map(c => '<th>' + inlineMarkdown(c) + '</th>').join('') +
                '</tr></thead><tbody>';
        i += 2;
        while (i < lines.length && TABLE_ROW.test(lines[i])) {
          html += '<tr>' +
                  tableCells(lines[i]).map(c => '<td>' + inlineMarkdown(c) + '</td>').join('') +
                  '</tr>';
          i++;
        }
        i--;
        html += '</tbody></table>';
        continue;
      }

      let m;
      if ((m = line.match(/^(#{1,5})\s+(.*)$/))) {
        closeList();
        const level = Math.min(m[1].length + 2, 6);
        html += '<h' + level + '>' + inlineMarkdown(m[2]) + '</h' + level + '>';
      } else if ((m = line.match(/^\s*&gt;\s?(.*)$/))) {
        closeList();
        html += '<blockquote>' + inlineMarkdown(m[1]) + '</blockquote>';
      } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
        if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
        html += '<li>' + inlineMarkdown(m[1]) + '</li>';
      } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
        html += '<li>' + inlineMarkdown(m[1]) + '</li>';
      } else {
        closeList();
        html += '<p>' + inlineMarkdown(line) + '</p>';
      }
    }
    closeList();
    return html;
  }

  function setMarkdown(el, text) {
    el.classList.remove('pending');
    el.innerHTML = renderMarkdown(text);
  }

  // ---------- toasts ----------

  const TOAST_SECONDS = 8;
  // Must match the .toast-out animation-duration in CSS - read from one
  // place so the removal timer and the animation can't drift apart.
  const TOAST_EXIT_MS = 160;

  function toast(message, opts) {
    opts = opts || {};
    const el = document.createElement('div');
    el.className = 'toast' + (opts.error ? ' err' : '');
    const msg = document.createElement('span');
    msg.className = 'msg';
    msg.textContent = message;
    el.appendChild(msg);

    let timer = null;
    // The node is removed only after the exit animation has had time to
    // play, rather than yanked out mid-fade.
    const dismiss = () => {
      if (timer) clearInterval(timer);
      el.classList.add('leaving');
      setTimeout(() => el.remove(), TOAST_EXIT_MS);
    };

    if (opts.undo) {
      // The countdown is shown rather than implied, so it is obvious how
      // long the undo actually lasts.
      let left = opts.seconds || TOAST_SECONDS;
      const btn = document.createElement('button');
      btn.className = 'undo';
      const label = () => { btn.textContent = 'Undo (' + left + ')'; };
      label();
      btn.onclick = async () => { dismiss(); await opts.undo(); };
      el.appendChild(btn);
      timer = setInterval(() => {
        left -= 1;
        if (left <= 0) dismiss(); else label();
      }, 1000);
    } else {
      timer = setTimeout(dismiss, (opts.seconds || 3) * 1000);
    }

    $('toasts').appendChild(el);
    return dismiss;
  }

  // ---------- loading placeholders ----------

  // A handful of varying widths so a stack of skeleton bars reads as
  // text of different lengths rather than a uniform, obviously-fake block.
  const SKELETON_WIDTHS = ['92%', '68%', '85%', '55%', '78%'];

  function skeletonBlock(lines) {
    const wrap = document.createElement('div');
    for (let i = 0; i < lines; i++) {
      const bar = document.createElement('div');
      bar.className = 'skeleton';
      bar.style.height = '0.85rem';
      bar.style.marginBottom = '0.6rem';
      bar.style.width = SKELETON_WIDTHS[i % SKELETON_WIDTHS.length];
      wrap.appendChild(bar);
    }
    return wrap;
  }

  // Swaps a button's label for a spinner + status text while a slow
  // request (roadmap generation) is in flight, and restores the exact
  // original label afterwards - shared so the three generate buttons
  // can't drift out of sync with each other.
  function setButtonBusy(btn, label) {
    btn.disabled = true;
    btn.innerHTML = '';
    const spin = document.createElement('span');
    spin.className = 'spinner';
    btn.appendChild(spin);
    btn.appendChild(document.createTextNode(label));
  }
  function setButtonIdle(btn, label) {
    btn.disabled = false;
    btn.textContent = label;
  }

  const askText = (title, value, placeholder) =>
    modal({title, value, placeholder, input: true});
  const askConfirm = (title, message, confirmLabel) =>
    modal({title, message, confirmLabel, danger: true});

  // ---------- memory entry edit/delete (shared by the chat view and search) ----------
  // A single bad or wrong research entry used to be permanent - the only
  // removal path was deleting the whole conversation. Both actions go
  // through /api/entry/<id>; the server re-embeds on edit (see
  // MemoryStore.update_entry) so recall never keeps matching stale text
  // while the UI shows something new.

  async function editEntry(entryId, currentSummary) {
    const text = await modal({
      title: 'Edit entry', value: currentSummary, multiline: true,
      input: true, confirmLabel: 'Save',
    });
    if (text === null) return null;
    const res = await jsonSend('/api/entry/' + entryId, {summary: text}, 'PATCH');
    if (res.error) { toast(res.error, {error: true}); return null; }
    return res;
  }

  async function deleteEntry(entryId) {
    const ok = await askConfirm('Delete entry',
      'This memory entry will be removed and will no longer come up in recall. '
      + 'This cannot be undone.', 'Delete');
    if (!ok) return false;
    const res = await api('/api/entry/' + entryId, {method: 'DELETE'});
    if (res.error) { toast(res.error, {error: true}); return false; }
    toast('Entry deleted');
    return true;
  }

