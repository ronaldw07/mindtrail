
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
  // typing, so they can never hijack an unrelated field.
  document.addEventListener('keydown', ev => {
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

      const close = result => {
        overlay.classList.remove('open');
        overlay.innerHTML = '';
        document.removeEventListener('keydown', onKey);
        resolve(result);
      };
      const submit = () => close(
        opts.select ? field.value : (opts.input ? (field.value.trim() || null) : true)
      );
      const onKey = e => {
        if (e.key === 'Escape') { e.preventDefault(); close(null); }
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

  // ---------- sidebar ----------

  async function loadSidebar() {
    sidebar = await api('/api/sidebar');
    renderTree();
  }

  // Reload the sidebar, and the project screen too when one is open -
  // it renders its own copy of names and chat rows, so it goes stale
  // otherwise.
  async function refreshViews() {
    // Independent of each other, so they run together rather than one
    // after the other — this runs after most sidebar-menu actions
    // (rename, pin, move, delete), so halving its wait speeds up all of
    // them. background: true means "do not spend an API call
    // regenerating highlights" - this refresh is a side effect of a
    // move or rename, not the user asking to see the project.
    await Promise.all([
      loadSidebar(),
      currentProject ? openProject(currentProject, {background: true}) : null
    ]);
  }

  function sectionRow(label, opts) {
    const row = document.createElement('div');
    row.className = 'section' + (opts.onClick ? ' clickable' : '');
    if (opts.caret) {
      const c = document.createElement('span');
      c.className = 'sec-caret';
      c.textContent = opts.open ? '\u25be' : '\u25b8';
      row.appendChild(c);
    }
    const l = document.createElement('span');
    l.className = 'label';
    l.textContent = label;
    row.appendChild(l);
    if (opts.onAdd) {
      const b = document.createElement('button');
      b.className = 'add';
      b.textContent = '+';
      b.title = opts.addTitle || 'Add';
      b.onclick = e => { e.stopPropagation(); opts.onAdd(); };
      row.appendChild(b);
    }
    if (opts.onClick) makeClickable(row, opts.onClick);
    return row;
  }

  // Every clickable row in the app is a plain div with an onclick and no
  // other affordance for reaching it - Tab skips over all of them, and
  // there was no keyboard equivalent for the click at all. This makes a
  // div behave like a real button: reachable by Tab, activated by
  // Enter or Space, exposed to a screen reader as a button.
  function makeClickable(el, onClick) {
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    el.onclick = onClick;
    el.addEventListener('keydown', e => {
      if (e.target !== el) return; // let a real button/input inside handle its own key
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e); }
    });
  }

  function chatRow(c) {
    const row = document.createElement('div');
    row.className = 'chat' + (c.unread ? ' unread' : '') +
                    (current && current.id === c.id ? ' active' : '');
    if (c.unread) {
      const d = document.createElement('div'); d.className = 'dot';
      row.appendChild(d);
    }
    if (c.pinned) {
      const p = document.createElement('span');
      p.className = 'pin';
      p.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M12 17v5"/>' +
        '<path d="M9 3h6l1 5 3 2-1 3H6l-1-3 3-2 1-5Z"/></svg>';
      row.appendChild(p);
    }
    const title = document.createElement('span');
    title.className = 'chat-title';
    title.textContent = c.title;
    row.appendChild(title);
    const btn = document.createElement('button');
    btn.className = 'menu-btn';
    btn.textContent = '\u22ef';
    btn.title = 'Chat options';
    btn.setAttribute('aria-label', 'Chat options');
    btn.onclick = e => { e.stopPropagation(); openChatMenu(e, c); };
    row.appendChild(btn);
    makeClickable(row, () => openConversation(c.id));
    return row;
  }

  function renderTree() {
    // Every toggle of these three (section open/closed, which projects
    // are expanded) re-renders the tree, so persisting here in one place
    // catches every mutation path instead of threading a prefs.set into
    // each individual click handler.
    prefs.set('projectsOpen', projectsOpen);
    prefs.set('chatsOpen', chatsOpen);
    prefs.set('openProjects', Array.from(openProjects));
    const tree = $('tree');
    tree.innerHTML = '';

    // Projects: click the header to open the section, then + to add one.
    tree.appendChild(sectionRow('Projects', {
      caret: true,
      open: projectsOpen,
      onAdd: projectsOpen ? createProject : null,
      addTitle: 'New project',
      onClick: () => { projectsOpen = !projectsOpen; renderTree(); }
    }));

    if (projectsOpen) {
      if (!sidebar.projects.length) {
        const hint = document.createElement('div');
        hint.className = 'empty-hint';
        hint.textContent = 'No projects yet \u2014 use + to add one.';
        tree.appendChild(hint);
      }
      sidebar.projects.forEach(p => {
        const wrap = document.createElement('div');
        wrap.className = 'project';
        const expanded = openProjects.has(p.id);

        const head = document.createElement('div');
        head.className = 'project-head';
        const caret = document.createElement('span');
        caret.className = 'caret';
        caret.textContent = expanded ? '\u25be' : '\u25b8';
        head.appendChild(caret);
        const name = document.createElement('span');
        name.style.flex = '1';
        name.textContent = p.name;
        // Clicking the name opens the project screen; the caret to its
        // left is what expands the chat list inline.
        makeClickable(name, e => { e.stopPropagation(); openProject(p.id); });
        head.appendChild(name);
        const btn = document.createElement('button');
        btn.className = 'menu-btn';
        btn.textContent = '\u22ef';
        btn.title = 'Project options';
        btn.setAttribute('aria-label', 'Project options');
        btn.onclick = e => { e.stopPropagation(); openProjectMenu(e, p); };
        head.appendChild(btn);
        makeClickable(head, () => {
          expanded ? openProjects.delete(p.id) : openProjects.add(p.id);
          renderTree();
        });
        wrap.appendChild(head);

        if (expanded) {
          const kids = document.createElement('div');
          kids.className = 'nested';
          if (!p.conversations.length) {
            const empty = document.createElement('div');
            empty.className = 'empty-hint';
            empty.textContent = 'Empty \u2014 move a chat here.';
            kids.appendChild(empty);
          }
          p.conversations.forEach(c => kids.appendChild(chatRow(c)));
          wrap.appendChild(kids);
        }
        tree.appendChild(wrap);
      });
    }

    // Chats: click the header to minimize the list, + starts a new one.
    tree.appendChild(sectionRow('Chats', {
      caret: true,
      open: chatsOpen,
      onAdd: newChat,
      addTitle: 'New chat',
      onClick: () => { chatsOpen = !chatsOpen; renderTree(); }
    }));
    if (chatsOpen) {
      sidebar.unfiled.forEach(c => tree.appendChild(chatRow(c)));
    }
  }

  async function createProject() {
    const name = await askText('New project', '', 'e.g. Career');
    if (!name) return;
    const res = await jsonSend('/api/projects', {name});
    if (res.error) { toast(res.error, {error: true}); return; }
    projectsOpen = true;
    openProjects.add(res.id);
    await loadSidebar();
    toast('Created project "' + res.name + '"');
  }

  // ---------- context menus ----------

  function showMenu(e, items) {
    menu.innerHTML = '';
    items.forEach(it => {
      if (it.divider) { menu.appendChild(document.createElement('hr')); return; }
      const d = document.createElement('div');
      d.textContent = it.label;
      if (it.danger) d.className = 'danger';
      // makeClickable, not a raw onclick - the established pattern for a
      // keyboard-activatable non-button row, so a menu opened from a
      // keyboard-reachable trigger (the "..." button) stays reachable
      // once it's open too.
      makeClickable(d, async () => { menu.style.display = 'none'; await it.run(); });
      menu.appendChild(d);
    });
    menu.style.display = 'block';
    menu.style.left = Math.min(e.clientX, window.innerWidth - 190) + 'px';
    menu.style.top = Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 10) + 'px';
  }

  document.addEventListener('click', e => {
    if (!menu.contains(e.target)) menu.style.display = 'none';
  });

  function openChatMenu(e, c) {
    const items = [
      {label: 'Rename', run: async () => {
        const t = await askText('Rename chat', c.title);
        if (!t) return;
        await jsonSend('/api/conversations/' + c.id, {title: t}, 'PATCH');
        if (current && current.id === c.id) { current.title = t; setBreadcrumb(); }
        await refreshViews();
        toast('Renamed to "' + t + '"', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {title: c.title}, 'PATCH');
          if (current && current.id === c.id) { current.title = c.title; setBreadcrumb(); }
          await refreshViews();
          toast('Rename undone');
        }});
      }},
      {label: c.pinned ? 'Unpin' : 'Pin', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {pinned: !c.pinned}, 'PATCH');
        await refreshViews();
        toast(c.pinned ? 'Unpinned' : 'Pinned', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {pinned: c.pinned}, 'PATCH');
          await refreshViews();
          toast('Reverted');
        }});
      }},
      {label: c.unread ? 'Mark as read' : 'Mark as unread', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {unread: !c.unread}, 'PATCH');
        await refreshViews();
        toast(c.unread ? 'Marked as read' : 'Marked as unread', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {unread: c.unread}, 'PATCH');
          await refreshViews();
          toast('Reverted');
        }});
      }},
      {divider: true}
    ];

    sidebar.projects.filter(p => p.id !== c.project_id).forEach(p => {
      items.push({label: 'Move to ' + p.name, run: async () => {
        const previous = c.project_id;
        await jsonSend('/api/conversations/' + c.id, {project_id: p.id}, 'PATCH');
        projectsOpen = true; openProjects.add(p.id);
        if (current && current.id === c.id) { current.project_id = p.id; }
        await refreshViews();
        setBreadcrumb();
        toast('Moved to ' + p.name, {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {project_id: previous}, 'PATCH');
          if (current && current.id === c.id) { current.project_id = previous; }
          await refreshViews();
          setBreadcrumb();
          toast('Move undone');
        }});
      }});
    });
    if (c.project_id) {
      items.push({label: 'Remove from project', run: async () => {
        const previous = c.project_id;
        await jsonSend('/api/conversations/' + c.id, {project_id: null}, 'PATCH');
        if (current && current.id === c.id) { current.project_id = null; }
        await refreshViews();
        setBreadcrumb();
        toast('Removed from project', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {project_id: previous}, 'PATCH');
          if (current && current.id === c.id) { current.project_id = previous; }
          await refreshViews();
          setBreadcrumb();
          toast('Move undone');
        }});
      }});
    }

    items.push({divider: true});
    items.push({label: 'Delete', danger: true, run: async () => {
      const ok = await askConfirm('Delete chat',
        '"' + c.title + '" and everything in it will be removed. This cannot be undone.',
        'Delete');
      if (!ok) return;
      const res = await api('/api/conversations/' + c.id, {method: 'DELETE'});
      if (current && current.id === c.id) newChat();
      await refreshViews();
      if (res.error) { toast(res.error, {error: true}); return; }
      toast('Deleted "' + c.title + '"', {undo: async () => {
        const back = await api('/api/undo-delete/' + c.id, {method: 'POST'});
        if (back.error) { toast(back.error, {error: true}); return; }
        await refreshViews();
        toast('Restored with ' + back.entries + ' message(s)');
      }});
    }});
    showMenu(e, items);
  }

  function openProjectMenu(e, p) {
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const n = await askText('Rename project', p.name);
        if (!n) return;
        await jsonSend('/api/projects/' + p.id, {name: n}, 'PATCH');
        await loadSidebar();
        // The project screen renders its own copy of the name, so it has
        // to be re-read or it keeps showing the old one.
        if (currentProject === p.id) await openProject(p.id, {background: true});
        else setBreadcrumb();
        toast('Project renamed to "' + n + '"', {undo: async () => {
          await jsonSend('/api/projects/' + p.id, {name: p.name}, 'PATCH');
          await loadSidebar();
          if (currentProject === p.id) await openProject(p.id, {background: true});
          toast('Rename undone');
        }});
      }},
      {divider: true},
      {label: 'Delete project', danger: true, run: async () => {
        const ok = await askConfirm('Delete project',
          'Chats inside "' + p.name + '" are kept and moved out of the project.',
          'Delete project');
        if (!ok) return;
        await api('/api/projects/' + p.id, {method: 'DELETE'});
        openProjects.delete(p.id);
        if (currentProject === p.id) newChat();
        await loadSidebar();
        setBreadcrumb();
        toast('Deleted project "' + p.name + '" \u2014 its chats were kept');
      }}
    ]);
  }

  // ---------- conversation view ----------

  function turn() {
    const d = document.createElement('div'); d.className = 'turn';
    log.appendChild(d); return d;
  }
  function userLine(c, text) {
    const row = document.createElement('div'); row.className = 'user-line';
    const s = document.createElement('span'); s.textContent = text;
    row.appendChild(s); c.appendChild(row);
  }
  function assistantText(c, text, kind, opts) {
    if (kind && kind !== 'research') {
      const t = document.createElement('div'); t.className = 'kind-tag';
      t.textContent = kind; c.appendChild(t);
    }
    const d = document.createElement('div'); d.className = 'assistant-text';
    // Uploaded documents are raw extracted text, not markdown, so they
    // are shown verbatim rather than run through the converter.
    if (opts && opts.plain) {
      d.style.whiteSpace = 'pre-wrap';
      d.textContent = text;
    } else {
      setMarkdown(d, text);
    }
    c.appendChild(d);
    return d;
  }
  function metaBlock(c, recalled, sources) {
    if (!(recalled || []).length && !(sources || []).length) return;
    const m = document.createElement('div'); m.className = 'meta';
    if ((recalled || []).length) {
      const label = document.createElement('div');
      label.className = 'recalled-label';
      label.textContent = 'Built on:';
      m.appendChild(label);
      const trail = document.createElement('div');
      trail.className = 'recalled-trail';
      recalled.forEach(r => {
        const chip = document.createElement('span');
        chip.className = 'recalled-chip';
        chip.textContent = r.query;
        chip.title = 'Open this chat';
        makeClickable(chip, () => { showChatView(); openConversation(r.conversation_id); });
        trail.appendChild(chip);
      });
      m.appendChild(trail);
    }
    (sources || []).forEach(u => {
      const a = document.createElement('a');
      a.href = u; a.target = '_blank'; a.rel = 'noopener'; a.textContent = u;
      m.appendChild(a);
    });
    c.appendChild(m);
  }

  function setBreadcrumb() {
    if (!current) { $('breadcrumb').textContent = 'New chat'; return; }
    const proj = sidebar.projects.find(p => p.id === current.project_id);
    $('breadcrumb').innerHTML = '';
    if (proj) {
      $('breadcrumb').appendChild(document.createTextNode(proj.name + ' / '));
    }
    const b = document.createElement('b');
    b.textContent = current.title;
    $('breadcrumb').appendChild(b);
  }

  function showEmptyState() {
    log.innerHTML = '';
    const d = document.createElement('div');
    d.className = 'empty-state';
    d.textContent = 'Ask anything. Answers are researched, sourced, and remembered.';
    log.appendChild(d);
  }

  // ---------- navigation history ----------
  // Tracks which conversations have been viewed, so back/forward move
  // through them the way browser history would. `replaying` suppresses
  // recording while moving through the stack, which would otherwise
  // append every step back onto the end.

  let navStack = [null];
  let navPos = 0;
  let replaying = false;

  function recordVisit(id) {
    if (replaying) return;
    if (navStack[navPos] === id) return;
    navStack = navStack.slice(0, navPos + 1);
    navStack.push(id);
    navPos = navStack.length - 1;
    updateNav();
  }

  function updateNav() {
    $('nav-back').disabled = navPos <= 0;
    $('nav-fwd').disabled = navPos >= navStack.length - 1;
  }

  async function goTo(pos) {
    if (pos < 0 || pos >= navStack.length) return;
    navPos = pos;
    replaying = true;
    const id = navStack[navPos];
    if (id) await openConversation(id);
    else newChat();
    replaying = false;
    updateNav();
  }

  $('nav-back').onclick = () => goTo(navPos - 1);
  $('nav-fwd').onclick = () => goTo(navPos + 1);

  $('toggle-sidebar').onclick = () => {
    const collapsed = $('sidebar').classList.toggle('collapsed');
    prefs.set('sidebarCollapsed', collapsed);
  };

  // ---------- opening ----------

  async function openConversation(id) {
    const data = await api('/api/conversations/' + id);
    if (data.error) { setStatus(data.error); return; }
    showChatView();
    currentProject = null;
    pendingProject = null;
    current = data.conversation;
    log.innerHTML = '';
    data.entries.forEach(e => {
      const t = turn();
      userLine(t, e.query);
      assistantText(t, e.summary, e.kind, {plain: e.kind === 'document' || e.kind === 'note'});
      metaBlock(t, e.recalled, e.sources);

      const actions = document.createElement('div');
      const editBtn = document.createElement('button');
      editBtn.className = 'card-btn';
      editBtn.textContent = 'Edit';
      editBtn.onclick = async () => {
        const updated = await editEntry(e.id, e.summary);
        if (updated) await openConversation(id);
      };
      actions.appendChild(editBtn);
      const delBtn = document.createElement('button');
      delBtn.className = 'card-btn';
      delBtn.textContent = 'Delete';
      delBtn.onclick = async () => {
        if (await deleteEntry(e.id)) await openConversation(id);
      };
      actions.appendChild(delBtn);
      t.appendChild(actions);
    });
    setBreadcrumb();
    recordVisit(id);
    prefs.set('lastView', {type: 'chat', id});
    await loadSidebar();
    log.scrollTop = log.scrollHeight;
  }

  function newChat() {
    current = null;
    currentProject = null;
    pendingProject = null;
    showChatView();
    showEmptyState();
    setBreadcrumb();
    recordVisit(null);
    prefs.set('lastView', {type: 'chat', id: null});
    renderTree();
    input.focus();
  }

  // ---------- project detail ----------

  function relTime(iso) {
    if (!iso) return '';
    const secs = (Date.now() - new Date(iso).getTime()) / 1000;
    if (secs < 90) return 'just now';
    if (secs < 3600) return Math.round(secs / 60) + ' min ago';
    if (secs < 86400) return Math.round(secs / 3600) + ' hours ago';
    return Math.round(secs / 86400) + ' days ago';
  }

  function card(title, buttonLabel, onClick) {
    const c = document.createElement('div');
    c.className = 'card';
    const h = document.createElement('h4');
    h.appendChild(document.createTextNode(title));
    const sp = document.createElement('span'); sp.className = 'spacer';
    h.appendChild(sp);
    if (buttonLabel) {
      const b = document.createElement('button');
      b.className = 'card-btn';
      b.textContent = buttonLabel;
      b.onclick = onClick;
      h.appendChild(b);
    }
    c.appendChild(h);
    return c;
  }

  // A compact propose/accept chat card - same safety property as the
  // roadmap's larger canvas-side panel (the model only ever proposes;
  // nothing changes until Accept is clicked), packaged for the project
  // and profile screens where a full side panel doesn't fit. `chatLog`
  // is the caller's persistent array (survives a parent re-render since
  // it lives outside this card); `applyAction` performs one accepted
  // action's real mutation and returns whether it succeeded;
  // `afterApply` runs after a successful accept to refresh whatever the
  // action changed.
  function buildAssistantCard(title, hint, chatLog, sendMessage, applyAction, afterApply) {
    const c = card(title, null, null);
    const log = document.createElement('div');
    log.className = 'rc-log';
    c.appendChild(log);

    function renderActionCard(action) {
      const box = document.createElement('div');
      box.className = 'rc-action' + (action.resolved ? ' resolved' : '');
      const label = document.createElement('div');
      label.className = 'rc-action-label';
      label.textContent = action.label;
      box.appendChild(label);

      if (action.resolved) {
        const note = document.createElement('div');
        note.className = 'rc-action-resolved-note';
        note.textContent = action.resolved === 'accepted' ? '\u2713 Applied' : '\u2717 Dismissed';
        box.appendChild(note);
        return box;
      }

      const buttons = document.createElement('div');
      buttons.className = 'rc-action-buttons';
      const accept = document.createElement('button');
      accept.className = 'rc-accept';
      accept.textContent = 'Accept';
      accept.onclick = async () => {
        accept.disabled = true;
        const ok = await applyAction(action);
        if (!ok) { accept.disabled = false; return; }
        action.resolved = 'accepted';
        await afterApply();
      };
      buttons.appendChild(accept);
      const reject = document.createElement('button');
      reject.className = 'rc-reject';
      reject.textContent = 'Dismiss';
      reject.onclick = () => { action.resolved = 'rejected'; renderLog(); };
      buttons.appendChild(reject);
      box.appendChild(buttons);
      return box;
    }

    function renderLog() {
      log.innerHTML = '';
      if (!chatLog.length) {
        const hintEl = document.createElement('div');
        hintEl.className = 'muted';
        hintEl.textContent = hint;
        log.appendChild(hintEl);
      }
      chatLog.forEach(entry => {
        const msg = document.createElement('div');
        msg.className = 'rc-msg ' + entry.role;
        msg.textContent = entry.content;
        log.appendChild(msg);
        (entry.actions || []).forEach(a => log.appendChild(renderActionCard(a)));
      });
      log.scrollTop = log.scrollHeight;
    }
    renderLog();

    const form = document.createElement('form');
    form.className = 'rc-form';
    const input = document.createElement('input');
    input.className = 'rc-input';
    input.placeholder = 'Ask\u2026';
    form.appendChild(input);
    const mic = micButton();
    attachDictation(mic, input, msg => { if (msg) toast(msg, {error: msg.includes('fail')}); });
    form.appendChild(mic);
    const sendBtn = document.createElement('button');
    sendBtn.className = 'send';
    sendBtn.type = 'submit';
    sendBtn.textContent = 'Send';
    form.appendChild(sendBtn);
    form.onsubmit = async e => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      sendBtn.disabled = input.disabled = true;

      const historyForRequest = chatLog.map(m => ({role: m.role, content: m.content}));
      chatLog.push({role: 'user', content: message});
      renderLog();

      const res = await sendMessage(message, historyForRequest);
      sendBtn.disabled = input.disabled = false;
      input.focus();
      if (res.error) {
        chatLog.push({role: 'assistant', content: 'Error: ' + res.error, actions: []});
      } else {
        chatLog.push({role: 'assistant', content: res.reply, actions: res.actions || []});
      }
      renderLog();
    };
    c.appendChild(form);
    return c;
  }

  function setActiveView(name) {
    $('project-view').classList.toggle('open', name === 'project');
    $('roadmap-view').classList.toggle('open', name === 'roadmap');
    $('profile-view').classList.toggle('open', name === 'profile');
    $('dashboard-view').classList.toggle('open', name === 'dashboard');
    log.style.display = name === 'chat' ? '' : 'none';
    $('composer').style.display = name === 'chat' ? '' : 'none';
  }

  function showChatView() { setActiveView('chat'); }
  function showProjectView() { setActiveView('project'); }
  function showRoadmapView() { setActiveView('roadmap'); }
  function showProfileView() { setActiveView('profile'); }
  function showDashboardView() { setActiveView('dashboard'); }

  async function openProject(id, opts) {
    opts = opts || {};
    currentProject = id;
    current = null;
    showProjectView();

    const view = $('project-view');
    if (!opts.background) {
      view.innerHTML = '';
      view.appendChild(skeletonBlock(6));
      $('breadcrumb').textContent = 'Projects';
      // A background refresh (e.g. after the chat assistant renames the
      // project) must not wipe the chat history it's about to redraw.
      projectChatLog = [];
    }

    // Opening a project must never block on a model call - background=1
    // always skips highlight generation here, regardless of opts.background
    // (which only controls the loading placeholder below). Stale or
    // missing highlights show as-is with a note; the Refresh button, not
    // navigation, is what pays the LLM round trip.
    const params = ['background=1'];
    if (opts.refresh) params.push('refresh=1');
    // Both requests are independent, so they're fired together instead of
    // one after the other — the roadmap fetch below just reads a promise
    // that has usually already resolved by the time it's needed.
    const dataPromise = api('/api/projects/' + id +
                            (params.length ? '?' + params.join('&') : ''));
    const rmDataPromise = api('/api/roadmap/' + id);
    const data = await dataPromise;
    if (data.error) { view.innerHTML = ''; setStatus(data.error); return; }
    // Only a real navigation (not a background refresh after a rename or
    // move elsewhere) should overwrite what reload restores to.
    if (!opts.background) prefs.set('lastView', {type: 'project', id});

    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode('Projects / '));
    const b = document.createElement('b');
    b.textContent = data.name;
    $('breadcrumb').appendChild(b);

    view.innerHTML = '';
    const layout = document.createElement('div');
    layout.className = 'proj-layout';

    // --- left: title, new chat, conversations ---
    const main = document.createElement('div');
    main.className = 'proj-main';
    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = data.name;
    main.appendChild(title);

    const startCard = card('Start a chat in this project', null, null);
    const startBtn = document.createElement('button');
    startBtn.className = 'send';
    startBtn.textContent = '+ New chat here';
    startBtn.onclick = () => newChatInProject(id, data.name);
    startCard.appendChild(startBtn);
    main.appendChild(startCard);

    const chatsCard = card('Chats', null, null);
    if (!data.conversations.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No chats yet. Start one above, or move an existing chat here.';
      chatsCard.appendChild(p);
    }
    data.conversations.forEach(c => {
      const row = document.createElement('div');
      row.className = 'proj-chat';
      const t = document.createElement('span');
      t.style.flex = '1';
      if (c.pinned) {
        const pin = document.createElement('span');
        pin.className = 'pin';
        pin.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
          'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
          'stroke-linejoin="round"><path d="M12 17v5"/>' +
          '<path d="M9 3h6l1 5 3 2-1 3H6l-1-3 3-2 1-5Z"/></svg>';
        t.appendChild(pin);
      }
      t.appendChild(document.createTextNode(c.title));
      row.appendChild(t);
      const w = document.createElement('span');
      w.className = 'when';
      w.textContent = relTime(c.updated_at);
      row.appendChild(w);
      makeClickable(row, () => { showChatView(); openConversation(c.id); });
      chatsCard.appendChild(row);
    });
    main.appendChild(chatsCard);
    layout.appendChild(main);

    // --- right rail: highlights, instructions, files ---
    const rail = document.createElement('div');
    rail.className = 'proj-rail';

    // Refresh replaces only this panel's contents, so the rest of the
    // project screen does not flash while one card reloads.
    const hlCard = card('What\u2019s next', '\u21bb Refresh', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = '\u21bb Refreshing\u2026';
      const fresh = await api('/api/projects/' + id + '?refresh=1');
      btn.disabled = false;
      btn.textContent = '\u21bb Refresh';
      if (fresh.error) { toast(fresh.error, {error: true}); return; }
      fillHighlights(hlCard, fresh, id);
      toast(fresh.highlights_error
        ? 'Could not refresh: ' + fresh.highlights_error
        : 'Suggestions updated', {error: !!fresh.highlights_error});
    });
    fillHighlights(hlCard, data, id);
    rail.appendChild(hlCard);

    const roadmapCard = card('Roadmap', null, null);
    const rmData = await rmDataPromise;
    if (!rmData.roadmap) {
      const goalInput = document.createElement('input');
      goalInput.placeholder = 'What are you working toward?';
      goalInput.style.cssText = 'width:100%;padding:0.5rem 0.65rem;border-radius:8px;' +
        'border:1px solid #333;background:#191919;color:#ececec;font-size:0.85rem;' +
        'margin:0.5rem 0;';
      roadmapCard.appendChild(goalInput);
      const genBtn = document.createElement('button');
      genBtn.className = 'send';
      genBtn.textContent = 'Generate roadmap';
      genBtn.onclick = async () => {
        const goal = goalInput.value.trim();
        if (!goal) { toast('Enter a goal first', {error: true}); return; }
        setButtonBusy(genBtn, 'Generating\u2026');
        const res = await jsonSend('/api/roadmap/' + id + '/generate', {goal});
        setButtonIdle(genBtn, 'Generate roadmap');
        if (res.error) { toast(res.error, {error: true}); return; }
        openRoadmapView(id, data.name);
      };
      roadmapCard.appendChild(genBtn);
    } else {
      const summary = document.createElement('div');
      summary.className = 'muted';
      summary.textContent = rmData.roadmap.goal;
      roadmapCard.appendChild(summary);
      const openBtn = document.createElement('button');
      openBtn.className = 'send';
      openBtn.style.marginTop = '0.5rem';
      openBtn.textContent = 'Open roadmap';
      openBtn.onclick = () => openRoadmapView(id, data.name);
      roadmapCard.appendChild(openBtn);
    }
    rail.appendChild(roadmapCard);

    const instrCard = card('Instructions', null, null);
    const box = document.createElement('textarea');
    box.className = 'instructions-box';
    box.value = data.instructions || '';
    box.placeholder = 'Guidance applied to every answer in this project.';
    instrCard.appendChild(box);

    const saveRow = document.createElement('div');
    saveRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;margin-top:0.6rem;';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'send';
    saveBtn.textContent = 'Save instructions';
    saveBtn.disabled = true;
    const dirtyNote = document.createElement('span');
    dirtyNote.className = 'muted';
    saveRow.appendChild(saveBtn);
    saveRow.appendChild(dirtyNote);
    instrCard.appendChild(saveRow);

    // The button only lights up when there is something to save, so it
    // is obvious whether the current text is applied or not.
    const original = box.value;
    box.oninput = () => {
      const changed = box.value !== original;
      saveBtn.disabled = !changed;
      dirtyNote.textContent = changed ? 'Unsaved changes' : '';
    };
    saveBtn.onclick = async () => {
      const res = await jsonSend('/api/projects/' + id, {instructions: box.value}, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return; }
      saveBtn.disabled = true;
      dirtyNote.textContent = '';
      toast('Instructions saved', {undo: async () => {
        await jsonSend('/api/projects/' + id, {instructions: original}, 'PATCH');
        box.value = original;
        toast('Instructions reverted');
      }});
    };
    rail.appendChild(instrCard);

    const filesCard = card('Files', '+ Upload', () => uploadInto(id));
    if (!data.files.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No documents yet.';
      filesCard.appendChild(p);
    }
    data.files.forEach(f => {
      const chip = document.createElement('span');
      chip.className = 'file-chip';
      chip.textContent = f.name;
      makeClickable(chip, () => { showChatView(); openConversation(f.conversation_id); });
      filesCard.appendChild(chip);
    });
    rail.appendChild(filesCard);

    const assistantCard = buildAssistantCard(
      'Project Assistant',
      'Ask about this project, or tell it what to change \u2014 it can ' +
      'propose renaming it or updating its instructions.',
      projectChatLog,
      (message, history) => jsonSend('/api/projects/' + id + '/chat', {message, history}),
      async action => {
        const patch = {};
        if (action.name !== null) patch.name = action.name;
        if (action.instructions !== null) patch.instructions = action.instructions;
        const res = await jsonSend('/api/projects/' + id, patch, 'PATCH');
        if (res.error) { toast(res.error, {error: true}); return false; }
        return true;
      },
      () => refreshViews()
    );
    rail.appendChild(assistantCard);

    layout.appendChild(rail);
    view.appendChild(layout);
  }

  // Rebuilds only the body of the What's next card, leaving its header
  // (and the Refresh button being clicked) in place.
  function fillHighlights(cardEl, data, projectId) {
    cardEl.querySelectorAll(':scope > *:not(h4)').forEach(n => n.remove());

    if (data.highlights_error) {
      const e = document.createElement('div');
      e.className = 'muted';
      e.textContent = 'Could not refresh \u2014 ' + data.highlights_error +
                      '. Showing the previous suggestions.';
      cardEl.appendChild(e);
    }
    // Loading a project never generates automatically now, so an
    // entry_count > 0 project with zero highlights just hasn't had
    // Refresh clicked yet - distinct from one with nothing to work from.
    if (!data.highlights.length && !data.highlights_error) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = data.entry_count
        ? 'Not generated yet \u2014 hit Refresh to see suggestions.'
        : 'Add chats or a document, and suggestions appear here.';
      cardEl.appendChild(p);
    }
    if (data.highlights_stale && data.highlights.length && !data.highlights_error) {
      const note = document.createElement('div');
      note.className = 'stale-note';
      note.textContent = 'New activity since these \u2014 hit Refresh to update.';
      cardEl.appendChild(note);
    }

    data.highlights.forEach(h => {
      const tier = h.priority || 'next';
      const item = document.createElement('div');
      item.className = 'hl ' + tier;
      item.title = 'Click to expand';

      const head = document.createElement('div');
      head.className = 'hl-head';
      const badge = document.createElement('span');
      badge.className = 'tier ' + tier;
      badge.textContent = tier === 'now' ? 'Do now' : tier;
      head.appendChild(badge);
      head.appendChild(document.createTextNode(h.headline));
      item.appendChild(head);

      if (h.detail) {
        const d = document.createElement('div');
        d.className = 'hl-detail';
        d.textContent = h.detail;
        item.appendChild(d);
      }
      if (h.source) {
        const s = document.createElement('div');
        s.className = 'hl-source';
        // The prompt labels entries "[RESEARCH] ..." so the model can tell
        // documents from chats; that tag is internal and reads as noise here.
        s.textContent = 'from: ' + h.source.replace(/^\[[A-Z]+\]\s*/, '');
        item.appendChild(s);
      }
      makeClickable(item, () => expandHighlight(h, data.name));
      cardEl.appendChild(item);
    });

    if (data.highlights_generated_at && data.highlights.length) {
      const stamp = document.createElement('div');
      stamp.className = 'stamp';
      stamp.textContent = 'Updated ' + relTime(data.highlights_generated_at) +
                          ' \u00b7 based on ' + data.entry_count + ' item(s)';
      cardEl.appendChild(stamp);
    }
  }

  function expandHighlight(h, projectName) {
    const tier = h.priority || 'next';
    const parts = [];
    if (h.detail) parts.push(h.detail);
    if (h.source) {
      parts.push('Based on: ' + h.source.replace(/^\[[A-Z]+\]\s*/, ''));
    }
    parts.push('Project: ' + projectName);
    modal({
      title: (tier === 'now' ? '\u2605  ' : '') + h.headline,
      message: parts.join('\n\n'),
      confirmLabel: 'Ask about this'
    }).then(async ok => {
      if (!ok) return;
      // Turning a highlight into a question is the natural next move, so
      // it drops straight into the composer inside this project.
      newChatInProject(currentProject, projectName);
      input.value = h.headline;
      input.focus();
    });
  }

  function newChatInProject(projectId, projectName) {
    showChatView();
    current = null;
    pendingProject = {id: projectId, name: projectName};
    showEmptyState();
    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode(projectName + ' / '));
    const b = document.createElement('b');
    b.textContent = 'New chat';
    $('breadcrumb').appendChild(b);
    input.focus();
  }

  // ---------- roadmap ----------

  async function openRoadmapView(projectId, projectName) {
    currentProject = projectId;
    current = null;
    roadmapChatLog = [];
    roadmapView = {zoom: 1, panX: 0, panY: 0};
    showRoadmapView();
    prefs.set('lastView', {type: 'roadmap', id: projectId});
    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode(projectName + ' / '));
    const b = document.createElement('b');
    b.textContent = 'Roadmap';
    $('breadcrumb').appendChild(b);

    const view = $('roadmap-view');
    view.innerHTML = '';
    const loading = skeletonBlock(4);
    loading.style.padding = '1.5rem';
    view.appendChild(loading);

    // Fired together rather than one after the other, same as the
    // project/roadmap pair in openProject - the template list is only
    // needed if there turns out to be no roadmap yet, but there's no
    // reason to wait for the roadmap fetch to finish before starting it.
    // A failed or slow template fetch must never block rendering an
    // existing roadmap, so its rejection is swallowed here rather than
    // left for the empty-state branch to deal with.
    const dataPromise = api('/api/roadmap/' + projectId);
    const templatesPromise = api('/api/roadmap-templates').catch(() => null);
    const data = await dataPromise;
    if (!data.roadmap) {
      view.innerHTML = '';
      const empty = document.createElement('div');
      empty.id = 'roadmap-empty';
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No roadmap yet for this project. What are you working toward?';
      empty.appendChild(p);

      const goalInput = document.createElement('input');
      goalInput.placeholder = 'What are you working toward?';
      empty.appendChild(goalInput);

      const genBtn = document.createElement('button');
      genBtn.className = 'send';
      genBtn.textContent = 'Generate roadmap';
      genBtn.onclick = async () => {
        const goal = goalInput.value.trim();
        if (!goal) { toast('Enter a goal first', {error: true}); return; }
        setButtonBusy(genBtn, 'Generating\u2026');
        const res = await jsonSend('/api/roadmap/' + projectId + '/generate', {goal});
        setButtonIdle(genBtn, 'Generate roadmap');
        if (res.error) { toast(res.error, {error: true}); return; }
        renderRoadmap(projectId, projectName, res.roadmap, res.nodes, {fitView: true});
      };
      empty.appendChild(genBtn);

      const back = document.createElement('button');
      back.className = 'card-btn';
      back.style.marginLeft = '0.5rem';
      back.textContent = 'Back to project';
      back.onclick = () => openProject(projectId);
      empty.appendChild(back);

      view.appendChild(empty);

      const templatesRes = await templatesPromise;
      const templates = templatesRes && Array.isArray(templatesRes.templates)
        ? templatesRes.templates : [];
      // A missing template list is a missing optional affordance, not an
      // error worth a toast - the goal input and Generate button above
      // still work fine without it.
      if (templates.length) appendTemplatePicker(empty, templates, projectId, projectName, goalInput);
      return;
    }
    // Opening an existing roadmap: a saved viewport beats fitting to
    // content, so the user lands back where they left it panned/zoomed
    // instead of being re-centred on every visit. (Tidy and regenerate
    // deliberately skip this and always fit - the layout just changed
    // under the user, so their old viewport no longer means anything.)
    const savedView = prefs.get('roadmapView:' + data.roadmap.id, null);
    if (savedView) {
      roadmapView = savedView;
      renderRoadmap(projectId, projectName, data.roadmap, data.nodes);
    } else {
      renderRoadmap(projectId, projectName, data.roadmap, data.nodes, {fitView: true});
    }
  }

  // Fills in a template's name/description/step-count on a card - split
  // out so a failed apply can rebuild the same content after wiping it
  // for the busy spinner via setButtonBusy.
  function fillTemplateCard(card, t) {
    const name = document.createElement('div');
    name.className = 'template-card-name';
    name.textContent = t.name;
    card.appendChild(name);

    const desc = document.createElement('div');
    desc.className = 'template-card-desc';
    desc.textContent = t.description;
    card.appendChild(desc);

    const count = document.createElement('div');
    count.className = 'template-card-count';
    count.textContent = t.step_count + (t.step_count === 1 ? ' step' : ' steps');
    card.appendChild(count);
  }

  function appendTemplatePicker(empty, templates, projectId, projectName, goalInput) {
    const divider = document.createElement('div');
    divider.className = 'muted template-divider';
    divider.textContent = 'or start from a template';
    empty.appendChild(divider);

    const list = document.createElement('div');
    list.className = 'template-list';
    empty.appendChild(list);

    templates.forEach(t => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'template-card';
      fillTemplateCard(card, t);

      card.onclick = async () => {
        // One card in flight must block every other card too, so a
        // double-click (or a click on a neighbor while the first request
        // is still out) can't apply two templates at once.
        const cards = Array.from(list.querySelectorAll('.template-card'));
        cards.forEach(c => { c.disabled = true; });
        setButtonBusy(card, 'Applying\u2026');

        const goal = goalInput.value.trim();
        const res = await jsonSend('/api/roadmap/' + projectId + '/template',
                                    {template_id: t.id, goal});
        if (res.error) {
          toast(res.error, {error: true});
          cards.forEach(c => { c.disabled = false; });
          setButtonIdle(card, '');
          fillTemplateCard(card, t);
          return;
        }
        renderRoadmap(projectId, projectName, res.roadmap, res.nodes, {fitView: true});
      };
      list.appendChild(card);
    });
  }

  function renderRoadmap(projectId, projectName, roadmap, nodesList, opts) {
    opts = opts || {};
    const view = $('roadmap-view');
    view.innerHTML = '';

    const top = document.createElement('div');
    top.id = 'roadmap-top';
    const goalEl = document.createElement('div');
    goalEl.className = 'goal';
    goalEl.textContent = roadmap.goal;
    top.appendChild(goalEl);

    const addBtn = document.createElement('button');
    addBtn.className = 'card-btn';
    addBtn.textContent = '+ Add step';
    addBtn.onclick = () => {
      // Cascades new cards so repeated adds don't stack exactly on top
      // of each other before the user drags them apart. Right-click
      // "Add step here" (below) uses the same addStepAt with the actual
      // click point instead of this cascade.
      const offset = (nodesList.length % 6) * 40;
      addStepAt(40 + offset, 40 + offset);
    };
    top.appendChild(addBtn);

    const tidyBtn = document.createElement('button');
    tidyBtn.className = 'card-btn';
    tidyBtn.textContent = 'Tidy up';
    tidyBtn.title = 'Re-space every step into a clean grid';
    tidyBtn.onclick = async () => {
      tidyBtn.disabled = true;
      const res = await jsonSend('/api/roadmap-node/' + roadmap.id + '/tidy', {});
      tidyBtn.disabled = false;
      if (res.error) { toast(res.error, {error: true}); return; }
      renderRoadmap(projectId, projectName, roadmap, res.nodes, {fitView: true});
    };
    top.appendChild(tidyBtn);

    const regenBtn = document.createElement('button');
    regenBtn.className = 'card-btn';
    regenBtn.textContent = '\u21bb Regenerate';
    regenBtn.onclick = async () => {
      setButtonBusy(regenBtn, 'Regenerating\u2026');
      const res = await jsonSend('/api/roadmap/' + projectId + '/generate', {goal: roadmap.goal});
      setButtonIdle(regenBtn, '\u21bb Regenerate');
      if (res.error) { toast(res.error, {error: true}); return; }
      renderRoadmap(projectId, projectName, res.roadmap, res.nodes, {fitView: true});
    };
    top.appendChild(regenBtn);

    const backBtn = document.createElement('button');
    backBtn.className = 'card-btn';
    backBtn.textContent = 'Back';
    backBtn.onclick = () => openProject(projectId);
    top.appendChild(backBtn);

    view.appendChild(top);

    const body = document.createElement('div');
    body.id = 'roadmap-body';

    const scroll = document.createElement('div');
    scroll.id = 'canvas-scroll';
    const canvas = document.createElement('div');
    canvas.id = 'canvas';
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    canvas.appendChild(svg);
    scroll.appendChild(canvas);
    body.appendChild(scroll);
    // Attached to the live document before any node is measured -
    // offsetWidth/offsetHeight read 0 for a detached element, which
    // would silently break both edge anchoring and fit-to-view below.
    view.appendChild(body);

    const byId = {};
    nodesList.forEach(n => { byId[n.id] = n; });
    const els = {};

    function edgeAnchor(n, side) {
      const el = els[n.id];
      const w = el ? el.offsetWidth : 220;
      const h = el ? el.offsetHeight : 70;
      return side === 'out' ? {x: n.x + w, y: n.y + h / 2} : {x: n.x, y: n.y + h / 2};
    }

    // --- pan / zoom ---------------------------------------------------

    const clampZoom = z => Math.min(Math.max(z, MIN_ZOOM), MAX_ZOOM);

    function applyViewport() {
      canvas.style.transform =
        'translate(' + roadmapView.panX + 'px,' + roadmapView.panY + 'px) ' +
        'scale(' + roadmapView.zoom + ')';
      const label = $('zoom-level');
      if (label) label.textContent = Math.round(roadmapView.zoom * 100) + '%';
      // Every pan/zoom mutation (drag, wheel, zoom buttons, fit-to-view)
      // funnels through here, so this is the one place that needs to
      // persist the viewport - keyed per roadmap so different projects
      // don't clobber each other's pan/zoom.
      prefs.set('roadmapView:' + roadmap.id, roadmapView);
    }

    function contentBounds() {
      const margin = 80;
      let maxRight = 0, maxBottom = 0;
      nodesList.forEach(n => {
        const el = els[n.id];
        if (!el) return;
        maxRight = Math.max(maxRight, n.x + el.offsetWidth);
        maxBottom = Math.max(maxBottom, n.y + el.offsetHeight);
      });
      return {
        width: Math.max(maxRight + margin, 400),
        height: Math.max(maxBottom + margin, 300),
      };
    }

    // Scales so every card fits at once and centres what's there,
    // never zooming past 100% for a small roadmap.
    function fitCanvasToContent() {
      if (!nodesList.length) return;
      const {width, height} = contentBounds();
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      const zoom = clampZoom(Math.min(
        scroll.clientWidth / width, scroll.clientHeight / height, 1
      ));
      roadmapView = {
        zoom,
        panX: Math.max((scroll.clientWidth - width * zoom) / 2, 0),
        panY: Math.max((scroll.clientHeight - height * zoom) / 2, 0),
      };
      applyViewport();
    }

    // Keeps the point under the cursor fixed while the scale changes,
    // so zooming feels like it's aimed where you're looking rather than
    // at an arbitrary corner.
    function zoomAt(clientX, clientY, nextZoom) {
      const rect = scroll.getBoundingClientRect();
      const vx = clientX - rect.left, vy = clientY - rect.top;
      const zoom = clampZoom(nextZoom);
      const k = zoom / roadmapView.zoom;
      roadmapView = {
        zoom,
        panX: vx - (vx - roadmapView.panX) * k,
        panY: vy - (vy - roadmapView.panY) * k,
      };
      applyViewport();
    }

    function zoomFromCentre(nextZoom) {
      zoomAt(
        scroll.getBoundingClientRect().left + scroll.clientWidth / 2,
        scroll.getBoundingClientRect().top + scroll.clientHeight / 2,
        nextZoom
      );
    }

    // Trackpad pinch arrives as wheel + ctrlKey; a plain wheel scrolls
    // the canvas rather than the page, which is what a canvas should do.
    scroll.addEventListener('wheel', ev => {
      ev.preventDefault();
      if (ev.ctrlKey || ev.metaKey) {
        zoomAt(ev.clientX, ev.clientY, roadmapView.zoom * (1 - ev.deltaY * 0.01));
      } else {
        roadmapView.panX -= ev.deltaX;
        roadmapView.panY -= ev.deltaY;
        applyViewport();
      }
    }, {passive: false});

    // Screen (clientX/clientY) -> canvas-local pixel coordinates - the
    // exact inverse of the transform applyViewport writes onto #canvas
    // (translate(panX,panY) scale(zoom), transform-origin 0 0, with
    // #canvas positioned at the scroll container's own top-left). Needed
    // wherever a pointer event has to land at the right spot on a panned,
    // zoomed canvas: drop detection for a dragged dependency, and
    // placing a right-click-added step where the click actually was.
    function screenToCanvas(clientX, clientY) {
      const rect = scroll.getBoundingClientRect();
      return {
        x: (clientX - rect.left - roadmapView.panX) / roadmapView.zoom,
        y: (clientY - rect.top - roadmapView.panY) / roadmapView.zoom,
      };
    }

    // Figma's convention, and what people guess: a plain left-drag on
    // empty canvas marquee-selects, while Space-held or middle-button
    // drag pans. Right-click (button 2) is reserved for the context menu
    // and never starts either.
    let panning = null;
    let marquee = null;
    scroll.addEventListener('pointerdown', ev => {
      if (ev.button !== 0 && ev.button !== 1) return;
      if (ev.target.closest('#zoom-controls')) return;
      const wantsPan = ev.button === 1 || (ev.button === 0 && spaceHeld);
      if (wantsPan) {
        panning = {x: ev.clientX, y: ev.clientY,
                   panX: roadmapView.panX, panY: roadmapView.panY};
        scroll.classList.add('panning');
        scroll.setPointerCapture(ev.pointerId);
        return;
      }
      // A card or its edge-creation handle owns its own pointerdown - let
      // that handler run instead of starting a marquee under it.
      if (ev.target.closest('.node, .node-edge-handle')) return;

      const box = document.createElement('div');
      box.style.cssText = 'position:absolute;border:1px solid var(--accent);' +
        'background:color-mix(in srgb, var(--accent) 15%, transparent);' +
        'pointer-events:none;z-index:5;';
      scroll.appendChild(box);
      const additive = ev.shiftKey || ev.metaKey || ev.ctrlKey;
      marquee = {
        startClientX: ev.clientX, startClientY: ev.clientY,
        endClientX: ev.clientX, endClientY: ev.clientY,
        box, additive, baseline: additive ? new Set(selectedNodeIds) : new Set(),
      };
      scroll.setPointerCapture(ev.pointerId);
    });
    scroll.addEventListener('pointermove', ev => {
      if (panning) {
        roadmapView.panX = panning.panX + (ev.clientX - panning.x);
        roadmapView.panY = panning.panY + (ev.clientY - panning.y);
        applyViewport();
        return;
      }
      if (marquee) {
        const rect = scroll.getBoundingClientRect();
        marquee.endClientX = ev.clientX;
        marquee.endClientY = ev.clientY;
        const x1 = Math.min(marquee.startClientX, ev.clientX) - rect.left;
        const y1 = Math.min(marquee.startClientY, ev.clientY) - rect.top;
        const x2 = Math.max(marquee.startClientX, ev.clientX) - rect.left;
        const y2 = Math.max(marquee.startClientY, ev.clientY) - rect.top;
        marquee.box.style.left = x1 + 'px';
        marquee.box.style.top = y1 + 'px';
        marquee.box.style.width = (x2 - x1) + 'px';
        marquee.box.style.height = (y2 - y1) + 'px';
      }
    });
    const endPointerInteraction = () => {
      if (panning) { panning = null; scroll.classList.remove('panning'); }
      if (marquee) {
        const a = screenToCanvas(marquee.startClientX, marquee.startClientY);
        const b = screenToCanvas(marquee.endClientX, marquee.endClientY);
        const minX = Math.min(a.x, b.x), maxX = Math.max(a.x, b.x);
        const minY = Math.min(a.y, b.y), maxY = Math.max(a.y, b.y);
        const hit = nodesList.filter(n => {
          const el = els[n.id];
          const w = el ? el.offsetWidth : 220, h = el ? el.offsetHeight : 70;
          return n.x < maxX && n.x + w > minX && n.y < maxY && n.y + h > minY;
        });
        selectedNodeIds.clear();
        marquee.baseline.forEach(id => selectedNodeIds.add(id));
        hit.forEach(n => selectedNodeIds.add(n.id));
        selectedEdge = marquee.additive ? selectedEdge : null;
        marquee.box.remove();
        marquee = null;
        refreshCanvasSelection();
      }
    };
    scroll.addEventListener('pointerup', endPointerInteraction);
    scroll.addEventListener('pointercancel', endPointerInteraction);

    // Right-click "Add step here" - the keyboard-triggered equivalent is
    // the "+ Add step" toolbar button, which places at a cascading offset
    // instead of a click point that doesn't exist without a pointer.
    scroll.addEventListener('contextmenu', ev => {
      if (ev.target.closest('.node, #zoom-controls, .node-edge-handle')) return;
      ev.preventDefault();
      const at = screenToCanvas(ev.clientX, ev.clientY);
      showMenu(ev, [{label: 'Add step here', run: () => addStepAt(at.x, at.y)}]);
    });

    const zoomControls = document.createElement('div');
    zoomControls.id = 'zoom-controls';
    const zoomBtn = (label, title, onClick) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.title = title;
      b.setAttribute('aria-label', title);
      b.onclick = onClick;
      zoomControls.appendChild(b);
      return b;
    };
    zoomBtn('\u2212', 'Zoom out', () => zoomFromCentre(roadmapView.zoom / 1.2));
    const zoomLabel = document.createElement('span');
    zoomLabel.id = 'zoom-level';
    zoomControls.appendChild(zoomLabel);
    zoomBtn('+', 'Zoom in', () => zoomFromCentre(roadmapView.zoom * 1.2));
    zoomBtn('\u2922', 'Fit to view', () => fitCanvasToContent());
    scroll.appendChild(zoomControls);

    // A hidden preview line drawn from the drag handle to the cursor
    // while a dependency link is being dragged - see the handle's
    // pointerdown/move/up below. Declared once and re-appended by
    // drawEdges (which clears the whole <svg> on every call, including
    // mid-drag redraws triggered by a plain node move) rather than being
    // recreated, so a link-drag survives an unrelated redraw.
    const linkPreview = document.createElementNS(svgNS, 'path');
    linkPreview.style.cssText = 'fill:none;stroke:var(--accent);stroke-width:2px;' +
      'stroke-dasharray:4 3;display:none;';
    let linking = null;

    function drawEdges() {
      svg.innerHTML = '';
      nodesList.forEach(n => {
        if (n.status === 'rejected') return;
        (n.depends_on || []).forEach(depId => {
          const dep = byId[depId];
          if (!dep || dep.status === 'rejected') return;
          const from = edgeAnchor(dep, 'out');
          const to = edgeAnchor(n, 'in');
          const mx = (from.x + to.x) / 2;
          const d = 'M' + from.x + ',' + from.y +
            ' C' + mx + ',' + from.y + ' ' + mx + ',' + to.y + ' ' + to.x + ',' + to.y;
          const isSelected = !!selectedEdge &&
            selectedEdge.nodeId === n.id && selectedEdge.depId === depId;

          // A wide, invisible hit-target behind the thin visible line -
          // clicking a 1.5px stroke precisely is unreasonable, and the
          // path has no fill for pointer-events to catch otherwise.
          const hit = document.createElementNS(svgNS, 'path');
          hit.setAttribute('d', d);
          // #canvas svg has pointer-events:none (so the transparent parts
          // of the overlay don't block panning/marquee) - pointer-events
          // is inherited, so it has to be turned back on right here or
          // this "wide invisible click target" is unclickable.
          hit.style.cssText = 'fill:none;stroke:transparent;stroke-width:14px;' +
            'cursor:pointer;pointer-events:stroke;';
          hit.addEventListener('click', ev => {
            ev.stopPropagation();
            selectedNodeIds.clear();
            selectedEdge = {nodeId: n.id, depId};
            refreshCanvasSelection();
          });
          svg.appendChild(hit);

          const path = document.createElementNS(svgNS, 'path');
          path.setAttribute('d', d);
          if (isSelected) path.style.cssText = 'stroke:var(--accent);stroke-width:2.5px;';
          svg.appendChild(path);
        });
      });
      svg.appendChild(linkPreview);
    }

    // Optimistic: applies the change and re-renders immediately, then
    // persists in the background. On failure, rolls back and re-renders
    // again so a slow or failed request never leaves the canvas stuck
    // showing a change the server didn't actually save.
    function updateNode(n, patch) {
      const previous = {...n};
      Object.assign(n, patch);
      renderRoadmap(projectId, projectName, roadmap, nodesList);
      jsonSend('/api/roadmap-node/' + n.id, patch, 'PATCH').then(res => {
        if (res.error) {
          Object.assign(n, previous);
          renderRoadmap(projectId, projectName, roadmap, nodesList);
          toast(res.error, {error: true});
          return;
        }
        Object.assign(n, res);
      });
    }

    // Adds one step at a canvas point and renders once - shared by the
    // toolbar's "+ Add step" (a cascading offset, its keyboard-reachable
    // equivalent) and the right-click "Add step here" menu (the actual
    // click point, converted via screenToCanvas).
    async function addStepAt(x, y) {
      const title = await askText('New step', '', 'Title');
      if (!title) return;
      const node = await jsonSend('/api/roadmap-node/' + roadmap.id, {title, x, y});
      if (node.error) { toast(node.error, {error: true}); return; }
      nodesList.push(node);
      renderRoadmap(projectId, projectName, roadmap, nodesList);
    }

    function removeDependency(nodeId, depId) {
      const target = byId[nodeId];
      if (!target) return;
      selectedEdge = null;
      updateNode(target, {depends_on: (target.depends_on || []).filter(d => d !== depId)});
    }

    // Not routed through updateNode's optimistic patch-and-render: that
    // helper assigns the patch straight onto the node and re-renders
    // immediately, which works for every other field because the wire
    // shape and the display shape are the same value. linked_entries
    // is the one field where they differ - the wire payload is a bare
    // list of entry ids, but the card renders {id, query, ...} objects
    // so a chip has text to show. Applying the raw-id patch optimistically
    // would flash ids where chip labels belong, so this waits for the
    // server's resolved shape instead.
    async function setLinkedEntries(n, nextIds) {
      const res = await jsonSend('/api/roadmap-node/' + n.id, {linked_entries: nextIds}, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return; }
      Object.assign(n, res);
      renderRoadmap(projectId, projectName, roadmap, nodesList);
    }

    // Paints selectedNodeIds/selectedEdge onto whatever elements exist
    // right now - called after every render (see pruneSelection below)
    // and after every selection change that doesn't otherwise re-render.
    function refreshSelectionUI() {
      nodesList.forEach(n => {
        const el = els[n.id];
        if (!el) return;
        const isSelected = selectedNodeIds.has(n.id);
        el.style.boxShadow = isSelected ? '0 0 0 2px var(--accent)' : '';
        el.setAttribute('aria-selected', String(isSelected));
      });
      const count = selectedNodeIds.size;
      bulkBar.style.display = count >= 2 ? 'flex' : 'none';
      bulkLabel.textContent = count + ' selected';
    }
    function refreshCanvasSelection() { refreshSelectionUI(); drawEdges(); }

    // Nodes that were deleted (by this user or, via a background
    // refresh, someone/something else) can't stay selected forever.
    function pruneSelection() {
      const live = new Set(nodesList.map(n => n.id));
      Array.from(selectedNodeIds).forEach(id => { if (!live.has(id)) selectedNodeIds.delete(id); });
    }

    function selectOnly(id) {
      selectedNodeIds.clear();
      selectedNodeIds.add(id);
      selectedEdge = null;
      refreshCanvasSelection();
    }
    function toggleSelect(id) {
      if (selectedNodeIds.has(id)) selectedNodeIds.delete(id); else selectedNodeIds.add(id);
      selectedEdge = null;
      refreshCanvasSelection();
    }

    // Mutates every selected node with one patch and renders once -
    // renderRoadmap tears the whole canvas down, so six sequential
    // accepts would mean six full teardown/rebuilds. This applies all
    // six, renders once, then persists in the background exactly like
    // updateNode does for a single node, rolling back only what failed.
    function batchUpdateNodes(ids, buildPatch) {
      const targets = ids.map(id => byId[id]).filter(Boolean);
      if (!targets.length) return;
      const patches = targets.map(buildPatch);
      const previous = targets.map(n => ({...n}));
      targets.forEach((n, i) => Object.assign(n, patches[i]));
      renderRoadmap(projectId, projectName, roadmap, nodesList);
      Promise.all(targets.map((n, i) =>
        jsonSend('/api/roadmap-node/' + n.id, patches[i], 'PATCH')
      )).then(results => {
        let failed = false;
        results.forEach((res, i) => {
          if (res.error) { failed = true; Object.assign(targets[i], previous[i]); }
          else Object.assign(targets[i], res);
        });
        if (failed) {
          toast('Some updates failed', {error: true});
          renderRoadmap(projectId, projectName, roadmap, nodesList);
        }
      });
    }

    async function batchDeleteNodes(ids) {
      const targets = ids.map(id => byId[id]).filter(Boolean);
      if (!targets.length) return;
      const ok = await askConfirm('Delete steps',
        targets.length + ' step(s) will be removed.', 'Delete');
      if (!ok) return;
      targets.forEach(n => {
        const idx = nodesList.indexOf(n);
        if (idx !== -1) nodesList.splice(idx, 1);
        selectedNodeIds.delete(n.id);
      });
      renderRoadmap(projectId, projectName, roadmap, nodesList);
      const results = await Promise.all(
        targets.map(n => api('/api/roadmap-node/' + n.id, {method: 'DELETE'}))
      );
      if (results.some(r => r.error)) {
        toast('Some steps could not be deleted', {error: true});
        // Reconciling by re-fetching is simpler and more correct than
        // trying to splice the failed ones back in at their old index.
        const fresh = await api('/api/roadmap/' + projectId);
        if (fresh.roadmap) renderRoadmap(projectId, projectName, fresh.roadmap, fresh.nodes);
      }
    }

    const bulkBar = document.createElement('div');
    bulkBar.style.cssText = 'display:none;align-items:center;gap:0.5rem;' +
      'margin-left:0.75rem;padding:0.25rem 0.6rem;border-radius:8px;' +
      'border:1px solid var(--border-strong);background:var(--surface);';
    const bulkLabel = document.createElement('span');
    bulkLabel.className = 'muted';
    bulkBar.appendChild(bulkLabel);
    const bulkBtn = (label, onClick, danger) => {
      const b = document.createElement('button');
      b.className = danger ? 'btn-danger' : 'card-btn';
      b.textContent = label;
      b.onclick = onClick;
      bulkBar.appendChild(b);
      return b;
    };
    bulkBtn('Accept all', () =>
      batchUpdateNodes(Array.from(selectedNodeIds), () => ({status: 'accepted'})));
    bulkBtn('Reject all', () =>
      batchUpdateNodes(Array.from(selectedNodeIds), () => ({status: 'rejected'})));
    bulkBtn('Mark done', () =>
      batchUpdateNodes(Array.from(selectedNodeIds), () => ({status: 'done'})));
    bulkBtn('Set due date', async () => {
      const dueDate = await modal({
        title: 'Due date', input: true, inputType: 'date', confirmLabel: 'Save',
      });
      if (dueDate === null) return;
      batchUpdateNodes(Array.from(selectedNodeIds), () => ({due_date: dueDate}));
    });
    bulkBtn('Delete', () => batchDeleteNodes(Array.from(selectedNodeIds)), true);
    top.appendChild(bulkBar);

    // Read by the module-level Escape/Delete keyboard handlers declared
    // near selectedNodeIds, above - refreshed on every render so they
    // always act on the canvas that's actually on screen.
    activeRoadmapCtx = {
      scroll,
      refresh: refreshCanvasSelection,
      removeSelectedEdge: () => {
        if (selectedEdge) removeDependency(selectedEdge.nodeId, selectedEdge.depId);
      },
    };

    function nodeMenuItems(n) {
      const items = [];
      if (n.status !== 'accepted') {
        items.push({label: 'Accept', run: () => updateNode(n, {status: 'accepted'})});
      }
      if (n.status !== 'done') {
        items.push({label: 'Mark done', run: () => updateNode(n, {status: 'done'})});
      }
      if (n.status !== 'rejected') {
        items.push({label: 'Reject', run: () => updateNode(n, {status: 'rejected'})});
      }
      items.push({label: n.note ? 'Edit note' : 'Add note', run: async () => {
        const note = await askText('Note', n.note || '', 'A note for this step');
        if (note === null) return;
        updateNode(n, {note});
      }});
      items.push({label: n.due_date ? 'Change due date' : 'Set due date', run: async () => {
        const dueDate = await modal({
          title: 'Due date', input: true, inputType: 'date', value: n.due_date || '',
          confirmLabel: 'Save',
        });
        if (dueDate === null) return;
        updateNode(n, {due_date: dueDate});
      }});
      if (n.due_date) {
        items.push({label: 'Clear due date', run: () => updateNode(n, {due_date: ''})});
      }
      items.push({divider: true});
      // The keyboard-reachable path to F1's drag-to-create dependency -
      // dragging the edge handle is pointer-only by construction, so
      // this is the only way to add a dependency without a mouse.
      items.push({label: 'Depends on…', run: async () => {
        const options = nodesList.filter(
          other => other.id !== n.id && !(n.depends_on || []).includes(other.id)
        );
        if (!options.length) {
          toast('No other steps available to depend on', {error: true});
          return;
        }
        const chosen = await modal({
          title: 'Depends on', confirmLabel: 'Add dependency',
          select: options.map(o => ({value: o.id, label: o.title})),
        });
        if (!chosen) return;
        const nextDeps = (n.depends_on || []).concat([chosen]);
        if (createsCycle(n.id, nextDeps, nodesList)) {
          toast('That would create a dependency cycle', {error: true});
          return;
        }
        updateNode(n, {depends_on: nextDeps});
      }});
      (n.depends_on || []).forEach(depId => {
        const dep = byId[depId];
        items.push({label: 'Remove dependency: ' + (dep ? dep.title : depId),
          run: () => removeDependency(n.id, depId)});
      });
      items.push({divider: true});
      // F6: closes the loop between recall and planning - a step can point
      // at the memory entries it's actually built on. /api/search is
      // semantic, not fuzzy, so this is a real search box, not a filter;
      // the two-step modal (search, then pick from results) reuses modal()
      // for both steps rather than inventing a combined search-and-pick
      // component.
      items.push({label: 'Link a memory…', run: async () => {
        const query = await askText('Link a memory', '', 'Search your memory…');
        if (!query) return;
        const data = await api('/api/search?q=' + encodeURIComponent(query));
        const already = new Set((n.linked_entries || []).map(le => le.id));
        const results = (data.results || []).filter(r => !already.has(r.id));
        if (!results.length) {
          toast('No new matches for "' + query + '"', {error: true});
          return;
        }
        const chosen = await modal({
          title: 'Link a memory', confirmLabel: 'Link',
          select: results.map(r => ({value: r.id, label: r.query})),
        });
        if (!chosen) return;
        setLinkedEntries(n, Array.from(already).concat([chosen]));
      }});
      (n.linked_entries || []).forEach(le => {
        items.push({label: 'Unlink memory: ' + le.query, run: () => {
          const nextIds = (n.linked_entries || []).map(x => x.id).filter(id => id !== le.id);
          setLinkedEntries(n, nextIds);
        }});
      });
      items.push({divider: true});
      items.push({label: 'Delete', danger: true, run: async () => {
        const ok = await askConfirm('Delete step', '"' + n.title + '" will be removed.', 'Delete');
        if (!ok) return;
        const idx = nodesList.indexOf(n);
        nodesList.splice(idx, 1);
        renderRoadmap(projectId, projectName, roadmap, nodesList);
        const res = await api('/api/roadmap-node/' + n.id, {method: 'DELETE'});
        if (res.error) {
          nodesList.splice(idx, 0, n);
          renderRoadmap(projectId, projectName, roadmap, nodesList);
          toast(res.error, {error: true});
        }
      }});
      return items;
    }

    nodesList.forEach(n => {
      const el = document.createElement('div');
      el.className = 'node ' + n.status;
      el.style.left = n.x + 'px';
      el.style.top = n.y + 'px';
      // For document.elementFromPoint(...).closest('.node') during a
      // dependency drag (see the edge handle below) - the source node
      // holds pointer capture for the whole drag, so a real 'pointerover'
      // on the target never fires; this is how the drop target is found.
      el.dataset.nodeId = n.id;
      el.setAttribute('role', 'group');
      el.setAttribute('aria-label', n.title + ', ' + n.status);

      const title = document.createElement('div');
      title.className = 'node-title';
      title.textContent = n.title;
      el.appendChild(title);

      if (n.detail) {
        const d = document.createElement('div');
        d.className = 'node-detail';
        d.textContent = n.detail;
        el.appendChild(d);
      }
      if (n.note) {
        const note = document.createElement('div');
        note.className = 'node-note';
        note.textContent = n.note;
        el.appendChild(note);
      }
      if (n.due_date) {
        const due = document.createElement('div');
        const overdue = n.status !== 'done' && n.due_date < new Date().toISOString().slice(0, 10);
        due.className = 'node-due' + (overdue ? ' overdue' : '');
        due.textContent = (overdue ? '\u26a0 Overdue: ' : '\u23f1 Due ') + n.due_date;
        el.appendChild(due);
      }
      if ((n.linked_entries || []).length) {
        // Reuses .file-chip (already generic, not scoped to the Files
        // card) rather than inventing a node-specific chip style.
        const links = document.createElement('div');
        links.className = 'node-links';
        n.linked_entries.forEach(le => {
          const chip = document.createElement('span');
          chip.className = 'file-chip';
          chip.textContent = le.query;
          chip.title = 'Open this chat';
          makeClickable(chip, ev => {
            ev.stopPropagation();
            showChatView();
            openConversation(le.conversation_id);
          });
          links.appendChild(chip);
        });
        el.appendChild(links);
      }

      const actions = document.createElement('div');
      actions.className = 'node-actions';
      if (n.status === 'proposed') {
        const acc = document.createElement('button');
        acc.className = 'accept';
        acc.textContent = 'Accept';
        acc.onclick = ev => { ev.stopPropagation(); updateNode(n, {status: 'accepted'}); };
        actions.appendChild(acc);
        const rej = document.createElement('button');
        rej.className = 'reject';
        rej.textContent = 'Reject';
        rej.onclick = ev => { ev.stopPropagation(); updateNode(n, {status: 'rejected'}); };
        actions.appendChild(rej);
      }
      if (n.status === 'accepted' || n.status === 'done') {
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.className = 'node-check';
        check.checked = n.status === 'done';
        check.title = n.status === 'done' ? 'Mark not done' : 'Mark done';
        check.onclick = ev => {
          ev.stopPropagation();
          updateNode(n, {status: check.checked ? 'done' : 'accepted'});
        };
        actions.appendChild(check);
        const label = document.createElement('span');
        label.className = 'node-check-label';
        label.textContent = 'Done';
        label.onclick = ev => { ev.stopPropagation(); check.click(); };
        actions.appendChild(label);
      }
      el.appendChild(actions);

      // Pinned to the card's own corner (see .node-more), not inline
      // with accept/reject/checkbox, so it doesn't drift around
      // depending on which of those happen to be showing.
      const more = document.createElement('button');
      more.className = 'node-more';
      more.textContent = '\u22ef';
      more.title = 'More actions for this step';
      more.setAttribute('aria-label', 'More actions for this step');
      more.onclick = ev => { ev.stopPropagation(); showMenu(ev, nodeMenuItems(n)); };
      el.appendChild(more);

      // Drag from here to draw a dependency onto another node - anchored
      // at the same point edgeAnchor(n, 'out') already draws edges from,
      // vertically centred on the right edge, so it never fights
      // .node-more (pinned to the bottom-right corner instead) for the
      // pointer. Pointer-only by construction; "Depends on…" in the
      // overflow menu above is the keyboard equivalent, so it's hidden
      // from assistive tech rather than given a false accessible name.
      const handle = document.createElement('div');
      handle.className = 'node-edge-handle';
      handle.title = 'Drag to create a dependency';
      handle.setAttribute('aria-hidden', 'true');
      handle.style.cssText = 'position:absolute;top:50%;right:-6px;width:12px;height:12px;' +
        'margin-top:-6px;border-radius:50%;background:var(--accent);cursor:crosshair;' +
        'border:2px solid var(--surface);';
      handle.addEventListener('pointerdown', ev => {
        if (ev.button !== 0 || spaceHeld) return;
        ev.stopPropagation();
        ev.preventDefault();
        handle.setPointerCapture(ev.pointerId);
        linking = {sourceId: n.id, pointerId: ev.pointerId};
        linkPreview.style.display = '';
      });
      handle.addEventListener('pointermove', ev => {
        if (!linking || linking.pointerId !== ev.pointerId) return;
        const pt = screenToCanvas(ev.clientX, ev.clientY);
        const from = edgeAnchor(n, 'out');
        const mx = (from.x + pt.x) / 2;
        linkPreview.setAttribute('d',
          'M' + from.x + ',' + from.y +
          ' C' + mx + ',' + from.y + ' ' + mx + ',' + pt.y + ' ' + pt.x + ',' + pt.y);
      });
      const endLink = ev => {
        if (!linking || linking.pointerId !== ev.pointerId) return;
        const sourceNode = byId[linking.sourceId];
        linking = null;
        linkPreview.style.display = 'none';
        // The source node holds pointer capture for the whole drag, so a
        // real 'pointerover' never reaches the node underneath the
        // cursor - elementFromPoint is the only way to find the target.
        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        const targetEl = under && under.closest('.node');
        if (!targetEl || !sourceNode) return;
        const targetNode = byId[targetEl.dataset.nodeId];
        if (!targetNode || targetNode.id === sourceNode.id) return;
        const current = targetNode.depends_on || [];
        if (current.includes(sourceNode.id)) {
          toast('Already depends on "' + sourceNode.title + '"', {error: true});
          return;
        }
        const nextDeps = current.concat([sourceNode.id]);
        if (createsCycle(targetNode.id, nextDeps, nodesList)) {
          toast('That would create a dependency cycle', {error: true});
          return;
        }
        updateNode(targetNode, {depends_on: nextDeps});
      };
      handle.addEventListener('pointerup', endLink);
      handle.addEventListener('pointercancel', () => {
        linking = null;
        linkPreview.style.display = 'none';
      });
      el.appendChild(handle);

      // Pointer events (not mouse events) so dragging works with touch
      // too. A short move threshold tells a click (select) apart from a
      // drag (move) using the same pointerdown/up pair, and dragging any
      // node that's part of the current multi-selection moves the whole
      // selection together.
      const DRAG_THRESHOLD = 4;
      let dragging = null;
      el.addEventListener('pointerdown', ev => {
        // Gated to the left button - a right-click on a card used to
        // start a drag before there was any right-click menu to
        // conflict with. Space-held defers to canvas panning instead.
        if (ev.button !== 0 || spaceHeld) return;
        if (ev.target.closest('button, input, label, .node-edge-handle, .node-links')) return;
        const groupIds = (selectedNodeIds.has(n.id) && selectedNodeIds.size > 1)
          ? Array.from(selectedNodeIds) : [n.id];
        const origins = {};
        groupIds.forEach(id => {
          const gn = byId[id];
          if (gn) origins[id] = {x: gn.x, y: gn.y};
        });
        dragging = {
          startX: ev.clientX, startY: ev.clientY, moved: false,
          groupIds, origins, shiftKey: ev.shiftKey, metaKey: ev.metaKey || ev.ctrlKey,
        };
        el.setPointerCapture(ev.pointerId);
      });
      el.addEventListener('pointermove', ev => {
        if (!dragging) return;
        const dx = ev.clientX - dragging.startX, dy = ev.clientY - dragging.startY;
        if (!dragging.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
        dragging.moved = true;
        // Cursor movement is in screen pixels but the card is positioned
        // in canvas pixels, so the delta has to be divided by the zoom
        // or a zoomed-out card outruns the cursor.
        const cdx = dx / roadmapView.zoom, cdy = dy / roadmapView.zoom;
        dragging.groupIds.forEach(id => {
          const gn = byId[id], origin = dragging.origins[id];
          if (!gn || !origin) return;
          gn.x = origin.x + cdx;
          gn.y = origin.y + cdy;
          const gel = els[id];
          if (gel) { gel.style.left = gn.x + 'px'; gel.style.top = gn.y + 'px'; }
        });
        drawEdges();
      });
      const endDrag = () => {
        if (!dragging) return;
        const {moved, groupIds, shiftKey, metaKey} = dragging;
        dragging = null;
        if (!moved) {
          // A click, not a drag: select instead of persisting a move.
          if (shiftKey || metaKey) toggleSelect(n.id); else selectOnly(n.id);
          return;
        }
        if (groupIds.length > 1) {
          batchUpdateNodes(groupIds, gn => ({x: gn.x, y: gn.y}));
          return;
        }
        // The dragged position is already on screen, so this persists in
        // the background without the full-canvas re-render updateNode
        // (or the group path above) does elsewhere.
        jsonSend('/api/roadmap-node/' + n.id, {x: n.x, y: n.y}, 'PATCH').then(res => {
          if (res.error) toast(res.error, {error: true});
          else Object.assign(n, res);
        });
      };
      el.addEventListener('pointerup', endDrag);
      el.addEventListener('pointercancel', () => { dragging = null; });

      canvas.appendChild(el);
      els[n.id] = el;
    });

    drawEdges();

    // Reapply the selection that survived this teardown/rebuild (see the
    // warning above selectedNodeIds) - every node status change routes
    // through here, so this is the one place that has to catch it.
    pruneSelection();
    refreshSelectionUI();

    // ---------- roadmap chat panel ----------
    // The model only ever proposes actions here; nothing touches the
    // roadmap until the user clicks Accept on a specific one, which
    // then goes through the same node endpoints everything else on
    // the canvas uses.

    const chatPanel = document.createElement('div');
    chatPanel.id = 'roadmap-chat';
    const chatLog = document.createElement('div');
    chatLog.id = 'roadmap-chat-log';
    chatPanel.appendChild(chatLog);

    function renderActionCard(action) {
      const box = document.createElement('div');
      box.className = 'rc-action' + (action.resolved ? ' resolved' : '');
      const label = document.createElement('div');
      label.className = 'rc-action-label';
      label.textContent = action.label;
      box.appendChild(label);

      if (action.resolved) {
        const note = document.createElement('div');
        note.className = 'rc-action-resolved-note';
        note.textContent = action.resolved === 'accepted' ? '\u2713 Applied' : '\u2717 Dismissed';
        box.appendChild(note);
        return box;
      }

      const buttons = document.createElement('div');
      buttons.className = 'rc-action-buttons';
      const accept = document.createElement('button');
      accept.className = 'rc-accept';
      accept.textContent = 'Accept';
      accept.onclick = async () => {
        accept.disabled = true;
        const ok = await applyRoadmapChatAction(roadmap, nodesList, action);
        if (!ok) { accept.disabled = false; return; }
        action.resolved = 'accepted';
        renderRoadmap(projectId, projectName, roadmap, nodesList,
                      {fitView: action.type === 'tidy'});
      };
      buttons.appendChild(accept);
      const reject = document.createElement('button');
      reject.className = 'rc-reject';
      reject.textContent = 'Dismiss';
      reject.onclick = () => { action.resolved = 'rejected'; renderChatLog(); };
      buttons.appendChild(reject);
      box.appendChild(buttons);
      return box;
    }

    function renderChatLog() {
      chatLog.innerHTML = '';
      if (!roadmapChatLog.length) {
        const hint = document.createElement('div');
        hint.className = 'muted';
        hint.textContent = 'Ask about this roadmap, or tell it what changed \u2014 ' +
                           'it can propose steps, statuses, and notes for you to accept.';
        chatLog.appendChild(hint);
      }
      roadmapChatLog.forEach(entry => {
        const msg = document.createElement('div');
        msg.className = 'rc-msg ' + entry.role;
        msg.textContent = entry.content;
        chatLog.appendChild(msg);
        (entry.actions || []).forEach(action => chatLog.appendChild(renderActionCard(action)));
      });
      chatLog.scrollTop = chatLog.scrollHeight;
    }
    renderChatLog();

    const form = document.createElement('form');
    form.id = 'roadmap-chat-form';
    const chatInput = document.createElement('input');
    chatInput.id = 'roadmap-chat-input';
    chatInput.placeholder = 'Ask about this roadmap\u2026';
    form.appendChild(chatInput);
    const mic = micButton();
    attachDictation(mic, chatInput, msg => { if (msg) toast(msg, {error: msg.includes('fail')}); });
    form.appendChild(mic);
    const sendBtn = document.createElement('button');
    sendBtn.className = 'send';
    sendBtn.type = 'submit';
    sendBtn.textContent = 'Send';
    form.appendChild(sendBtn);
    form.onsubmit = async e => {
      e.preventDefault();
      const message = chatInput.value.trim();
      if (!message) return;
      chatInput.value = '';
      sendBtn.disabled = chatInput.disabled = true;

      const historyForRequest = roadmapChatLog.map(m => ({role: m.role, content: m.content}));
      roadmapChatLog.push({role: 'user', content: message});
      renderChatLog();

      const res = await jsonSend('/api/roadmap/' + roadmap.id + '/chat',
                                 {message, history: historyForRequest});
      sendBtn.disabled = chatInput.disabled = false;
      chatInput.focus();
      if (res.error) {
        roadmapChatLog.push({role: 'assistant', content: 'Error: ' + res.error, actions: []});
      } else {
        roadmapChatLog.push({role: 'assistant', content: res.reply, actions: res.actions || []});
      }
      renderChatLog();
    };
    chatPanel.appendChild(form);

    body.appendChild(chatPanel);

    // Measured after the chat panel is in place, so the available
    // width already excludes the space it takes up. Without fitView
    // (a single node edit) the canvas keeps whatever zoom and pan the
    // user had set, and only re-sizes to the new content bounds.
    if (opts.fitView) {
      fitCanvasToContent();
    } else {
      const {width, height} = contentBounds();
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      applyViewport();
    }
  }

  // Applies one accepted chat-proposed action through the same endpoints
  // the rest of the canvas uses, so a chat-driven change and a
  // hand-dragged one are indistinguishable to the server.
  async function applyRoadmapChatAction(roadmap, nodesList, action) {
    if (action.type === 'tidy') {
      const res = await api('/api/roadmap-node/' + roadmap.id + '/tidy', {method: 'POST'});
      if (res.error) { toast(res.error, {error: true}); return false; }
      nodesList.splice(0, nodesList.length, ...res.nodes);
      return true;
    }
    if (action.type === 'add_node') {
      const offset = (nodesList.length % 6) * 40;
      const node = await jsonSend('/api/roadmap-node/' + roadmap.id, {
        title: action.title, detail: action.detail, x: 40 + offset, y: 40 + offset,
      });
      if (node.error) { toast(node.error, {error: true}); return false; }
      nodesList.push(node);
      return true;
    }
    const target = nodesList.find(n => n.id === action.node_id);
    if (action.type === 'delete_node') {
      if (!target) { toast('That step no longer exists', {error: true}); return false; }
      const res = await api('/api/roadmap-node/' + action.node_id, {method: 'DELETE'});
      if (res.error) { toast(res.error, {error: true}); return false; }
      nodesList.splice(nodesList.indexOf(target), 1);
      return true;
    }
    if (!target) { toast('That step no longer exists', {error: true}); return false; }
    const patch = action.type === 'update_status'
      ? {status: action.status}
      : {note: action.note};
    const res = await jsonSend('/api/roadmap-node/' + target.id, patch, 'PATCH');
    if (res.error) { toast(res.error, {error: true}); return false; }
    Object.assign(target, res);
    return true;
  }

  // ---------- profile ----------

  async function openProfileView(opts) {
    opts = opts || {};
    currentProject = null;
    current = null;
    showProfileView();
    $('breadcrumb').textContent = 'Profile';
    // A background refresh (after the assistant saves a proposed
    // profile) must not wipe the chat history it's about to redraw, nor
    // overwrite what reload restores to.
    if (!opts.background) { profileChatLog = []; prefs.set('lastView', {type: 'profile'}); }

    const view = $('profile-view');
    view.innerHTML = '';
    view.appendChild(skeletonBlock(5));
    const data = await api('/api/profile');
    view.innerHTML = '';

    const layout = document.createElement('div');
    layout.className = 'proj-layout';
    const main = document.createElement('div');
    main.className = 'proj-main';

    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'Profile';
    main.appendChild(title);

    const aboutCard = card('About you', 'Draft from my documents', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Drafting\u2026';
      const res = await api('/api/profile/draft', {method: 'POST'});
      btn.disabled = false;
      btn.textContent = 'Draft from my documents';
      if (res.error) { toast(res.error, {error: true}); return; }
      box.value = res.draft;
      box.oninput();
      toast('Draft generated \u2014 review and save');
    });

    const box = document.createElement('textarea');
    box.value = data.content || '';
    box.placeholder = 'Tell mindtrail about yourself \u2014 role, goals, background. ' +
                      'Used to personalize answers.';
    aboutCard.appendChild(box);

    const saveRow = document.createElement('div');
    saveRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;margin-top:0.6rem;';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'send';
    saveBtn.textContent = 'Save profile';
    saveBtn.disabled = true;
    const dirtyNote = document.createElement('span');
    dirtyNote.className = 'muted';
    saveRow.appendChild(saveBtn);
    saveRow.appendChild(dirtyNote);
    aboutCard.appendChild(saveRow);

    let original = box.value;
    box.oninput = () => {
      const changed = box.value !== original;
      saveBtn.disabled = !changed;
      dirtyNote.textContent = changed ? 'Unsaved changes' : '';
    };
    saveBtn.onclick = async () => {
      const res = await jsonSend('/api/profile', {content: box.value});
      if (res.error) { toast(res.error, {error: true}); return; }
      original = box.value;
      saveBtn.disabled = true;
      dirtyNote.textContent = '';
      toast('Profile saved');
    };

    main.appendChild(aboutCard);
    layout.appendChild(main);

    const rail = document.createElement('div');
    rail.className = 'proj-rail';
    const assistantCard = buildAssistantCard(
      'Profile Assistant',
      'Talk through what to put in your profile \u2014 it can propose ' +
      'the full replacement text for you to accept.',
      profileChatLog,
      (message, history) => jsonSend('/api/profile/chat', {message, history}),
      async action => {
        const res = await jsonSend('/api/profile', {content: action.content});
        if (res.error) { toast(res.error, {error: true}); return false; }
        return true;
      },
      () => openProfileView({background: true})
    );
    rail.appendChild(assistantCard);
    layout.appendChild(rail);

    view.appendChild(layout);
  }

  $('open-profile').onclick = () => openProfileView();

  // Notes were CLI-only until now, and the CLI version stores them with
  // no conversation attached - unreachable from the browser even after
  // the fact. This always creates one, so a note shows up in the
  // sidebar exactly like a chat or a document would.
  $('add-note').onclick = async () => {
    const text = await modal({
      title: 'New note', input: true, multiline: true,
      placeholder: 'Jot something down\u2026', confirmLabel: 'Save',
    });
    if (!text) return;
    const res = await jsonSend('/api/note', {text});
    if (res.error) { toast(res.error, {error: true}); return; }
    await loadSidebar();
    showChatView();
    await openConversation(res.conversation_id);
    toast('Note saved');
  };

  // ---------- search ----------
  // Semantic search over everything stored - the app's core retrieval,
  // otherwise only reachable indirectly through a follow-up question.

  (() => {
    const input = $('search-input');
    const results = $('search-results');
    let debounceTimer = null;
    let latestQuery = '';

    function closeResults() {
      results.classList.remove('open');
      results.innerHTML = '';
    }

    function renderResults(items, query) {
      results.innerHTML = '';
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.style.padding = '0.5rem 0.6rem';
        empty.textContent = 'No matches for "' + query + '".';
        results.appendChild(empty);
        results.classList.add('open');
        return;
      }
      items.forEach(r => {
        const item = document.createElement('div');
        item.className = 'sr-item';
        const title = document.createElement('div');
        title.className = 'sr-title';
        title.textContent = r.query;
        item.appendChild(title);
        const subParts = [];
        if (r.project_name) subParts.push(r.project_name);
        else if (r.conversation_title) subParts.push(r.conversation_title);
        subParts.push(r.kind);
        subParts.push(relTime(r.created_at));
        const sub = document.createElement('div');
        sub.className = 'sr-sub';
        sub.textContent = subParts.join(' \u00b7 ');
        item.appendChild(sub);

        const actions = document.createElement('div');
        const editBtn = document.createElement('button');
        editBtn.className = 'card-btn';
        editBtn.textContent = 'Edit';
        editBtn.onclick = async ev => {
          ev.stopPropagation();
          const updated = await editEntry(r.id, r.summary);
          if (updated) { r.summary = updated.summary; title.textContent = updated.query; }
        };
        actions.appendChild(editBtn);
        const delBtn = document.createElement('button');
        delBtn.className = 'card-btn';
        delBtn.textContent = 'Delete';
        delBtn.onclick = async ev => {
          ev.stopPropagation();
          if (await deleteEntry(r.id)) item.remove();
        };
        actions.appendChild(delBtn);
        item.appendChild(actions);

        makeClickable(item, () => {
          closeResults();
          input.value = '';
          if (r.conversation_id) {
            showChatView();
            openConversation(r.conversation_id);
          }
        });
        results.appendChild(item);
      });
      results.classList.add('open');
    }

    input.addEventListener('input', () => {
      const query = input.value.trim();
      clearTimeout(debounceTimer);
      if (!query) { closeResults(); return; }
      debounceTimer = setTimeout(async () => {
        latestQuery = query;
        const data = await api('/api/search?q=' + encodeURIComponent(query));
        // A slower earlier request resolving after a newer one must not
        // clobber what's already on screen.
        if (query !== latestQuery) return;
        renderResults(data.results || [], query);
      }, 250);
    });

    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.blur(); closeResults(); }
    });

    document.addEventListener('click', e => {
      if (!e.target.closest('#search-box')) closeResults();
    });
  })();

  // ---------- dashboard ----------

  function dashItem(titleText, subText, onClick) {
    const item = document.createElement('div');
    item.className = 'dash-item';
    const t = document.createElement('div');
    t.className = 'dash-item-title';
    t.textContent = titleText;
    item.appendChild(t);
    if (subText) {
      const s = document.createElement('div');
      s.className = 'dash-item-sub';
      s.textContent = subText;
      item.appendChild(s);
    }
    makeClickable(item, onClick);
    return item;
  }

  async function openDashboardView() {
    currentProject = null;
    current = null;
    showDashboardView();
    prefs.set('lastView', {type: 'dashboard'});
    $('breadcrumb').textContent = 'Today';

    const view = $('dashboard-view');
    view.innerHTML = '';
    view.appendChild(skeletonBlock(6));
    const data = await api('/api/dashboard');
    view.innerHTML = '';

    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'Today';
    view.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'dash-grid';

    // Next up leads - accepted roadmap steps are the most actionable
    // thing on this screen, so they get first position, not third.
    const nextCard = card('Next up', null, null);
    if (!data.next_up.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No accepted roadmap steps waiting yet.';
      nextCard.appendChild(p);
    }
    data.next_up.forEach(n => {
      let sub = n.project_name + (n.due_date ? ' \u00b7 due ' + n.due_date : '') +
                (n.note ? ' \u2014 ' + n.note : '');
      if (!n.unblocked) sub += ' \u00b7 waiting on a dependency';
      const item = dashItem(n.title, sub, () => openRoadmapView(n.project_id, n.project_name));
      if (!n.unblocked) item.style.opacity = '0.7';
      nextCard.appendChild(item);
    });
    grid.appendChild(nextCard);

    const hlCard = card('Across your projects', null, null);
    if (!data.highlights.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing yet \u2014 project highlights show up here.';
      hlCard.appendChild(p);
    }
    data.highlights.forEach(h => {
      hlCard.appendChild(dashItem(h.headline, h.project_name,
                                  () => openProject(h.project_id)));
    });
    grid.appendChild(hlCard);

    // Due this week - across every project, not just the one open right
    // now. Bucketing (overdue/today/this_week/later) and the "today"
    // boundary itself are computed server-side in handle_dashboard; see
    // the comment there for why local time, not UTC, is what decides
    // the boundary.
    const agendaCard = card('Due this week', null, null);
    const AGENDA_BUCKETS = [
      {key: 'overdue', label: 'Overdue'},
      {key: 'today', label: 'Today'},
      {key: 'this_week', label: 'This week'},
      {key: 'later', label: 'Later'},
    ];
    const agenda = data.agenda || {};
    const agendaIsEmpty = AGENDA_BUCKETS.every(b => !(agenda[b.key] || []).length);
    if (agendaIsEmpty) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing due.';
      agendaCard.appendChild(p);
    } else {
      AGENDA_BUCKETS.forEach(b => {
        const items = agenda[b.key] || [];
        if (!items.length) return;
        const heading = document.createElement('div');
        heading.className = 'dash-item-sub';
        heading.textContent = b.label;
        agendaCard.appendChild(heading);
        items.forEach(n => {
          const item = dashItem(n.title, n.project_name,
                                 () => openRoadmapView(n.project_id, n.project_name));
          const due = document.createElement('div');
          due.className = 'node-due' + (b.key === 'overdue' ? ' overdue' : '');
          due.textContent = (b.key === 'overdue' ? '⚠ Overdue: ' : '⏱ Due ') + n.due_date;
          item.insertBefore(due, item.firstChild);
          agendaCard.appendChild(item);
        });
      });
    }
    grid.appendChild(agendaCard);

    const recentCard = card('Recent', null, null);
    if (!data.recent.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing yet \u2014 start a chat to see it here.';
      recentCard.appendChild(p);
    }
    data.recent.forEach(c => {
      const sub = (c.project_name ? c.project_name + ' \u00b7 ' : '') + relTime(c.updated_at);
      recentCard.appendChild(dashItem(c.title, sub,
                                      () => { showChatView(); openConversation(c.id); }));
    });
    grid.appendChild(recentCard);

    view.appendChild(grid);
  }

  $('brand').onclick = () => openDashboardView();

  // ---------- asking ----------

  // Persisted as the user types, so a reload never loses an unsent
  // message. Cleared only once a send actually succeeds (below) - if the
  // request fails, the draft stays so it isn't lost a second time.
  input.addEventListener('input', () => prefs.set('draft', input.value));

  $('form').addEventListener('submit', async e => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    if (!current) log.innerHTML = '';
    const t = turn();
    userLine(t, message);
    const pending = assistantText(t, 'thinking...', null);
    pending.classList.add('pending');
    log.scrollTop = log.scrollHeight;
    input.disabled = send.disabled = true;

    try {
      const data = await jsonSend('/api/ask', {
        message,
        conversation_id: current ? current.id : '',
        project_id: (!current && pendingProject) ? pendingProject.id : null
      });
      pending.classList.remove('pending');
      if (data.error) { pending.textContent = 'Error: ' + data.error; }
      else {
        prefs.set('draft', '');
        setMarkdown(pending, data.answer);
        metaBlock(t, data.recalled, data.sources);
        if (!current) {
          current = {
            id: data.conversation_id,
            title: message.slice(0, 60),
            project_id: pendingProject ? pendingProject.id : null
          };
          pendingProject = null;
          recordVisit(data.conversation_id);
        }
        setBreadcrumb();
        await loadSidebar();
      }
    } catch (err) {
      pending.classList.remove('pending');
      pending.textContent = 'Error: request failed';
    } finally {
      input.disabled = send.disabled = false;
      input.focus();
      log.scrollTop = log.scrollHeight;
    }
  });

  // ---------- upload ----------

  // uploadTarget decides where the picked file lands: null means "the
  // open chat", a project id means "a new chat inside that project".
  let uploadTarget = null;

  function uploadInto(projectId) {
    uploadTarget = {projectId};
    $('file').click();
  }

  $('attach').onclick = () => { uploadTarget = null; $('file').click(); };

  $('file').onchange = async e => {
    const f = e.target.files[0];
    e.target.value = '';
    if (!f) return;

    const target = uploadTarget;
    uploadTarget = null;
    const dismiss = toast('Uploading ' + f.name + '\u2026', {seconds: 120});

    const q = '?filename=' + encodeURIComponent(f.name) +
              '&conversation_id=' +
              encodeURIComponent(target ? '' : (current ? current.id : ''));
    const res = await fetch('/api/upload' + q, {method: 'POST', body: f});
    const data = await res.json();
    dismiss();

    if (data.error) { toast('Upload failed: ' + data.error, {error: true}); return; }

    if (target && target.projectId) {
      await jsonSend('/api/conversations/' + data.conversation_id,
                     {project_id: target.projectId}, 'PATCH');
      await loadSidebar();
      await openProject(target.projectId, {background: true});
      toast('Added ' + data.filename + ' to this project');
      return;
    }

    await loadSidebar();
    await openConversation(data.conversation_id);
    toast('Stored ' + data.filename + ' (' + data.characters + ' characters)');
  };

  // ---------- dictation ----------
  // Shared by the main composer and every chat panel (roadmap, project,
  // profile assistants) - dictation used to be wired to the main
  // composer only, so the same feature had to be re-typed by hand
  // everywhere else in the app.

  function attachDictation(micBtn, targetField, reportStatus) {
    let recorder = null, chunks = [];
    micBtn.onclick = async () => {
      if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({audio: true});
        recorder = new MediaRecorder(stream);
        chunks = [];
        recorder.ondataavailable = ev => chunks.push(ev.data);
        recorder.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          micBtn.classList.remove('recording');
          micBtn.title = micBtn.ariaLabel = 'Dictate';
          reportStatus('Transcribing\u2026');
          const blob = new Blob(chunks, {type: 'audio/webm'});
          const res = await fetch('/api/transcribe', {method: 'POST', body: blob});
          const data = await res.json();
          if (data.error) { reportStatus('Dictation failed: ' + data.error); return; }
          reportStatus('');
          targetField.value = (targetField.value ? targetField.value + ' ' : '') + data.text;
          targetField.focus();
        };
        recorder.start();
        micBtn.classList.add('recording');
        micBtn.title = micBtn.ariaLabel = 'Stop recording';
        reportStatus('Recording\u2026 click the mic again to stop.');
      } catch (err) {
        reportStatus('Microphone unavailable: ' + err.message);
      }
    };
  }

  attachDictation($('mic'), input, setStatus);

  // A mic button matching #mic's markup, for a panel that doesn't have
  // the main composer's dedicated status line.
  function micButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn';
    btn.title = 'Dictate';
    btn.setAttribute('aria-label', 'Dictate');
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" style="vertical-align:-3px;"><rect x="9" y="2" ' +
      'width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/>' +
      '<line x1="12" y1="19" x2="12" y2="22"/></svg>';
    return btn;
  }

  // ---------- boot ----------
  // Restores whichever screen the user was last on. A persisted view
  // pointing at a project, roadmap, or chat that no longer exists (it
  // was deleted since the last visit) must never strand the user on a
  // broken screen, so every branch validates first and falls back to
  // Today silently rather than surfacing an error with nothing to do
  // about it.
  async function restoreLastView() {
    const last = prefs.get('lastView', null);
    if (!last) { openDashboardView(); return; }
    if (last.type === 'chat') {
      if (!last.id) { newChat(); return; }
      const data = await api('/api/conversations/' + last.id);
      if (data.error) { openDashboardView(); return; }
      await openConversation(last.id);
      return;
    }
    if (last.type === 'project') {
      const data = await api('/api/projects/' + last.id + '?background=1');
      if (data.error) { openDashboardView(); return; }
      await openProject(last.id);
      return;
    }
    if (last.type === 'roadmap') {
      const data = await api('/api/projects/' + last.id + '?background=1');
      if (data.error) { openDashboardView(); return; }
      await openRoadmapView(last.id, data.name);
      return;
    }
    if (last.type === 'profile') { await openProfileView(); return; }
    openDashboardView();
  }

  restoreLastView();
  updateNav();
  loadSidebar();
  