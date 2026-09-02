"""The chat page markup, styles, and client script.

Kept in its own module so chat_server.py stays about HTTP routing rather
than being mostly a large string literal.

Native prompt/confirm dialogs are deliberately not used anywhere: they
render in the OS light theme regardless of the page, which breaks the
dark UI. Everything goes through the in-page modal below.
"""

CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, system-ui, sans-serif;
           background: #1a1a1a; color: #ececec; height: 100vh; overflow: hidden; }
    #app { display: flex; height: 100vh; }

    /* --- sidebar --- */
    #sidebar { width: 275px; background: #171717; border-right: 1px solid #2a2a2a;
               display: flex; flex-direction: column; flex-shrink: 0;
               overflow: hidden; transition: width 0.16s ease, border-width 0.16s ease; }
    #sidebar.collapsed { width: 0; border-right-width: 0; }
    .brand { padding: 1rem 1rem 0.75rem; font-weight: 600; letter-spacing: 0.01em;
             white-space: nowrap; }
    #tree { flex: 1; overflow-y: auto; padding: 0 0.5rem 1.5rem; }

    .section { display: flex; align-items: center; gap: 0.35rem;
               padding: 0.75rem 0.6rem 0.35rem; font-size: 0.7rem;
               text-transform: uppercase; letter-spacing: 0.05em; color: #6b6b6b;
               user-select: none; }
    .section.clickable { cursor: pointer; border-radius: 6px; }
    .section.clickable:hover { color: #9a9a9a; }
    .section .label { flex: 1; }
    .sec-caret { font-size: 0.6rem; width: 0.7rem; color: #6b6b6b; }
    .add { border: none; background: transparent; color: #7d7d7d; cursor: pointer;
           font-size: 1.05rem; line-height: 1; padding: 0.1rem 0.3rem;
           border-radius: 5px; }
    .add:hover { background: #2a2a2a; color: #fff; }
    .empty-hint { padding: 0.35rem 0.75rem 0.5rem; font-size: 0.78rem; color: #5f5f5f; }

    .project { margin-bottom: 0.1rem; }
    .project-head { display: flex; align-items: center; gap: 0.35rem;
                    padding: 0.4rem 0.6rem; border-radius: 6px; cursor: pointer;
                    color: #d0d0d0; font-size: 0.85rem; font-weight: 500; }
    .project-head:hover { background: #212121; }
    .caret { font-size: 0.65rem; color: #777; width: 0.7rem; }
    .chat { display: flex; align-items: center; gap: 0.35rem; padding: 0.4rem 0.6rem;
            border-radius: 6px; cursor: pointer; font-size: 0.84rem; color: #b8b8b8; }
    .chat:hover { background: #212121; }
    .chat.active { background: #2b2b2b; color: #fff; }
    .chat.unread .chat-title { font-weight: 700; color: #fff; }
    .chat-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: #4f8ef7; flex-shrink: 0; }
    .pin { font-size: 0.7rem; }
    .menu-btn { opacity: 0; border: none; background: transparent; color: #999;
                cursor: pointer; font-size: 0.95rem; padding: 0 0.2rem; line-height: 1; }
    .chat:hover .menu-btn, .project-head:hover .menu-btn { opacity: 1; }
    .nested { margin-left: 0.85rem; }

    /* --- context menu --- */
    #menu { position: fixed; background: #262626; border: 1px solid #3a3a3a;
            border-radius: 8px; padding: 0.3rem; display: none; z-index: 60;
            min-width: 175px; box-shadow: 0 6px 22px rgba(0,0,0,0.45); }
    #menu div { padding: 0.45rem 0.7rem; border-radius: 5px; cursor: pointer;
                font-size: 0.83rem; color: #ddd; }
    #menu div:hover { background: #333; }
    #menu .danger { color: #f87171; }
    #menu hr { border: none; border-top: 1px solid #3a3a3a; margin: 0.25rem 0; }

    /* --- modal (replaces native prompt/confirm) --- */
    #overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.62);
               display: none; align-items: center; justify-content: center; z-index: 100; }
    #overlay.open { display: flex; }
    .modal { background: #212121; border: 1px solid #383838; border-radius: 12px;
             padding: 1.25rem; width: 390px; max-width: calc(100vw - 2rem);
             box-shadow: 0 18px 50px rgba(0,0,0,0.55); }
    .modal h3 { margin: 0 0 0.75rem; font-size: 0.95rem; font-weight: 600; color: #f2f2f2; }
    .modal p { margin: 0 0 1rem; font-size: 0.86rem; color: #a8a8a8; line-height: 1.55; }
    .modal input { width: 100%; padding: 0.6rem 0.75rem; border-radius: 8px;
                   border: 1px solid #3a3a3a; background: #191919; color: #ececec;
                   font-size: 0.9rem; outline: none; }
    .modal input:focus { border-color: #4f46e5; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem;
                     margin-top: 1.1rem; }
    .modal button { padding: 0.5rem 1.05rem; border-radius: 7px; border: none;
                    font-size: 0.85rem; cursor: pointer; }
    .btn-ghost { background: transparent; color: #a0a0a0; }
    .btn-ghost:hover { background: #2e2e2e; color: #fff; }
    .btn-primary { background: #4f46e5; color: #fff; }
    .btn-primary:hover { background: #5b52ea; }
    .btn-danger { background: #b91c1c; color: #fff; }
    .btn-danger:hover { background: #cf2222; }

    /* --- main --- */
    main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    #topbar { display: flex; align-items: center; gap: 0.15rem; padding: 0.6rem 1.25rem;
              border-bottom: 1px solid #2a2a2a; flex-shrink: 0; }
    .nav-btn { background: transparent; border: none; color: #9a9a9a; cursor: pointer;
               font-size: 0.95rem; line-height: 1; padding: 0.35rem 0.45rem;
               border-radius: 6px; }
    .nav-btn:hover:not(:disabled) { background: #2a2a2a; color: #fff; }
    .nav-btn:disabled { opacity: 0.3; cursor: default; }
    #breadcrumb { font-size: 0.85rem; color: #999; margin-left: 0.6rem;
                  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #breadcrumb b { color: #ececec; font-weight: 600; }
    #log { flex: 1; overflow-y: auto; padding: 1.5rem 2rem; max-width: 760px;
           margin: 0 auto; width: 100%; }
    .turn { margin-bottom: 1.6rem; }
    .user-line { display: flex; justify-content: flex-end; margin-bottom: 0.6rem; }
    .user-line span { background: #2a2a2a; padding: 0.5rem 0.9rem; border-radius: 14px;
                       max-width: 80%; white-space: pre-wrap; font-size: 0.95rem; }
    .assistant-text { white-space: pre-wrap; line-height: 1.6; font-size: 0.97rem; }
    .assistant-text.pending { color: #888; font-style: italic; }
    .meta { margin-top: 0.6rem; font-size: 0.78rem; color: #888; }
    .meta a { color: #8ab4f8; display: block; text-decoration: none; }
    .meta a:hover { text-decoration: underline; }
    .kind-tag { display: inline-block; font-size: 0.68rem; text-transform: uppercase;
                letter-spacing: 0.03em; color: #999; margin-bottom: 0.3rem; }
    .empty-state { color: #6a6a6a; font-size: 0.9rem; text-align: center;
                   margin-top: 22vh; line-height: 1.7; }

    #composer { padding: 1rem 1.5rem 1.5rem; flex-shrink: 0; }
    form { max-width: 760px; margin: 0 auto; display: flex; align-items: center;
           gap: 0.4rem; background: #212121; border: 1px solid #333; border-radius: 26px;
           padding: 0.35rem 0.4rem 0.35rem 0.9rem; }
    #input { flex: 1; background: transparent; border: none; outline: none;
             color: #ececec; font-size: 0.95rem; padding: 0.5rem 0; }
    #input::placeholder { color: #777; }
    .icon-btn { background: transparent; border: none; color: #aaa; cursor: pointer;
                font-size: 1.05rem; padding: 0.35rem 0.5rem; border-radius: 50%; }
    .icon-btn:hover { background: #2e2e2e; color: #fff; }
    .icon-btn.recording { color: #f87171; background: #3a2020; }
    button.send { padding: 0.55rem 1.1rem; border-radius: 20px; border: none;
                  background: #4f46e5; color: white; font-size: 0.88rem; cursor: pointer; }
    button.send:disabled { opacity: 0.4; cursor: default; }
    #status { max-width: 760px; margin: 0.4rem auto 0; font-size: 0.76rem; color: #888;
              min-height: 1rem; }
  </style>
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <div class="brand">mindtrail</div>
      <div id="tree"></div>
    </aside>
    <main>
      <div id="topbar">
        <button class="nav-btn" id="toggle-sidebar" title="Toggle sidebar">&#9707;</button>
        <button class="nav-btn" id="nav-back" title="Back" disabled>&#8592;</button>
        <button class="nav-btn" id="nav-fwd" title="Forward" disabled>&#8594;</button>
        <div id="breadcrumb">New chat</div>
      </div>
      <div id="log"></div>
      <div id="composer">
        <form id="form">
          <button type="button" class="icon-btn" id="attach" title="Upload a PDF">+</button>
          <button type="button" class="icon-btn" id="mic" title="Dictate">&#127908;</button>
          <input id="input" autocomplete="off" placeholder="Ask something..." autofocus>
          <button class="send" id="send">Ask</button>
        </form>
        <div id="status"></div>
        <input type="file" id="file" accept="application/pdf" style="display:none">
      </div>
    </main>
  </div>
  <div id="menu"></div>
  <div id="overlay"></div>

  <script>
  const $ = id => document.getElementById(id);
  const log = $('log'), input = $('input'), send = $('send'), status = $('status');
  const menu = $('menu'), overlay = $('overlay');
  let current = null;
  let sidebar = {projects: [], unfiled: []};
  let projectsOpen = false;
  const openProjects = new Set();

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
      if (opts.input) {
        field = document.createElement('input');
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
      const submit = () => close(opts.input ? (field.value.trim() || null) : true);
      const onKey = e => {
        if (e.key === 'Escape') { e.preventDefault(); close(null); }
        else if (e.key === 'Enter') { e.preventDefault(); submit(); }
      };

      cancel.onclick = () => close(null);
      ok.onclick = submit;
      overlay.onclick = e => { if (e.target === overlay) close(null); };
      document.addEventListener('keydown', onKey);
      if (field) { field.focus(); field.select(); }
      else ok.focus();
    });
  }

  const askText = (title, value, placeholder) =>
    modal({title, value, placeholder, input: true});
  const askConfirm = (title, message, confirmLabel) =>
    modal({title, message, confirmLabel, danger: true});

  // ---------- sidebar ----------

  async function loadSidebar() {
    sidebar = await api('/api/sidebar');
    renderTree();
  }

  function sectionRow(label, opts) {
    const row = document.createElement('div');
    row.className = 'section' + (opts.onClick ? ' clickable' : '');
    if (opts.caret) {
      const c = document.createElement('span');
      c.className = 'sec-caret';
      c.textContent = opts.open ? '\\u25be' : '\\u25b8';
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
    if (opts.onClick) row.onclick = opts.onClick;
    return row;
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
      p.className = 'pin'; p.textContent = '\\ud83d\\udccc';
      row.appendChild(p);
    }
    const title = document.createElement('span');
    title.className = 'chat-title';
    title.textContent = c.title;
    row.appendChild(title);
    const btn = document.createElement('button');
    btn.className = 'menu-btn';
    btn.textContent = '\\u22ef';
    btn.onclick = e => { e.stopPropagation(); openChatMenu(e, c); };
    row.appendChild(btn);
    row.onclick = () => openConversation(c.id);
    return row;
  }

  function renderTree() {
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
        hint.textContent = 'No projects yet \\u2014 use + to add one.';
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
        caret.textContent = expanded ? '\\u25be' : '\\u25b8';
        head.appendChild(caret);
        const name = document.createElement('span');
        name.style.flex = '1';
        name.textContent = p.name;
        head.appendChild(name);
        const btn = document.createElement('button');
        btn.className = 'menu-btn';
        btn.textContent = '\\u22ef';
        btn.onclick = e => { e.stopPropagation(); openProjectMenu(e, p); };
        head.appendChild(btn);
        head.onclick = () => {
          expanded ? openProjects.delete(p.id) : openProjects.add(p.id);
          renderTree();
        };
        wrap.appendChild(head);

        if (expanded) {
          const kids = document.createElement('div');
          kids.className = 'nested';
          if (!p.conversations.length) {
            const empty = document.createElement('div');
            empty.className = 'empty-hint';
            empty.textContent = 'Empty \\u2014 move a chat here.';
            kids.appendChild(empty);
          }
          p.conversations.forEach(c => kids.appendChild(chatRow(c)));
          wrap.appendChild(kids);
        }
        tree.appendChild(wrap);
      });
    }

    // Chats: + starts a new one.
    tree.appendChild(sectionRow('Chats', {
      onAdd: newChat,
      addTitle: 'New chat'
    }));
    sidebar.unfiled.forEach(c => tree.appendChild(chatRow(c)));
  }

  async function createProject() {
    const name = await askText('New project', '', 'e.g. Career');
    if (!name) return;
    const res = await jsonSend('/api/projects', {name});
    if (res.error) { setStatus(res.error); return; }
    projectsOpen = true;
    openProjects.add(res.id);
    await loadSidebar();
  }

  // ---------- context menus ----------

  function showMenu(e, items) {
    menu.innerHTML = '';
    items.forEach(it => {
      if (it.divider) { menu.appendChild(document.createElement('hr')); return; }
      const d = document.createElement('div');
      d.textContent = it.label;
      if (it.danger) d.className = 'danger';
      d.onclick = async () => { menu.style.display = 'none'; await it.run(); };
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
        await loadSidebar();
      }},
      {label: c.pinned ? 'Unpin' : 'Pin', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {pinned: !c.pinned}, 'PATCH');
        await loadSidebar();
      }},
      {label: c.unread ? 'Mark as read' : 'Mark as unread', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {unread: !c.unread}, 'PATCH');
        await loadSidebar();
      }},
      {divider: true}
    ];

    sidebar.projects.filter(p => p.id !== c.project_id).forEach(p => {
      items.push({label: 'Move to ' + p.name, run: async () => {
        await jsonSend('/api/conversations/' + c.id, {project_id: p.id}, 'PATCH');
        projectsOpen = true; openProjects.add(p.id);
        if (current && current.id === c.id) { current.project_id = p.id; }
        await loadSidebar();
        setBreadcrumb();
      }});
    });
    if (c.project_id) {
      items.push({label: 'Remove from project', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {project_id: null}, 'PATCH');
        if (current && current.id === c.id) { current.project_id = null; }
        await loadSidebar();
        setBreadcrumb();
      }});
    }

    items.push({divider: true});
    items.push({label: 'Delete', danger: true, run: async () => {
      const ok = await askConfirm('Delete chat',
        '"' + c.title + '" and everything in it will be removed. This cannot be undone.',
        'Delete');
      if (!ok) return;
      await api('/api/conversations/' + c.id, {method: 'DELETE'});
      if (current && current.id === c.id) newChat();
      await loadSidebar();
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
        setBreadcrumb();
      }},
      {divider: true},
      {label: 'Delete project', danger: true, run: async () => {
        const ok = await askConfirm('Delete project',
          'Chats inside "' + p.name + '" are kept and moved out of the project.',
          'Delete project');
        if (!ok) return;
        await api('/api/projects/' + p.id, {method: 'DELETE'});
        openProjects.delete(p.id);
        await loadSidebar();
        setBreadcrumb();
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
  function assistantText(c, text, kind) {
    if (kind && kind !== 'research') {
      const t = document.createElement('div'); t.className = 'kind-tag';
      t.textContent = kind; c.appendChild(t);
    }
    const d = document.createElement('div'); d.className = 'assistant-text';
    d.textContent = text; c.appendChild(d); return d;
  }
  function metaBlock(c, recalled, sources) {
    if (!(recalled || []).length && !(sources || []).length) return;
    const m = document.createElement('div'); m.className = 'meta';
    if ((recalled || []).length) {
      const r = document.createElement('div');
      r.textContent = 'Built on: ' + recalled.join(', ');
      m.appendChild(r);
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
    $('sidebar').classList.toggle('collapsed');
  };

  // ---------- opening ----------

  async function openConversation(id) {
    const data = await api('/api/conversations/' + id);
    if (data.error) { setStatus(data.error); return; }
    current = data.conversation;
    log.innerHTML = '';
    data.entries.forEach(e => {
      const t = turn();
      userLine(t, e.query);
      assistantText(t, e.summary, e.kind);
      metaBlock(t, [], e.sources);
    });
    setBreadcrumb();
    recordVisit(id);
    await loadSidebar();
    log.scrollTop = log.scrollHeight;
  }

  function newChat() {
    current = null;
    showEmptyState();
    setBreadcrumb();
    recordVisit(null);
    renderTree();
    input.focus();
  }

  // ---------- asking ----------

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
        message, conversation_id: current ? current.id : ''
      });
      pending.classList.remove('pending');
      if (data.error) { pending.textContent = 'Error: ' + data.error; }
      else {
        pending.textContent = data.answer;
        metaBlock(t, data.recalled, data.sources);
        if (!current) {
          current = {id: data.conversation_id, title: message.slice(0, 60), project_id: null};
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

  $('attach').onclick = () => $('file').click();
  $('file').onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    setStatus('Uploading ' + f.name + '...');
    const q = '?filename=' + encodeURIComponent(f.name) +
              '&conversation_id=' + encodeURIComponent(current ? current.id : '');
    const res = await fetch('/api/upload' + q, {method: 'POST', body: f});
    const data = await res.json();
    e.target.value = '';
    if (data.error) { setStatus('Upload failed: ' + data.error); return; }
    setStatus('Stored ' + data.filename + ' (' + data.characters + ' characters)');
    await loadSidebar();
    await openConversation(data.conversation_id);
  };

  // ---------- dictation ----------

  let recorder = null, chunks = [];
  $('mic').onclick = async () => {
    const mic = $('mic');
    if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = ev => chunks.push(ev.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        mic.classList.remove('recording');
        setStatus('Transcribing...');
        const blob = new Blob(chunks, {type: 'audio/webm'});
        const res = await fetch('/api/transcribe', {method: 'POST', body: blob});
        const data = await res.json();
        if (data.error) { setStatus('Dictation failed: ' + data.error); return; }
        setStatus('');
        input.value = (input.value ? input.value + ' ' : '') + data.text;
        input.focus();
      };
      recorder.start();
      mic.classList.add('recording');
      setStatus('Recording\\u2026 click the mic again to stop.');
    } catch (err) {
      setStatus('Microphone unavailable: ' + err.message);
    }
  };

  showEmptyState();
  updateNav();
  loadSidebar();
  </script>
</body>
</html>"""
