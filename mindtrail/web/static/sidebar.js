  // ---------- sidebar ----------

  async function loadSidebar() {
    [sidebar] = await Promise.all([api('/api/sidebar'), loadAreas()]);
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
        const dot = areaDot(p.area_id);
        if (dot) head.appendChild(dot);
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
      {label: 'Set life area\u2026', run: () => setProjectArea(p)},
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

