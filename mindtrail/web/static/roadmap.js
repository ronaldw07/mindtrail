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

    // Denominator excludes rejected steps - a rejected step isn't
    // outstanding work, and counting it would mean a roadmap can never
    // reach 100%. Repeating steps (F4) never actually land in this list
    // as 'done': the server resets them to 'accepted' the moment they're
    // completed, so they always count as outstanding here rather than
    // needing special-casing on the client.
    const countable = nodesList.filter(n => n.status !== 'rejected');
    if (countable.length) {
      const doneCount = countable.filter(n => n.status === 'done').length;
      const progress = document.createElement('div');
      progress.className = 'roadmap-progress';
      const label = document.createElement('span');
      label.className = 'roadmap-progress-label';
      label.textContent = doneCount + ' of ' + countable.length + ' done';
      const bar = document.createElement('div');
      bar.className = 'roadmap-progress-bar';
      const fill = document.createElement('div');
      fill.className = 'roadmap-progress-fill';
      fill.style.width = Math.round((doneCount / countable.length) * 100) + '%';
      bar.appendChild(fill);
      progress.appendChild(label);
      progress.appendChild(bar);
      top.appendChild(progress);
    }

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
    // Ids, not just a class, so the palette's context-aware "Tidy
    // roadmap" / "Regenerate roadmap" actions (below) can trigger the
    // exact same button rather than duplicating its logic - the canvas
    // code itself is untouched otherwise.
    tidyBtn.id = 'roadmap-tidy-btn';
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
    regenBtn.id = 'roadmap-regenerate-btn';
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
        // A repeating step marked done doesn't land on 'done' - the
        // server resets it to 'accepted' with a new due date (see
        // RoadmapNodeStore.set_status), so the optimistic patch above
        // can disagree with what was actually saved. Re-render whenever
        // that happens so the canvas doesn't keep showing a status the
        // server didn't accept.
        const diverged = 'status' in patch && res.status !== patch.status;
        Object.assign(n, res);
        if (diverged) renderRoadmap(projectId, projectName, roadmap, nodesList);
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
        // Same divergence as updateNode's single-node path: a repeating
        // node in this batch may come back 'accepted' instead of 'done'.
        let diverged = false;
        results.forEach((res, i) => {
          if (res.error) { failed = true; Object.assign(targets[i], previous[i]); }
          else {
            if ('status' in patches[i] && res.status !== patches[i].status) diverged = true;
            Object.assign(targets[i], res);
          }
        });
        if (failed) toast('Some updates failed', {error: true});
        if (failed || diverged) renderRoadmap(projectId, projectName, roadmap, nodesList);
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
      // Marking a repeating step done doesn't reach 'done' - the server
      // resets it to 'accepted' and rolls the due date forward instead
      // (see RoadmapNodeStore.set_status), so weekly/daily habits don't
      // fill the canvas with a fresh clone every time.
      items.push({label: 'Repeats every…', run: async () => {
        const chosen = await modal({
          title: 'Repeats every', confirmLabel: 'Save',
          select: REPEAT_CHOICES.map(c => ({value: String(c.days), label: c.label})),
          value: String(n.repeat_days || 0),
        });
        if (chosen === null) return;
        updateNode(n, {repeat_days: Number(chosen)});
      }});
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
      if (n.repeat_days) {
        // Reuses .file-chip like the linked-memory chips below, rather
        // than inventing a repeat-specific chip style for one glyph.
        const repeat = document.createElement('span');
        repeat.className = 'file-chip';
        repeat.textContent = '\u21bb ' + repeatLabel(n.repeat_days);
        el.appendChild(repeat);
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

