
  // ---------- notifications ----------
  // Declarations only, loaded before app.js - see the note atop jobs.js.
  //
  // Mac notifications through the browser, so they only fire while Mind
  // Trail is open (it has no background process). Off until you turn them
  // on in Settings, which is also when the browser asks for permission.

  const NOTIFY_PREF = 'notificationsOn';
  const REMINDER_CHECK_MS = 15 * 60 * 1000;

  const notificationsSupported = () => 'Notification' in window;
  const notificationsEnabled = () =>
    notificationsSupported() && prefs.get(NOTIFY_PREF, false) && Notification.permission === 'granted';

  async function setNotifications(on) {
    if (!on) { prefs.set(NOTIFY_PREF, false); return false; }
    if (!notificationsSupported()) { toast('This browser can’t show notifications', {error: true}); return false; }
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    if (permission !== 'granted') {
      toast('Allow notifications for this page in your browser settings first', {error: true});
      return false;
    }
    prefs.set(NOTIFY_PREF, true);
    notify('Notifications are on', 'You’ll hear about interviews, assessments and focus sessions.', 'hello');
    return true;
  }

  function notify(title, body, tag) {
    if (!notificationsEnabled()) return;
    new Notification(title, {body, tag, icon: '/static/icon-192.png'});
  }

  // Each reminder fires once a day, however often this runs.
  function notifyOncePerDay(key, title, body) {
    const today = localISO(new Date());
    const seen = prefs.get('notified', {});
    if (seen[key] === today) return;
    const kept = Object.fromEntries(Object.entries(seen).filter(([, d]) => d === today));
    prefs.set('notified', {...kept, [key]: today});
    notify(title, body, key);
  }

  async function checkReminders() {
    if (!notificationsEnabled()) return;
    const today = localISO(new Date());
    const jobs = await api('/api/jobs');
    (jobs.applications || []).forEach(a => {
      if (a.deadline === today && (a.stage === 'oa' || a.stage === 'interview')) {
        notifyOncePerDay('job:' + a.id, (a.stage === 'oa' ? 'Assessment' : 'Interview') + ' today: ' + a.company,
                         a.role || 'Open Mind Trail for your prep notes');
      }
    });
    const people = await api('/api/people');
    (people.people || []).filter(p => p.due).forEach(p =>
      notifyOncePerDay('person:' + p.id, 'Time to reach out to ' + p.name, p.context || 'It’s been a while'));
  }

  function startReminders() {
    checkReminders();
    setInterval(checkReminders, REMINDER_CHECK_MS);
  }

  function notificationsCard() {
    const c = card('Notifications', null, null);
    c.appendChild(settingRow('Mac notifications', switchEl(notificationsEnabled(), async on => {
      const ok = await setNotifications(on);
      if (on && !ok) c.replaceWith(notificationsCard());
    }, 'Mac notifications'),
      'Interviews and assessments due today, people due a nudge, and when a focus session ends. '
      + 'Only while Mind Trail is open.'));
    return c;
  }
