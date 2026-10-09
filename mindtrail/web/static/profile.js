  // ---------- profile ----------

  async function openProfileView(opts) {
    opts = opts || {};
    currentProject = null;
    current = null;
    showProfileView();
    $('breadcrumb').textContent = 'Settings';
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
    title.textContent = 'Settings';
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

    main.appendChild(setupCard());
    main.appendChild(appearanceCard());
    main.appendChild(aboutCard);
    main.appendChild(areasCard());
    main.appendChild(canvasCard());
    main.appendChild(githubCard());
    main.appendChild(backupsCard());
    main.appendChild(dataCard());
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
  $('open-jobs').onclick = () => openJobsView();
  $('open-today').onclick = () => openDashboardView();
  $('open-week').onclick = () => openWeekView();
  $('open-people').onclick = () => openPeopleView();
  $('open-tasks').onclick = () => openTasksView();
  $('open-habits').onclick = () => openHabitsView();
  $('open-journal').onclick = () => openJournalView();
  $('quick-add').onclick = e => showMenuFrom(e.currentTarget, [
    {label: 'New to-do', run: quickAddTask},
    {label: 'New note', run: addNote},
    {label: 'Save a link', run: saveUrl},
    {label: 'New chat', run: () => newChat()},
  ]);

  // Notes were CLI-only until now, and the CLI version stores them with
  // no conversation attached - unreachable from the browser even after
  // the fact. This always creates one, so a note shows up in the
  // sidebar exactly like a chat or a document would.
  //
  // A named function rather than an inline handler so the command
  // palette's "New note" action (below) can call the exact same flow
  // instead of simulating a click on the sidebar button.
  async function addNote() {
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
  }

  // Same shape as addNote above: search and PDF upload were the only two
  // ways a page's content reached memory before this - a URL a user
  // already has open can now be handed straight to the server instead of
  // being re-typed into a note.
  //
  // A named function, matching addNote, so the palette's "Save a link"
  // action (below) reuses this instead of simulating a click.
  async function saveUrl() {
    const url = await modal({
      title: 'Save a link', input: true, inputType: 'url',
      placeholder: 'https://…', confirmLabel: 'Save',
    });
    if (!url) return;
    const res = await jsonSend('/api/save-url', {url});
    if (res.error) { toast(res.error, {error: true}); return; }
    await loadSidebar();
    showChatView();
    await openConversation(res.conversation_id);
    toast('Link saved');
  }

  // Backs up the whole database plus profile to plain markdown on disk -
  // the CLI's `mindtrail export` had no browser entry point until now, so
  // the backup story was invisible to anyone who never reads --help.
  async function exportData(btnEl) {
    // The button that asked (Settings → Data), when there is one. setButtonBusy
    // wipes a button's children for the spinner, so the original markup is
    // kept aside and reattached afterwards.
    const btn = btnEl || null;
    const original = btn ? Array.from(btn.childNodes) : [];
    if (btn) setButtonBusy(btn, 'Exporting…');
    try {
      const res = await jsonSend('/api/export', {});
      if (res.error) { toast(res.error, {error: true}); return; }
      toast('Exported ' + res.files + ' file' + (res.files === 1 ? '' : 's') +
            ' to ' + res.path);
    } catch (err) {
      toast('Export failed', {error: true});
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '';
        original.forEach(node => btn.appendChild(node));
      }
    }
  }

