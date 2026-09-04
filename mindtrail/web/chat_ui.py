"""The chat page shell markup.

CSS and JS live as real files under web/static/ (app.css, app.js), served
by chat_server.py — real files get syntax checking and editor tooling that
a string literal can't. This module is just the HTML shell that references
them.

Native prompt/confirm dialogs are deliberately not used anywhere: they
render in the OS light theme regardless of the page, which breaks the
dark UI. Everything goes through the in-page modal below.
"""

CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <link rel="stylesheet" href="/static/app.css">
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
      <button class="side-btn" id="open-profile">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             style="vertical-align:-2px;margin-right:0.4rem;">
          <circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
        </svg>Profile
      </button>
      <button class="side-btn" id="add-note">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             style="vertical-align:-2px;margin-right:0.4rem;">
          <path d="M4 19.5V6a2 2 0 0 1 2-2h9l5 5v10.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/>
          <path d="M14 4v5h5"/><path d="M8 13h8"/><path d="M8 17h5"/>
        </svg>Note
      </button>
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

  <script src="/static/app.js"></script>
</body>
</html>"""
