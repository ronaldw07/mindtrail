"""The chat page shell markup.

CSS and JS live as real files under web/static/ (app.css, app.js), served
by chat_server.py — real files get syntax checking and editor tooling that
a string literal can't. This module is just the HTML shell that references
them.

Native prompt/confirm dialogs are deliberately not used anywhere: they
render in the OS light theme regardless of the page, which breaks the
dark UI. Everything goes through the in-page modal below.
"""

# Sidebar navigation: (title, items). Each item is (id, label, icon svg
# inner markup, tile color, badge key or ""). Tile colors are all dark
# enough that the white icon clears 3:1 (the floor for graphics).
SIDE_GROUPS = (
    (
        "",
        (
            ("open-today", "Today", "#d9480f",
             '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
             'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', ""),
        ),
    ),
    (
        "Library",
        (
            ("open-week", "Week", "#d70015",
             '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 3v4M16 3v4"/>', ""),
            ("open-tasks", "To-dos", "#0071e3", '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>', "tasks"),
            ("open-habits", "Habits", "#248a3d",
             '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18"/>'
             '<path d="M8 14h2"/><path d="M14 14h2"/>', ""),
            ("open-journal", "Journal", "#8944ab",
             '<path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="M8 9h8"/><path d="M8 13h6"/>', ""),
            ("open-people", "People", "#0e7c86",
             '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/>'
             '<path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14c2.2.6 3.5 2.8 3.5 6"/>', "people"),
            ("open-jobs", "Jobs", "#a0560a",
             '<rect x="3" y="7" width="18" height="13" rx="2"/>'
             '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>', "jobs"),
            ("open-practice", "Practice", "#1d6f5f",
             '<path d="M8 6l-5 6 5 6"/><path d="M16 6l5 6-5 6"/><path d="M14 4l-4 16"/>', "practice"),
            ("open-stories", "Stories", "#6e3fb5",
             '<path d="M12 6c-2-2-5-2.5-8-2v14c3-.5 6 0 8 2 2-2 5-2.5 8-2V4c-3-.5-6 0-8 2z"/>'
             '<path d="M12 6v14"/>', ""),
        ),
    ),
)

ICON_ATTRS = (
    'width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
)


def _side_nav() -> str:
    groups = []
    for title, items in SIDE_GROUPS:
        head = f'        <div class="side-title">{title}</div>\n' if title else ""
        buttons = "\n".join(
            f'        <button class="side-btn" id="{bid}" data-view="{bid[5:]}">'
            f'<span class="side-icon" style="--tile:{color}"><svg {ICON_ATTRS}>{paths}</svg></span>'
            f'<span class="side-label">{label}</span>'
            + (f'<span class="side-badge" data-badge="{badge}" hidden></span>' if badge else "")
            + "</button>"
            for bid, label, color, paths, badge in items
        )
        groups.append(f'      <div class="side-group">\n{head}{buttons}\n      </div>')
    return "\n".join(groups)


GEAR_ICON = (
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
    'a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3'
    'l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 '
    '1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 '
    '2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 '
    '1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'
)


CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1a1a1a">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <link rel="manifest" href="/static/manifest.webmanifest">
  <link rel="icon" href="/static/favicon.png">
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
  <link rel="stylesheet" href="/static/app.css">
  <link rel="stylesheet" href="/static/life.css">
  <link rel="stylesheet" href="/static/ui.css">
  <link rel="stylesheet" href="/static/theme.css">
  <script>
    // Theme before first paint, so a light-mode user never sees a dark flash.
    (function () {{
      var get = function (k, d) {{
        try {{ var v = localStorage.getItem('mindtrail:' + k); return v === null ? d : JSON.parse(v); }}
        catch (e) {{ return d; }}
      }};
      var mode = get('appearance', 'system');
      var dark = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
      var root = document.documentElement;
      root.dataset.theme = mode === 'system' ? (dark ? 'dark' : 'light') : mode;
      root.dataset.accent = get('accent', 'blue');
    }})();
  </script>
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <div class="brand" id="brand" title="Today">mindtrail</div>
      <div id="search-box">
        <input id="search-input" placeholder="Search your memory&#8230;"
               aria-label="Search everything stored">
        <div id="search-results"></div>
      </div>
{side_nav}
      <div id="tree"></div>
      <div id="side-foot">
        <button class="side-btn" id="open-profile" data-view="profile">
          <span class="side-icon plain"><svg {icon_attrs}>{gear}</svg></span>
          <span class="side-label">Settings</span></button>
      </div>
    </aside>
    <main>
      <div id="topbar">
        <div class="nav-capsule">
          <button class="nav-btn" id="toggle-sidebar" title="Toggle sidebar"
                  aria-label="Toggle sidebar">&#9707;</button>
          <button class="nav-btn" id="nav-back" title="Back" aria-label="Back"
                  disabled>&#8592;</button>
          <button class="nav-btn" id="nav-fwd" title="Forward" aria-label="Forward"
                  disabled>&#8594;</button>
        </div>
        <div id="breadcrumb">New chat</div>
        <button class="nav-btn quick-add" id="quick-add" title="Add" aria-label="Add"
                aria-haspopup="menu">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14"/></svg>
        </button>
      </div>
      <div id="log"></div>
      <div id="project-view"></div>
      <div id="roadmap-view"></div>
      <div id="profile-view"></div>
      <div id="dashboard-view"></div>
      <div id="jobs-view"></div>
      <div id="tasks-view"></div>
      <div id="habits-view"></div>
      <div id="journal-view"></div>
      <div id="week-view"></div>
      <div id="people-view"></div>
      <div id="practice-view"></div>
      <div id="stories-view"></div>
      <div id="composer">
        <form id="form">
          <button type="button" class="icon-btn" id="attach" title="Upload a PDF"
                  aria-label="Upload a PDF">+</button>
          <button type="button" class="icon-btn" id="mic" title="Dictate"
                  aria-label="Dictate">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 style="vertical-align:-3px;">
              <rect x="9" y="2" width="6" height="12" rx="3"/>
              <path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/>
            </svg>
          </button>
          <input id="input" autocomplete="off" placeholder="Ask something..." autofocus>
          <button class="send" id="send">Ask</button>
        </form>
        <div id="status"></div>
        <input type="file" id="file" accept="application/pdf" style="display:none">
      </div>
    </main>
  </div>
  <div id="menu"></div>
  <div id="overlay"></div>
  <div id="toasts"></div>
  <div id="palette"></div>
  <div id="shortcuts"></div>

  <script src="/static/ui.js"></script>
  <script src="/static/jobs.js"></script>
  <script src="/static/life.js"></script>
  <script src="/static/today.js"></script>
  <script src="/static/tasks.js"></script>
  <script src="/static/settings.js"></script>
  <script src="/static/notify.js"></script>
  <script src="/static/recruit.js"></script>
  <script src="/static/stories.js"></script>
  <script src="/static/practice.js"></script>
  <script src="/static/focus.js"></script>
  <script src="/static/review.js"></script>
  <script src="/static/admin.js"></script>
  <script src="/static/core.js"></script>
  <script src="/static/sidebar.js"></script>
  <script src="/static/chat.js"></script>
  <script src="/static/project.js"></script>
  <script src="/static/roadmap.js"></script>
  <script src="/static/profile.js"></script>
  <script src="/static/composer.js"></script>
  <script src="/static/palette.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>""".format(side_nav=_side_nav(), icon_attrs=ICON_ATTRS, gear=GEAR_ICON)
