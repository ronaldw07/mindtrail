"""The chat page markup, styles, and client script.

Kept in its own module so chat_server.py stays about HTTP routing rather
than being mostly a large string literal.
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

    #sidebar { width: 275px; background: #171717; border-right: 1px solid #2a2a2a;
               display: flex; flex-direction: column; flex-shrink: 0; }
    .brand { padding: 1rem 1rem 0.6rem; font-weight: 600; }
    .side-btn { margin: 0 1rem 0.4rem; padding: 0.55rem 0.8rem; border-radius: 8px;
                border: 1px solid #333; background: #212121; color: #ececec;
                cursor: pointer; text-align: left; font-size: 0.88rem; width: calc(100% - 2rem); }
    .side-btn:hover { background: #2a2a2a; }
    #tree { flex: 1; overflow-y: auto; padding: 0.5rem 0.5rem 1.5rem; }
    .section-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
                     color: #6b6b6b; padding: 0.7rem 0.6rem 0.3rem; }
    .project { margin-bottom: 0.15rem; }
    .project-head { display: flex; align-items: center; gap: 0.35rem;
                    padding: 0.4rem 0.6rem; border-radius: 6px; cursor: pointer;
                    color: #d0d0d0; font-size: 0.85rem; font-weight: 500; }
    .project-head:hover { background: #212121; }
    .caret { font-size: 0.65rem; color: #777; width: 0.7rem; }
    .chat { display: flex; align-items: center; gap: 0.3rem; padding: 0.4rem 0.6rem;
            border-radius: 6px; cursor: pointer; font-size: 0.84rem; color: #b8b8b8; }
    .chat:hover { background: #212121; }
    .chat.active { background: #2b2b2b; color: #fff; }
    .chat.unread .chat-title { font-weight: 700; color: #fff; }
    .chat-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: #4f8ef7; flex-shrink: 0; }
    .pin { font-size: 0.7rem; color: #888; }
    .menu-btn { opacity: 0; border: none; background: transparent; color: #999;
                cursor: pointer; font-size: 0.95rem; padding: 0 0.2rem; line-height: 1; }
    .chat:hover .menu-btn, .project-head:hover .menu-btn { opacity: 1; }
    .nested { margin-left: 0.85rem; }

    #menu { position: fixed; background: #262626; border: 1px solid #3a3a3a;
            border-radius: 8px; padding: 0.3rem; display: none; z-index: 50;
            min-width: 165px; box-shadow: 0 6px 22px rgba(0,0,0,0.45); }
    #menu div { padding: 0.45rem 0.7rem; border-radius: 5px; cursor: pointer;
                font-size: 0.83rem; color: #ddd; }
    #menu div:hover { background: #333; }
    #menu .danger { color: #f87171; }
    #menu hr { border: none; border-top: 1px solid #3a3a3a; margin: 0.25rem 0; }

    main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    #breadcrumb { padding: 0.9rem 1.5rem; border-bottom: 1px solid #2a2a2a;
                  font-size: 0.85rem; color: #999; flex-shrink: 0; }
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
    .kind-tag { display: inline-block; font-size: 0.68rem; text-transform: uppercase;
                letter-spacing: 0.03em; color: #999; margin-bottom: 0.3rem; }

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
      <button class="side-btn" id="new-chat">+ New chat</button>
      <button class="side-btn" id="new-project">+ New project</button>
      <div id="tree"></div>
    </aside>
    <main>
      <div id="breadcrumb">New chat</div>
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

  <script>
  const $ = id => document.getElementById(id);
  const log = $('log'), input = $('input'), send = $('send'), status = $('status');
  const menu = $('menu');
  let current = null;      // {id, title, project_id}
  let sidebar = {projects: [], unfiled: []};

  const api = async (path, opts) => (await fetch(path, opts)).json();
  const jsonPost = (path, body, method) => api(path, {
    method: method || 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });

  function setStatus(msg) { status.textContent = msg || ''; }

  // ---------- sidebar ----------

  async function loadSidebar() {
    sidebar = await api('/api/sidebar');
    renderTree();
  }

  function chatRow(c) {
    const row = document.createElement('div');
    row.className = 'chat' + (c.unread ? ' unread' : '') + (current && current.id === c.id ? ' active' : '');
    if (c.unread) row.appendChild(Object.assign(document.createElement('div'), {className: 'dot'}));
    if (c.pinned) row.appendChild(Object.assign(document.createElement('span'), {className: 'pin', textContent: '📌'}));
    const title = document.createElement('span');
    title.className = 'chat-title'; title.textContent = c.title;
    row.appendChild(title);
    const btn = document.createElement('button');
    btn.className = 'menu-btn'; btn.textContent = '⋯';
    btn.onclick = e => { e.stopPropagation(); openChatMenu(e, c); };
    row.appendChild(btn);
    row.onclick = () => openConversation(c.id);
    return row;
  }

  function renderTree() {
    const tree = $('tree');
    tree.innerHTML = '';

    sidebar.projects.forEach(p => {
      const wrap = document.createElement('div');
      wrap.className = 'project';
      const head = document.createElement('div');
      head.className = 'project-head';
      head.innerHTML = '<span class="caret">▾</span>';
      const name = document.createElement('span');
      name.style.flex = '1'; name.textContent = p.name;
      head.appendChild(name);
      const btn = document.createElement('button');
      btn.className = 'menu-btn'; btn.textContent = '⋯';
      btn.onclick = e => { e.stopPropagation(); openProjectMenu(e, p); };
      head.appendChild(btn);
      const kids = document.createElement('div');
      kids.className = 'nested';
      p.conversations.forEach(c => kids.appendChild(chatRow(c)));
      head.onclick = () => { kids.style.display = kids.style.display === 'none' ? '' : 'none'; };
      wrap.appendChild(head); wrap.appendChild(kids);
      tree.appendChild(wrap);
    });

    if (sidebar.unfiled.length) {
      tree.appendChild(Object.assign(document.createElement('div'),
        {className: 'section-label', textContent: 'Chats'}));
      sidebar.unfiled.forEach(c => tree.appendChild(chatRow(c)));
    }
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
    menu.style.left = Math.min(e.clientX, window.innerWidth - 185) + 'px';
    menu.style.top = e.clientY + 'px';
  }

  document.addEventListener('click', e => {
    if (!menu.contains(e.target)) menu.style.display = 'none';
  });

  function openChatMenu(e, c) {
    const items = [
      {label: 'Rename', run: async () => {
        const t = prompt('Rename chat', c.title);
        if (t && t.trim()) { await jsonPost('/api/conversations/' + c.id, {title: t}, 'PATCH'); await refresh(); }
      }},
      {label: c.pinned ? 'Unpin' : 'Pin', run: async () => {
        await jsonPost('/api/conversations/' + c.id, {pinned: !c.pinned}, 'PATCH'); await refresh();
      }},
      {label: c.unread ? 'Mark as read' : 'Mark as unread', run: async () => {
        await jsonPost('/api/conversations/' + c.id, {unread: !c.unread}, 'PATCH'); await refresh();
      }},
      {divider: true}
    ];

    sidebar.projects.filter(p => p.id !== c.project_id).forEach(p => {
      items.push({label: 'Move to ' + p.name, run: async () => {
        await jsonPost('/api/conversations/' + c.id, {project_id: p.id}, 'PATCH'); await refresh();
      }});
    });
    if (c.project_id) {
      items.push({label: 'Remove from project', run: async () => {
        await jsonPost('/api/conversations/' + c.id, {project_id: null}, 'PATCH'); await refresh();
      }});
    }

    items.push({divider: true});
    items.push({label: 'Delete', danger: true, run: async () => {
      if (!confirm('Delete "' + c.title + '" and everything in it?')) return;
      await api('/api/conversations/' + c.id, {method: 'DELETE'});
      if (current && current.id === c.id) newChat();
      await refresh();
    }});
    showMenu(e, items);
  }

  function openProjectMenu(e, p) {
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const n = prompt('Rename project', p.name);
        if (n && n.trim()) { await jsonPost('/api/projects/' + p.id, {name: n}, 'PATCH'); await refresh(); }
      }},
      {divider: true},
      {label: 'Delete project', danger: true, run: async () => {
        if (!confirm('Delete project "' + p.name + '"? Its chats are kept and moved out.')) return;
        await api('/api/projects/' + p.id, {method: 'DELETE'});
        await refresh();
      }}
    ]);
  }

  async function refresh() { await loadSidebar(); }

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
    if ((recalled || []).length) m.innerHTML += 'Built on: ' + recalled.join(', ') + '<br>';
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
    $('breadcrumb').innerHTML = (proj ? proj.name + ' / ' : '') + '<b>' + current.title + '</b>';
  }

  async function openConversation(id) {
    const data = await api('/api/conversations/' + id);
    if (data.error) return;
    current = data.conversation;
    log.innerHTML = '';
    data.entries.forEach(e => {
      const t = turn();
      userLine(t, e.query);
      assistantText(t, e.summary, e.kind);
      metaBlock(t, [], e.sources);
    });
    setBreadcrumb();
    await loadSidebar();
    log.scrollTop = log.scrollHeight;
  }

  function newChat() {
    current = null; log.innerHTML = '';
    setBreadcrumb(); renderTree(); input.focus();
  }

  $('new-chat').onclick = newChat;
  $('new-project').onclick = async () => {
    const name = prompt('Project name');
    if (name && name.trim()) { await jsonPost('/api/projects', {name}); await refresh(); }
  };

  // ---------- asking ----------

  $('form').addEventListener('submit', async e => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    const t = turn();
    userLine(t, message);
    const pending = assistantText(t, 'thinking...', null);
    pending.classList.add('pending');
    log.scrollTop = log.scrollHeight;
    input.disabled = send.disabled = true;

    try {
      const data = await jsonPost('/api/ask', {
        message, conversation_id: current ? current.id : ''
      });
      pending.classList.remove('pending');
      if (data.error) { pending.textContent = 'Error: ' + data.error; }
      else {
        pending.textContent = data.answer;
        metaBlock(t, data.recalled, data.sources);
        if (!current) current = {id: data.conversation_id, title: message.slice(0, 60), project_id: null};
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
    setStatus('Stored ' + data.filename + ' (' + data.characters + ' chars)');
    await loadSidebar();
    await openConversation(data.conversation_id);
  };

  // ---------- dictation ----------

  let recorder = null, chunks = [];
  $('mic').onclick = async () => {
    const mic = $('mic');
    if (recorder && recorder.state === 'recording') {
      recorder.stop();
      return;
    }
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
      setStatus('Recording... click the mic again to stop.');
    } catch (err) {
      setStatus('Microphone unavailable: ' + err.message);
    }
  };

  loadSidebar();
  </script>
</body>
</html>"""
