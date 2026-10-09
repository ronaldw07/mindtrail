  // ---------- boot ----------
  // Restores whichever screen the user was last on. A persisted view
  // pointing at a project, roadmap, or chat that no longer exists (it
  // was deleted since the last visit) must never strand the user on a
  // broken screen, so every branch validates first and falls back to
  // Today silently rather than surfacing an error with nothing to do
  // about it.
  async function restoreLastView() {
    const last = prefs.get('lastView', null);
    if (!last) { openDashboardView(); return; }
    if (last.type === 'chat') {
      if (!last.id) { newChat(); return; }
      const data = await api('/api/conversations/' + last.id);
      if (data.error) { openDashboardView(); return; }
      await openConversation(last.id);
      return;
    }
    if (last.type === 'project') {
      const data = await api('/api/projects/' + last.id + '?background=1');
      if (data.error) { openDashboardView(); return; }
      await openProject(last.id);
      return;
    }
    if (last.type === 'roadmap') {
      const data = await api('/api/projects/' + last.id + '?background=1');
      if (data.error) { openDashboardView(); return; }
      await openRoadmapView(last.id, data.name);
      return;
    }
    if (last.type === 'profile') { await openProfileView(); return; }
    if (last.type === 'jobs') { await openJobsView(); return; }
    if (last.type === 'tasks') { await openTasksView(); return; }
    if (last.type === 'habits') { await openHabitsView(); return; }
    if (last.type === 'journal') { await openJournalView(); return; }
    if (last.type === 'week') { await openWeekView(); return; }
    if (last.type === 'people') { await openPeopleView(); return; }
    openDashboardView();
  }

  restoreLastView();
  resumeFocus();
  updateNav();
  loadSidebar();
  