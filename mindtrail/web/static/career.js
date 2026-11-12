  // ---------- career: the career journey, jobs and practice in one place ----------
  // Reached from the Career box on Journey; there's no sidebar row.
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  // Career in the sidebar opens whichever of the three you used last; the
  // switch at the top of each moves between them.

  const CAREER_TABS = [{value: 'plan', label: 'Plan'}, {value: 'jobs', label: 'Jobs'},
                       {value: 'practice', label: 'Practice'}];

  function openCareerView() {
    const tab = prefs.get('careerTab', 'jobs');
    if (tab === 'practice') return openPracticeView();
    if (tab === 'plan') return openCareerPlan();
    return openJobsView();
  }

  // Plan is the career journey's timeline: open it, switching to it first
  // if another journey is the one open. With no career journey yet, the
  // Journey page offers to make one.
  async function openCareerPlan() {
    const data = await api('/api/journey');
    const career = (data.journeys || []).find(j => j.kind === 'career');
    if (career && career.project_id !== data.project_id) {
      await jsonSend('/api/journey/select', {project_id: career.project_id});
    }
    await openJourneyView({detail: true});
  }

  function careerSwitch(active) {
    return segmented(CAREER_TABS, active, v => {
      prefs.set('careerTab', v);
      openCareerView();
    }, 'Career');
  }

  // The title row for Jobs and Practice: a way back to Journeys, then
  // "Career" with the switch beside it.
  function careerTabs(active) {
    const wrap = tEl('div');
    wrap.appendChild(journeyCrumb());
    const bar = tEl('div', 'career-tabs');
    bar.appendChild(tEl('div', 'proj-title', 'Career'));
    bar.appendChild(careerSwitch(active));
    wrap.appendChild(bar);
    return wrap;
  }
