  // ---------- search ----------
  // Semantic search over everything stored - the app's core retrieval,
  // otherwise only reachable indirectly through a follow-up question.

  (() => {
    const input = $('search-input');
    const results = $('search-results');
    let debounceTimer = null;
    let latestQuery = '';
    // Registered with the shared layer stack only while results are
    // actually showing, so Escape closes this dropdown - and only this
    // dropdown, not whatever else happens to be open underneath it -
    // exactly when there's something here to close.
    let popSearchLayer = null;

    function closeResults() {
      results.classList.remove('open');
      results.innerHTML = '';
      if (popSearchLayer) { popSearchLayer(); popSearchLayer = null; }
    }

    function openResults() {
      results.classList.add('open');
      if (!popSearchLayer) {
        popSearchLayer = pushLayer(() => { input.blur(); closeResults(); });
      }
    }

    function renderResults(items, query) {
      results.innerHTML = '';
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.style.padding = '0.5rem 0.6rem';
        empty.textContent = 'No matches for "' + query + '".';
        results.appendChild(empty);
        openResults();
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
        if (r.kind === 'journal') actions.style.display = 'none';
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
          if (r.kind === 'journal') openJournalView(r.topic);
          else if (r.conversation_id) {
            showChatView();
            openConversation(r.conversation_id);
          }
        });
        results.appendChild(item);
      });
      openResults();
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

    // Escape is handled by the layer stack (see openResults/closeResults
    // above), not here - a local element-level listener would fire
    // regardless of whether this dropdown is the topmost open thing.

    document.addEventListener('click', e => {
      if (!e.target.closest('#search-box')) closeResults();
    });
  })();

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

