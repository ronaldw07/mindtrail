
  // ---------- life areas, habits, journal ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.

  let lifeAreas = [];  // [{id, name, color, sort}], refreshed with the sidebar

  async function loadAreas() {
    const data = await api('/api/areas');
    lifeAreas = data.areas || [];
    return lifeAreas;
  }

  const areaById = id => lifeAreas.find(a => a.id === id) || null;

  function areaDot(areaId) {
    const area = areaById(areaId);
    if (!area) return null;
    const dot = document.createElement('span');
    dot.className = 'area-dot';
    dot.style.background = area.color;
    dot.title = area.name;
    return dot;
  }

  async function pickArea(title, currentId) {
    const choice = await modal({
      title, select: [{value: '', label: 'None'}].concat(
        lifeAreas.map(a => ({value: a.id, label: a.name}))),
      value: currentId || '', confirmLabel: 'Save',
    });
    return choice;  // null if cancelled, '' for none
  }

  async function setProjectArea(p) {
    const areaId = await pickArea('Life area for "' + p.name + '"', p.area_id);
    if (areaId === null) return;
    const res = await jsonSend('/api/projects/' + p.id + '/area', {area_id: areaId}, 'PATCH');
    if (res.error) { toast(res.error, {error: true}); return; }
    await loadSidebar();
  }

  function areasCard() {
    const c = card('Life areas', '+ Add', async () => {
      const name = await askText('New life area', '', 'e.g. Family');
      if (!name) return;
      const res = await jsonSend('/api/areas', {name, color: '#8a8f98'});
      if (res.error) { toast(res.error, {error: true}); return; }
      await loadAreas();
      c.replaceWith(areasCard());
    });
    const hint = document.createElement('div');
    hint.className = 'muted area-hint';
    hint.textContent = 'Tag projects, to-dos, and habits so Today can show where your week went.';
    c.appendChild(hint);
    lifeAreas.forEach(a => {
      const row = document.createElement('div');
      row.className = 'area-row';
      const color = document.createElement('input');
      color.type = 'color';
      color.value = a.color;
      color.className = 'area-color';
      color.setAttribute('aria-label', a.name + ' color');
      const name = document.createElement('input');
      name.className = 'job-field-input';
      name.value = a.name;
      name.setAttribute('aria-label', 'Area name');
      const save = async () => {
        const res = await jsonSend('/api/areas/' + a.id,
          {name: name.value, color: color.value}, 'PATCH');
        if (res.error) { toast(res.error, {error: true}); name.value = a.name; return; }
        await loadSidebar();
      };
      color.addEventListener('change', save);
      name.addEventListener('change', save);
      const del = document.createElement('button');
      del.className = 'nav-btn';
      del.textContent = '×';
      del.setAttribute('aria-label', 'Delete ' + a.name);
      del.onclick = async () => {
        if (!await askConfirm('Delete area', 'Untag everything in "' + a.name
            + '" and remove the area?', 'Delete')) return;
        await api('/api/areas/' + a.id, {method: 'DELETE'});
        await loadSidebar();
        c.replaceWith(areasCard());
      };
      row.appendChild(color);
      row.appendChild(name);
      row.appendChild(del);
      c.appendChild(row);
    });
    return c;
  }
