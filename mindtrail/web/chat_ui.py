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

    /* --- project detail --- */
    #project-view { flex: 1; overflow-y: auto; display: none; padding: 1.75rem 2rem; }
    #project-view.open { display: block; }
    .proj-layout { display: flex; gap: 1.75rem; max-width: 1180px; margin: 0 auto;
                   align-items: flex-start; }
    .proj-main { flex: 1; min-width: 0; }
    .proj-rail { width: 330px; flex-shrink: 0; }
    .proj-title { font-size: 1.55rem; font-weight: 600; margin: 0 0 1.25rem; }
    .card { background: #1f1f1f; border: 1px solid #2e2e2e; border-radius: 10px;
            padding: 1rem 1.1rem; margin-bottom: 1rem; }
    .card h4 { margin: 0 0 0.7rem; font-size: 0.72rem; text-transform: uppercase;
               letter-spacing: 0.06em; color: #8a8a8a; display: flex;
               align-items: center; gap: 0.4rem; }
    .card h4 .spacer { flex: 1; }
    .card-btn { border: none; background: transparent; color: #8a8a8a; cursor: pointer;
                font-size: 0.8rem; padding: 0.15rem 0.4rem; border-radius: 5px; }
    .card-btn:hover { background: #2c2c2c; color: #fff; }
    .hl { padding: 0.65rem 0; border-bottom: 1px solid #292929; }
    .hl:last-child { border-bottom: none; padding-bottom: 0; }
    .hl-head { font-size: 0.88rem; font-weight: 600; color: #ececec;
               margin-bottom: 0.2rem; }
    .hl-detail { font-size: 0.82rem; color: #a5a5a5; line-height: 1.5; }
    .hl-source { font-size: 0.73rem; color: #6f6f6f; margin-top: 0.25rem; }
    .stamp { font-size: 0.72rem; color: #6a6a6a; margin-top: 0.6rem; }
    .instructions-box { width: 100%; min-height: 84px; resize: vertical;
                        background: #191919; border: 1px solid #333; border-radius: 8px;
                        color: #dcdcdc; font-size: 0.84rem; padding: 0.6rem 0.7rem;
                        font-family: inherit; line-height: 1.5; outline: none; }
    .instructions-box:focus { border-color: #4f46e5; }
    .proj-chat { display: flex; align-items: center; gap: 0.5rem; padding: 0.7rem 0.2rem;
                 border-bottom: 1px solid #262626; cursor: pointer; font-size: 0.9rem; }
    .proj-chat:hover { color: #fff; }
    .proj-chat .when { color: #757575; font-size: 0.78rem; }
    .file-chip { display: inline-block; background: #262626; border: 1px solid #333;
                 border-radius: 6px; padding: 0.3rem 0.6rem; font-size: 0.8rem;
                 color: #c5c5c5; margin: 0.2rem 0.3rem 0.2rem 0; }
    .muted { color: #6f6f6f; font-size: 0.84rem; }

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
      <div id="project-view"></div>
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
  let currentProject = null;
  let pendingProject = null;   // project a not-yet-created chat belongs to
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

  // Reload the sidebar, and the project screen too when one is open -
  // it renders its own copy of names and chat rows, so it goes stale
  // otherwise.
  async function refreshViews() {
    await loadSidebar();
    if (currentProject) await openProject(currentProject);
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
        // Clicking the name opens the project screen; the caret to its
        // left is what expands the chat list inline.
        name.onclick = e => { e.stopPropagation(); openProject(p.id); };
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
        await refreshViews();
      }},
      {label: c.pinned ? 'Unpin' : 'Pin', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {pinned: !c.pinned}, 'PATCH');
        await refreshViews();
      }},
      {label: c.unread ? 'Mark as read' : 'Mark as unread', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {unread: !c.unread}, 'PATCH');
        await refreshViews();
      }},
      {divider: true}
    ];

    sidebar.projects.filter(p => p.id !== c.project_id).forEach(p => {
      items.push({label: 'Move to ' + p.name, run: async () => {
        await jsonSend('/api/conversations/' + c.id, {project_id: p.id}, 'PATCH');
        projectsOpen = true; openProjects.add(p.id);
        if (current && current.id === c.id) { current.project_id = p.id; }
        await refreshViews();
        setBreadcrumb();
      }});
    });
    if (c.project_id) {
      items.push({label: 'Remove from project', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {project_id: null}, 'PATCH');
        if (current && current.id === c.id) { current.project_id = null; }
        await refreshViews();
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
      await refreshViews();
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
        if (currentProject === p.id) await openProject(p.id);
        else setBreadcrumb();
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
    showChatView();
    currentProject = null;
    pendingProject = null;
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
    currentProject = null;
    pendingProject = null;
    showChatView();
    showEmptyState();
    setBreadcrumb();
    recordVisit(null);
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

  function showChatView() {
    $('project-view').classList.remove('open');
    log.style.display = '';
    $('composer').style.display = '';
  }

  function showProjectView() {
    $('project-view').classList.add('open');
    log.style.display = 'none';
    $('composer').style.display = 'none';
  }

  async function openProject(id, opts) {
    const refresh = opts && opts.refresh;
    currentProject = id;
    current = null;
    showProjectView();

    const view = $('project-view');
    view.innerHTML = '<div class="muted">Loading project\\u2026</div>';
    $('breadcrumb').textContent = 'Projects';

    const data = await api('/api/projects/' + id + (refresh ? '?refresh=1' : ''));
    if (data.error) { view.innerHTML = ''; setStatus(data.error); return; }

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
      t.textContent = (c.pinned ? '\\ud83d\\udccc  ' : '') + c.title;
      row.appendChild(t);
      const w = document.createElement('span');
      w.className = 'when';
      w.textContent = relTime(c.updated_at);
      row.appendChild(w);
      row.onclick = () => { showChatView(); openConversation(c.id); };
      chatsCard.appendChild(row);
    });
    main.appendChild(chatsCard);
    layout.appendChild(main);

    // --- right rail: highlights, instructions, files ---
    const rail = document.createElement('div');
    rail.className = 'proj-rail';

    const hlCard = card('What\\u2019s next', '\\u21bb Refresh',
      () => openProject(id, {refresh: true}));
    if (data.highlights_error) {
      const e = document.createElement('div');
      e.className = 'muted';
      e.textContent = data.highlights_error;
      hlCard.appendChild(e);
    }
    if (!data.highlights.length && !data.highlights_error) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = data.entry_count
        ? 'Nothing to suggest yet.'
        : 'Add chats or a document, and suggestions appear here.';
      hlCard.appendChild(p);
    }
    data.highlights.forEach(h => {
      const item = document.createElement('div');
      item.className = 'hl';
      const head = document.createElement('div');
      head.className = 'hl-head';
      head.textContent = h.headline;
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
        s.textContent = 'from: ' + h.source.replace(/^\\[[A-Z]+\\]\\s*/, '');
        item.appendChild(s);
      }
      hlCard.appendChild(item);
    });
    if (data.highlights_generated_at) {
      const stamp = document.createElement('div');
      stamp.className = 'stamp';
      stamp.textContent = 'Updated ' + relTime(data.highlights_generated_at) +
                          ' \\u00b7 based on ' + data.entry_count + ' item(s)';
      hlCard.appendChild(stamp);
    }
    rail.appendChild(hlCard);

    const instrCard = card('Instructions', 'Save', null);
    const box = document.createElement('textarea');
    box.className = 'instructions-box';
    box.value = data.instructions || '';
    box.placeholder = 'Guidance applied to every answer in this project.';
    instrCard.appendChild(box);
    instrCard.querySelector('.card-btn').onclick = async () => {
      await jsonSend('/api/projects/' + id, {instructions: box.value}, 'PATCH');
      setStatus('Instructions saved.');
    };
    rail.appendChild(instrCard);

    const filesCard = card('Files', null, null);
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
      chip.onclick = () => { showChatView(); openConversation(f.conversation_id); };
      filesCard.appendChild(chip);
    });
    rail.appendChild(filesCard);

    layout.appendChild(rail);
    view.appendChild(layout);
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
        message,
        conversation_id: current ? current.id : '',
        project_id: (!current && pendingProject) ? pendingProject.id : null
      });
      pending.classList.remove('pending');
      if (data.error) { pending.textContent = 'Error: ' + data.error; }
      else {
        pending.textContent = data.answer;
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
