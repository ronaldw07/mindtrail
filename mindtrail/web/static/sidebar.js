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

  const CHEVRON_SVG = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  const FOLDER_SVG = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
  // Chats listed under each project; the rest sit behind "View all".
  const PROJECT_PREVIEW_CHATS = 3;

  // A titled section of the tree: a header that folds its body, with an
  // optional + button. Folding toggles a class in place rather than
  // rebuilding the tree, so the chevron can turn instead of jumping.
  function treeSection(label, open, onToggle, opts) {
    const sec = document.createElement('div');
    sec.className = 'tree-sec' + (open ? '' : ' collapsed');
    const row = document.createElement('div');
    row.className = 'section clickable';
    const l = document.createElement('span');
    l.className = 'label';
    l.textContent = label;
    row.appendChild(l);
    const chev = document.createElement('span');
    chev.className = 'sec-chevron';
    chev.innerHTML = CHEVRON_SVG;
    row.appendChild(chev);
    if (opts.onAdd) {
      const b = document.createElement('button');
      b.className = 'add';
      b.textContent = '+';
      b.title = opts.addTitle || 'Add';
      b.setAttribute('aria-label', opts.addTitle || 'Add');
      b.onclick = e => { e.stopPropagation(); opts.onAdd(); };
      row.appendChild(b);
    }
    makeClickable(row, () => {
      const nowOpen = sec.classList.toggle('collapsed') === false;
      row.setAttribute('aria-expanded', String(nowOpen));
      onToggle(nowOpen);
    });
    row.setAttribute('aria-expanded', String(open));
    const body = document.createElement('div');
    body.className = 'tree-body';
    sec.appendChild(row);
    sec.appendChild(body);
    return {sec, body};
  }

  // Lights up the row for whatever is on screen. Called on every view
  // change rather than rebuilding the tree, which would reset hover.
  function syncTreeActive() {
    const tree = $('tree');
    if (!tree) return;
    const onProject = ['project', 'roadmap'].includes(activeView);
    tree.querySelectorAll('[data-project]').forEach(el =>
      el.classList.toggle('active', onProject && el.dataset.project === currentProject));
    tree.querySelectorAll('[data-chat]').forEach(el =>
      el.classList.toggle('active', activeView === 'chat' && !!current && el.dataset.chat === current.id));
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
    row.className = 'chat' + (c.unread ? ' unread' : '');
    row.dataset.chat = c.id;
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
    onRightClick(row, e => openChatMenu(e, c));
    return row;
  }

  function renderTree() {
    const tree = $('tree');
    tree.replaceChildren();

    const projects = treeSection('Projects', projectsOpen, open => {
      projectsOpen = open;
      prefs.set('projectsOpen', open);
    }, {onAdd: createProject, addTitle: 'New project'});
    if (!sidebar.projects.length) {
      const hint = document.createElement('div');
      hint.className = 'empty-hint';
      hint.textContent = 'No projects yet \u2014 use + to add one.';
      projects.body.appendChild(hint);
    }
    sidebar.projects.forEach(p => projects.body.appendChild(projectRow(p)));
    tree.appendChild(projects.sec);

    const chats = treeSection('Chats', chatsOpen, open => {
      chatsOpen = open;
      prefs.set('chatsOpen', open);
    }, {onAdd: newChat, addTitle: 'New chat'});
    sidebar.unfiled.forEach(c => chats.body.appendChild(chatRow(c)));
    tree.appendChild(chats.sec);
    syncTreeActive();
  }

  // A project with its newest chats under it. The folder icon turns into
  // a chevron on hover and folds the chats; the name opens the project.
  function projectRow(p) {
    const wrap = document.createElement('div');
    wrap.className = 'project' + (closedProjects.has(p.id) ? ' collapsed' : '');

    const head = document.createElement('div');
    head.className = 'project-head';
    head.dataset.project = p.id;
    const toggle = document.createElement('button');
    toggle.className = 'project-toggle';
    toggle.innerHTML = '<span class="pt-folder">' + FOLDER_SVG + '</span>' +
                       '<span class="pt-chevron">' + CHEVRON_SVG + '</span>';
    const area = areaById(p.area_id);
    if (area) toggle.style.color = area.color;
    const syncToggle = () => {
      const open = !closedProjects.has(p.id);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' chats in ' + p.name);
    };
    syncToggle();
    toggle.onclick = e => {
      e.stopPropagation();
      closedProjects.has(p.id) ? closedProjects.delete(p.id) : closedProjects.add(p.id);
      prefs.set('closedProjects', Array.from(closedProjects));
      wrap.classList.toggle('collapsed', closedProjects.has(p.id));
      syncToggle();
    };
    head.appendChild(toggle);
    const name = document.createElement('span');
    name.className = 'project-name';
    name.textContent = p.name;
    head.appendChild(name);
    const btn = document.createElement('button');
    btn.className = 'menu-btn';
    btn.textContent = '\u22ef';
    btn.title = 'Project options';
    btn.setAttribute('aria-label', 'Project options');
    btn.onclick = e => { e.stopPropagation(); openProjectMenu(e, p); };
    head.appendChild(btn);
    makeClickable(head, () => openProject(p.id));
    onRightClick(head, e => openProjectMenu(e, p));
    wrap.appendChild(head);

    const kids = document.createElement('div');
    kids.className = 'nested';
    const shown = p.conversations.slice(0, PROJECT_PREVIEW_CHATS);
    // The chat you're in stays visible even when it's older than the preview.
    const open = current && p.conversations.find(c => c.id === current.id);
    if (open && !shown.includes(open)) shown.push(open);
    shown.forEach(c => kids.appendChild(chatRow(c)));
    if (p.conversations.length > shown.length) {
      const all = document.createElement('div');
      all.className = 'view-all';
      all.textContent = 'View all';
      makeClickable(all, () => openProject(p.id));
      kids.appendChild(all);
    }
    wrap.appendChild(kids);
    return wrap;
  }

  async function createProject() {
    const name = await askText('New project', '', 'e.g. Career');
    if (!name) return;
    const res = await jsonSend('/api/projects', {name});
    if (res.error) { toast(res.error, {error: true}); return; }
    projectsOpen = true;
    prefs.set('projectsOpen', true);
    closedProjects.delete(res.id);
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
        projectsOpen = true; prefs.set('projectsOpen', true); closedProjects.delete(p.id);
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
        closedProjects.delete(p.id);
        if (currentProject === p.id) newChat();
        await loadSidebar();
        setBreadcrumb();
        toast('Deleted project "' + p.name + '" \u2014 its chats were kept');
      }}
    ]);
  }

