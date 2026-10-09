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
      assistantText(t, e.summary, e.kind, {
        plain: e.kind === 'document' || e.kind === 'note' || e.kind === 'link',
      });
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

