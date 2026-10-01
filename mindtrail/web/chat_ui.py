"""The chat page shell markup.

CSS and JS live as real files under web/static/ (app.css, app.js), served
by chat_server.py — real files get syntax checking and editor tooling that
a string literal can't. This module is just the HTML shell that references
them.

Native prompt/confirm dialogs are deliberately not used anywhere: they
render in the OS light theme regardless of the page, which breaks the
dark UI. Everything goes through the in-page modal below.
"""

# Sidebar buttons: (id, label, svg inner markup), grouped - navigation,
# capture, then settings - with a small gap between groups.
SIDE_GROUPS = (
    (
        ("open-today", "Today",
         '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
         'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
        ("open-tasks", "To-dos", '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>'),
        ("open-habits", "Habits",
         '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18"/>'
         '<path d="M8 14h2"/><path d="M14 14h2"/>'),
        ("open-journal", "Journal",
         '<path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="M8 9h8"/><path d="M8 13h6"/>'),
        ("open-jobs", "Jobs",
         '<rect x="3" y="7" width="18" height="13" rx="2"/>'
         '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
    ),
    (
        ("add-note", "Note",
         '<path d="M4 19.5V6a2 2 0 0 1 2-2h9l5 5v10.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/>'
         '<path d="M14 4v5h5"/><path d="M8 13h8"/><path d="M8 17h5"/>'),
        ("save-url", "Save a link",
         '<path d="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07l-1.5 1.5"/>'
         '<path d="M14 11a5 5 0 0 0-7.07 0l-2.83 2.83a5 5 0 0 0 7.07 7.07l1.5-1.5"/>'),
    ),
    (
        ("open-profile", "Profile",
         '<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>'),
        ("export-data", "Export",
         '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
         '<path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>'),
    ),
)


def _side_nav() -> str:
    groups = []
    for group in SIDE_GROUPS:
        buttons = "\n".join(
            f'        <button class="side-btn" id="{bid}">'
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'style="vertical-align:-2px;margin-right:0.4rem;">{paths}</svg>{label}</button>'
            for bid, label, paths in group
        )
        groups.append(f'      <div class="side-group">\n{buttons}\n      </div>')
    return "\n".join(groups)


CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <link rel="stylesheet" href="/static/app.css">
  <link rel="stylesheet" href="/static/life.css">
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
    </aside>
    <main>
      <div id="topbar">
        <button class="nav-btn" id="toggle-sidebar" title="Toggle sidebar"
                aria-label="Toggle sidebar">&#9707;</button>
        <button class="nav-btn" id="nav-back" title="Back" aria-label="Back"
                disabled>&#8592;</button>
        <button class="nav-btn" id="nav-fwd" title="Forward" aria-label="Forward"
                disabled>&#8594;</button>
        <div id="breadcrumb">New chat</div>
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

  <script src="/static/jobs.js"></script>
  <script src="/static/life.js"></script>
  <script src="/static/today.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>""".format(side_nav=_side_nav())
