"""The chat page markup, styles, and client script.

Kept in its own module so chat_server.py stays about HTTP routing rather
than being mostly a large string literal.

Native prompt/confirm dialogs are deliberately not used anywhere: they
render in the OS light theme regardless of the page, which breaks the
dark UI. Everything goes through the in-page modal below.
"""

CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <style>
    :root {
      --bg: #1a1a1a;
      --surface: #242424;      /* raised above --bg so cards read as a
                                   surface rather than a hairline outline */
      --accent: #4f46e5;
      --label: #ececec;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, system-ui, sans-serif;
           background: var(--bg); color: var(--label); height: 100vh; overflow: hidden;
           -webkit-font-smoothing: antialiased; }
    #app { display: flex; height: 100vh; }
    /* Every interactive element gets one consistent ring on keyboard
       focus - previously nothing in the app had any visible focus
       state at all. Mouse clicks don't trigger :focus-visible, so this
       costs nothing visually for the common case. */
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

    /* --- sidebar --- */
    #sidebar { width: 275px; background: #171717; border-right: 1px solid #2a2a2a;
               display: flex; flex-direction: column; flex-shrink: 0;
               overflow: hidden; transition: width 0.16s ease, border-width 0.16s ease; }
    #sidebar.collapsed { width: 0; border-right-width: 0; }
    .brand { padding: 1rem 1rem 0.75rem; font-weight: 600; letter-spacing: 0.01em;
             white-space: nowrap; cursor: pointer; }
    .side-btn { display: block; width: calc(100% - 1rem); margin: 0 0.5rem 0.5rem;
                text-align: left; padding: 0.45rem 0.6rem; border-radius: 6px; border: none;
                background: transparent; color: #b8b8b8; font-size: 0.85rem; cursor: pointer; }
    .side-btn:hover { background: #212121; color: #fff; }

    /* --- search --- */
    #search-box { position: relative; padding: 0 0.75rem 0.6rem; }
    #search-input { width: 100%; background: #1f1f1f; border: 1px solid #2e2e2e;
                    border-radius: 7px; color: #ececec; padding: 0.4rem 0.6rem;
                    font-size: 0.83rem; outline: none; }
    #search-input:focus { border-color: #4f46e5; }
    #search-input::placeholder { color: #868686; }
    #search-results { position: absolute; top: calc(100% - 0.3rem); left: 0.75rem;
                      right: 0.75rem; display: none; background: #212121;
                      border: 1px solid #333; border-radius: 8px; padding: 0.3rem;
                      max-height: 60vh; overflow-y: auto; z-index: 50;
                      box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
    #search-results.open { display: block; }
    .sr-item { padding: 0.5rem 0.6rem; border-radius: 6px; cursor: pointer; }
    .sr-item:hover { background: #2a2a2a; }
    .sr-title { font-size: 0.84rem; color: #ececec; font-weight: 500;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sr-sub { font-size: 0.74rem; color: #868686; margin-top: 0.15rem;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #tree { flex: 1; overflow-y: auto; padding: 0 0.5rem 1.5rem; }

    .section { display: flex; align-items: center; gap: 0.35rem;
               padding: 0.75rem 0.6rem 0.35rem; font-size: 0.7rem;
               text-transform: uppercase; letter-spacing: 0.05em; color: #868686;
               user-select: none; }
    .section.clickable { cursor: pointer; border-radius: 6px; }
    .section.clickable:hover { color: #9a9a9a; }
    .section .label { flex: 1; }
    .sec-caret { font-size: 0.95rem; width: 1rem; color: #868686; }
    .add { border: none; background: transparent; color: #7d7d7d; cursor: pointer;
           font-size: 1.05rem; line-height: 1; padding: 0.1rem 0.3rem;
           border-radius: 5px; }
    .add:hover { background: #2a2a2a; color: #fff; }
    .empty-hint { padding: 0.35rem 0.75rem 0.5rem; font-size: 0.78rem; color: #868686; }

    .project { margin-bottom: 0.1rem; }
    .project-head { display: flex; align-items: center; gap: 0.35rem;
                    padding: 0.4rem 0.6rem; border-radius: 6px; cursor: pointer;
                    color: #d0d0d0; font-size: 0.85rem; font-weight: 500; }
    .project-head:hover { background: #212121; }
    .caret { font-size: 0.95rem; color: #868686; width: 1rem; }
    .chat { display: flex; align-items: center; gap: 0.35rem; padding: 0.4rem 0.6rem;
            border-radius: 6px; cursor: pointer; font-size: 0.84rem; color: #b8b8b8; }
    .chat:hover { background: #212121; }
    .chat.active { background: #2b2b2b; color: #fff; }
    .chat.unread .chat-title { font-weight: 700; color: #fff; }
    .chat-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: #4f8ef7; flex-shrink: 0; }
    .pin { display: inline-flex; margin-right: 0.3rem; color: #868686; flex-shrink: 0; }
    .menu-btn { opacity: 0; border: none; background: transparent; color: #999;
                cursor: pointer; font-size: 0.95rem; padding: 0 0.2rem; line-height: 1; }
    .chat:hover .menu-btn, .project-head:hover .menu-btn { opacity: 1; }
    .nested { margin-left: 0.85rem; }

    /* --- context menu --- */
    #menu { position: fixed; background: #262626; border: 1px solid #3a3a3a;
            border-radius: 8px; padding: 0.3rem; display: none; z-index: 60;
            min-width: 175px; box-shadow: 0 6px 22px rgba(0,0,0,0.45); }
    #menu div { padding: 0.45rem 0.7rem; border-radius: 5px; cursor: pointer;
                font-size: 0.83rem; color: #ddd; }
    #menu div:hover { background: #333; }
    #menu .danger { color: #f87171; }
    #menu hr { border: none; border-top: 1px solid #3a3a3a; margin: 0.25rem 0; }

    /* --- modal (replaces native prompt/confirm) --- */
    #overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.62);
               display: none; align-items: center; justify-content: center; z-index: 100; }
    #overlay.open { display: flex; }
    .modal { background: #212121; border: 1px solid #383838; border-radius: 12px;
             padding: 1.25rem; width: 390px; max-width: calc(100vw - 2rem);
             box-shadow: 0 18px 50px rgba(0,0,0,0.55); }
    .modal h3 { margin: 0 0 0.75rem; font-size: 0.95rem; font-weight: 600; color: #f2f2f2; }
    .modal p { margin: 0 0 1rem; font-size: 0.86rem; color: #a8a8a8; line-height: 1.55;
               white-space: pre-wrap; }
    .modal input { width: 100%; padding: 0.6rem 0.75rem; border-radius: 8px;
                   border: 1px solid #3a3a3a; background: #191919; color: #ececec;
                   font-size: 0.9rem; outline: none; }
    .modal input:focus { border-color: #4f46e5; }
    .modal-textarea { width: 100%; min-height: 140px; padding: 0.6rem 0.75rem;
                      border-radius: 8px; border: 1px solid #3a3a3a; background: #191919;
                      color: #ececec; font-size: 0.9rem; font-family: inherit;
                      line-height: 1.5; resize: vertical; outline: none; }
    .modal-textarea:focus { border-color: #4f46e5; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem;
                     margin-top: 1.1rem; }
    .modal button { padding: 0.5rem 1.05rem; border-radius: 7px; border: none;
                    font-size: 0.85rem; cursor: pointer; }
    .btn-ghost { background: transparent; color: #a0a0a0; }
    .btn-ghost:hover { background: #2e2e2e; color: #fff; }
    .btn-primary { background: #4f46e5; color: #fff; }
    .btn-primary:hover { background: #5b52ea; }
    .btn-danger { background: #b91c1c; color: #fff; }
    .btn-danger:hover { background: #cf2222; }

    /* --- main --- */
    main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    #topbar { display: flex; align-items: center; gap: 0.15rem; padding: 0.6rem 1.25rem;
              border-bottom: 1px solid #2a2a2a; flex-shrink: 0; }
    .nav-btn { background: transparent; border: none; color: #9a9a9a; cursor: pointer;
               font-size: 0.95rem; line-height: 1; padding: 0.35rem 0.45rem;
               border-radius: 6px; }
    .nav-btn:hover:not(:disabled) { background: #2a2a2a; color: #fff; }
    .nav-btn:disabled { opacity: 0.3; cursor: default; }
    #breadcrumb { font-size: 0.85rem; color: #999; margin-left: 0.6rem;
                  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #breadcrumb b { color: #ececec; font-weight: 600; }
    #log { flex: 1; overflow-y: auto; padding: 1.5rem 2rem; max-width: 760px;
           margin: 0 auto; width: 100%; }
    .turn { margin-bottom: 1.6rem; }
    .user-line { display: flex; justify-content: flex-end; margin-bottom: 0.6rem; }
    .user-line span { background: #2a2a2a; padding: 0.5rem 0.9rem; border-radius: 14px;
                       max-width: 80%; white-space: pre-wrap; font-size: 0.95rem; }
    .assistant-text { line-height: 1.65; font-size: 0.97rem; }
    .assistant-text.pending { color: #888; font-style: italic; white-space: pre-wrap; }
    .assistant-text p { margin: 0 0 0.85rem; }
    .assistant-text p:last-child { margin-bottom: 0; }
    .assistant-text h3, .assistant-text h4, .assistant-text h5 {
      margin: 1.15rem 0 0.5rem; font-size: 1rem; font-weight: 600; color: #f4f4f4; }
    .assistant-text h3:first-child, .assistant-text h4:first-child { margin-top: 0; }
    .assistant-text ul, .assistant-text ol { margin: 0 0 0.85rem; padding-left: 1.35rem; }
    .assistant-text li { margin-bottom: 0.35rem; }
    .assistant-text strong { color: #fff; font-weight: 600; }
    .assistant-text code { background: #2a2a2a; border-radius: 4px; padding: 0.1rem 0.35rem;
                           font-size: 0.88em; font-family: ui-monospace, monospace; }
    .assistant-text a { color: #8ab4f8; }
    .assistant-text blockquote { margin: 0 0 0.85rem; padding-left: 0.8rem;
                                 border-left: 3px solid #3a3a3a; color: #b8b8b8; }
    .assistant-text table { border-collapse: collapse; width: 100%;
                            margin: 0 0 0.95rem; font-size: 0.9rem; display: block;
                            overflow-x: auto; }
    .assistant-text th, .assistant-text td { border: 1px solid #333; padding: 0.45rem 0.6rem;
                                             text-align: left; vertical-align: top; }
    .assistant-text th { background: #242424; color: #f0f0f0; font-weight: 600; }
    .assistant-text hr { border: none; border-top: 1px solid #2f2f2f; margin: 1.1rem 0; }
    .meta { margin-top: 0.6rem; font-size: 0.78rem; color: #888; }
    .meta a { color: #8ab4f8; display: block; text-decoration: none; }
    .meta a:hover { text-decoration: underline; }
    .kind-tag { display: inline-block; font-size: 0.68rem; text-transform: uppercase;
                letter-spacing: 0.03em; color: #999; margin-bottom: 0.3rem; }
    .empty-state { color: #6a6a6a; font-size: 0.9rem; text-align: center;
                   margin-top: 22vh; line-height: 1.7; }

    /* --- project detail --- */
    #project-view, #profile-view, #dashboard-view {
      flex: 1; overflow-y: auto; display: none; padding: 1.75rem 2rem;
    }
    #project-view.open, #profile-view.open, #dashboard-view.open { display: block; }
    #roadmap-view { flex: 1; display: none; overflow: hidden; flex-direction: column; }
    #roadmap-view.open { display: flex; }

    /* --- dashboard --- */
    .dash-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem;
                 max-width: 1180px; margin: 0 auto; align-items: start; }
    .dash-item { padding: 0.6rem 0; border-bottom: 1px solid #292929; cursor: pointer; }
    .dash-item:last-child { border-bottom: none; padding-bottom: 0; }
    .dash-item:hover .dash-item-title { color: #fff; }
    .dash-item-title { font-size: 0.88rem; font-weight: 600; color: #ececec; }
    .dash-item-sub { font-size: 0.78rem; color: #868686; margin-top: 0.15rem; }
    .proj-layout { display: flex; gap: 1.75rem; max-width: 1180px; margin: 0 auto;
                   align-items: flex-start; }
    .proj-main { flex: 1; min-width: 0; }
    .proj-rail { width: 330px; flex-shrink: 0; }
    .proj-title { font-size: 1.55rem; font-weight: 600; margin: 0 0 1.25rem; }
    /* Raised above --bg (#1a1a1a vs #242424, was #1f1f1f - a 1.06:1
       contrast that made the "card" invisible as a surface, carried
       only by its border) plus a real elevation shadow and a 4%-white
       inset top edge, the macOS trick for a lit edge in dark mode. */
    .card { background: var(--surface); border: 1px solid #333; border-radius: 10px;
            padding: 1rem 1.1rem; margin-bottom: 1rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 0 0 0.5px rgba(255,255,255,0.04) inset; }
    .card h4 { margin: 0 0 0.7rem; font-size: 0.72rem; text-transform: uppercase;
               letter-spacing: 0.06em; color: #8a8a8a; display: flex;
               align-items: center; gap: 0.4rem; }
    .card h4 .spacer { flex: 1; }
    .card-btn { border: none; background: transparent; color: #8a8a8a; cursor: pointer;
                font-size: 0.8rem; padding: 0.15rem 0.4rem; border-radius: 5px; }
    .card-btn:hover { background: #2c2c2c; color: #fff; }
    .hl { padding: 0.65rem 0; border-bottom: 1px solid #292929; }
    .hl:last-child { border-bottom: none; padding-bottom: 0; }
    .hl-head { font-size: 0.88rem; font-weight: 600; color: #ececec;
               margin-bottom: 0.2rem; }
    .hl-detail { font-size: 0.82rem; color: #a5a5a5; line-height: 1.5; }
    .hl-source { font-size: 0.73rem; color: #868686; margin-top: 0.25rem; }
    .stamp { font-size: 0.72rem; color: #6a6a6a; margin-top: 0.6rem; }
    .instructions-box { width: 100%; min-height: 84px; resize: vertical;
                        background: #191919; border: 1px solid #333; border-radius: 8px;
                        color: #dcdcdc; font-size: 0.84rem; padding: 0.6rem 0.7rem;
                        font-family: inherit; line-height: 1.5; outline: none; }
    .instructions-box:focus { border-color: #4f46e5; }
    .proj-chat { display: flex; align-items: center; gap: 0.5rem; padding: 0.7rem 0.2rem;
                 border-bottom: 1px solid #262626; cursor: pointer; font-size: 0.9rem; }
    .proj-chat:hover { color: #fff; }
    .proj-chat .when { color: #757575; font-size: 0.78rem; }
    .file-chip { display: inline-block; background: #262626; border: 1px solid #333;
                 border-radius: 6px; padding: 0.3rem 0.6rem; font-size: 0.8rem;
                 color: #c5c5c5; margin: 0.2rem 0.3rem 0.2rem 0; }
    .muted { color: #868686; font-size: 0.84rem; }

    /* --- roadmap canvas --- */
    #roadmap-top { display: flex; align-items: center; gap: 0.6rem; padding: 0.8rem 1.25rem;
                   border-bottom: 1px solid #2a2a2a; flex-shrink: 0; }
    #roadmap-top .goal { flex: 1; font-size: 0.92rem; font-weight: 600; }
    #roadmap-body { flex: 1; display: flex; overflow: hidden; min-height: 0; }
    /* Pan/zoom viewport: the canvas is transformed rather than scrolled,
       so a scaled canvas can't disagree with the scrollbars about how
       big it is. Panning is handled in JS on the background. */
    #canvas-scroll { flex: 1; position: relative; overflow: hidden;
                     cursor: grab; touch-action: none; }
    #canvas-scroll.panning { cursor: grabbing; }
    #canvas { position: absolute; top: 0; left: 0; width: 2400px; height: 1600px;
              transform-origin: 0 0; }
    #zoom-controls { position: absolute; right: 0.9rem; bottom: 0.9rem; z-index: 5;
                     display: flex; align-items: center; gap: 0.25rem; padding: 0.25rem;
                     background: #212121cc; border: 1px solid #333; border-radius: 8px;
                     backdrop-filter: blur(8px); }
    #zoom-controls button { border: none; background: transparent; color: #c5c5c5;
                            cursor: pointer; font-size: 0.85rem; border-radius: 5px;
                            padding: 0.2rem 0.5rem; line-height: 1.5; }
    #zoom-controls button:hover { background: #333; color: #fff; }
    #zoom-level { font-size: 0.75rem; color: #868686; min-width: 3.1rem;
                  text-align: center; user-select: none; }
    #canvas svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                  pointer-events: none; }
    #canvas svg path { fill: none; stroke: #3d3d3d; stroke-width: 1.5; }

    /* --- roadmap chat --- */
    #roadmap-chat { width: 340px; flex-shrink: 0; border-left: 1px solid #2a2a2a;
                    background: #181818; display: flex; flex-direction: column; }
    #roadmap-chat-log { flex: 1; overflow-y: auto; padding: 1rem; display: flex;
                        flex-direction: column; gap: 0.85rem; }
    .rc-msg { font-size: 0.85rem; line-height: 1.5; max-width: 92%; }
    .rc-msg.user { align-self: flex-end; color: #d8d8ff; background: #262a4a;
                   border-radius: 10px; padding: 0.45rem 0.65rem; }
    .rc-msg.assistant { align-self: flex-start; color: #ececec; }
    .rc-action { background: #212121; border: 1px solid #333; border-radius: 8px;
                 padding: 0.55rem 0.7rem; font-size: 0.8rem; margin-top: 0.5rem;
                 align-self: flex-start; max-width: 92%; }
    .rc-action-label { margin-bottom: 0.45rem; color: #dcdcdc; }
    .rc-action-buttons { display: flex; gap: 0.4rem; }
    .rc-action-buttons button { font-size: 0.72rem; padding: 0.2rem 0.55rem; border-radius: 5px;
                                border: 1px solid #3a3a3a; background: #2a2a2a; color: #ccc;
                                cursor: pointer; }
    .rc-action-buttons button:hover { background: #333; color: #fff; }
    .rc-action-buttons button.rc-accept:hover { border-color: #4f46e5; }
    .rc-action-buttons button.rc-reject:hover { border-color: #b91c1c; }
    .rc-action.resolved { opacity: 0.55; }
    .rc-action-resolved-note { font-size: 0.76rem; color: #868686; }
    #roadmap-chat-form { display: flex; gap: 0.4rem; padding: 0.75rem; flex-shrink: 0;
                         border-top: 1px solid #2a2a2a; }
    #roadmap-chat-input { flex: 1; background: #191919; border: 1px solid #333;
                          border-radius: 8px; color: #ececec; padding: 0.5rem 0.65rem;
                          font-size: 0.85rem; outline: none; }
    #roadmap-chat-input:focus { border-color: #4f46e5; }

    /* --- compact assistant card (project, profile) --- */
    .rc-log { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column;
              gap: 0.7rem; margin-bottom: 0.6rem; }
    .rc-form { display: flex; gap: 0.4rem; }
    .rc-input { flex: 1; background: #191919; border: 1px solid #333; border-radius: 8px;
                color: #ececec; padding: 0.45rem 0.6rem; font-size: 0.82rem; outline: none; }
    .rc-input:focus { border-color: #4f46e5; }
    .node { position: absolute; width: 220px; background: #212121; border: 1px solid #3a3a3a;
            border-radius: 10px; padding: 0.7rem 0.85rem 2rem; cursor: grab; font-size: 0.85rem;
            box-shadow: 0 4px 14px rgba(0,0,0,0.3); user-select: none; }
    .node:active { cursor: grabbing; }
    .node.proposed { border-style: dashed; opacity: 0.85; }
    .node.accepted { border-color: #4f46e5; }
    .node.done { border-color: #2f9e5c; }
    .node.done .node-title { text-decoration: line-through; color: #8fae9c; }
    .node.rejected { opacity: 0.45; border-style: dotted; }
    .node.rejected .node-title { text-decoration: line-through; }
    .node-title { font-weight: 600; color: #ececec; margin-bottom: 0.3rem; }
    .node-detail { color: #a5a5a5; font-size: 0.78rem; line-height: 1.4; margin-bottom: 0.4rem; }
    .node-note { font-size: 0.76rem; color: #cdd8ff; background: #1e2340; border-radius: 6px;
                 padding: 0.3rem 0.5rem; margin-bottom: 0.4rem; }
    .node-actions { display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
    .node-actions button { font-size: 0.72rem; padding: 0.2rem 0.5rem; border-radius: 5px;
                            border: 1px solid #3a3a3a; background: #2a2a2a; color: #ccc;
                            cursor: pointer; }
    .node-actions button:hover { background: #333; color: #fff; }
    .node-actions button.accept:hover { border-color: #4f46e5; }
    .node-actions button.reject:hover { border-color: #b91c1c; }
    .node-check { width: 15px; height: 15px; accent-color: #2f9e5c; cursor: pointer; }
    .node-check-label { font-size: 0.76rem; color: #a5a5a5; cursor: pointer; }
    /* Pinned to the same corner on every card, separate from the
       accept/reject/checkbox row, so it's always where a person expects
       an overflow menu to be regardless of how much text is above it. */
    .node-more { position: absolute; bottom: 0.5rem; right: 0.6rem; border: 1px solid #3a3a3a;
                 background: #2a2a2a; color: #ccc; border-radius: 5px; padding: 0.1rem 0.5rem;
                 font-size: 0.85rem; line-height: 1.4; cursor: pointer; }
    .node-more:hover { background: #333; color: #fff; }
    #roadmap-empty { padding: 2rem; max-width: 480px; }
    #roadmap-empty input { width: 100%; padding: 0.6rem 0.75rem; border-radius: 8px;
                            border: 1px solid #333; background: #191919; color: #ececec;
                            font-size: 0.9rem; margin: 0.6rem 0; }

    /* --- profile view --- */
    #profile-view textarea { width: 100%; min-height: 220px; background: #191919;
                             border: 1px solid #333; border-radius: 8px; color: #dcdcdc;
                             font-size: 0.9rem; padding: 0.8rem; font-family: inherit;
                             line-height: 1.55; resize: vertical; outline: none; }
    #profile-view textarea:focus { border-color: #4f46e5; }

    /* --- priority on highlights --- */
    .hl.now { border-left: 3px solid #4f8ef7; padding-left: 0.65rem; }
    .hl { cursor: pointer; }
    .hl:hover .hl-head { color: #fff; text-decoration: underline; }
    .tier { display: inline-block; font-size: 0.62rem; text-transform: uppercase;
            letter-spacing: 0.07em; padding: 0.1rem 0.4rem; border-radius: 4px;
            margin-right: 0.4rem; vertical-align: 1px; }
    .tier.now   { background: #1e3a6b; color: #a9c9ff; }
    .tier.next  { background: #2d2d2d; color: #b5b5b5; }
    .tier.later { background: #262626; color: #8a8a8a; }
    .stale-note { font-size: 0.75rem; color: #c8a44a; margin-bottom: 0.5rem; }

    /* --- toasts --- */
    #toasts { position: fixed; bottom: 1.25rem; left: 50%; transform: translateX(-50%);
              display: flex; flex-direction: column; gap: 0.5rem; z-index: 200;
              align-items: center; }
    .toast { background: #262626; border: 1px solid #3a3a3a; border-radius: 9px;
             padding: 0.6rem 0.9rem; font-size: 0.85rem; color: #ececec;
             box-shadow: 0 8px 26px rgba(0,0,0,0.5); display: flex;
             align-items: center; gap: 0.75rem; min-width: 280px; }
    .toast.err { border-color: #7f2b2b; }
    .toast .msg { flex: 1; }
    .toast .undo { background: transparent; border: 1px solid #4a4a4a; color: #cdd8ff;
                   border-radius: 6px; padding: 0.25rem 0.6rem; font-size: 0.78rem;
                   cursor: pointer; white-space: nowrap; }
    .toast .undo:hover { background: #333; color: #fff; }

    #composer { padding: 1rem 1.5rem 1.5rem; flex-shrink: 0; }
    form { max-width: 760px; margin: 0 auto; display: flex; align-items: center;
           gap: 0.4rem; background: #212121; border: 1px solid #333; border-radius: 26px;
           padding: 0.35rem 0.4rem 0.35rem 0.9rem; }
    #input { flex: 1; background: transparent; border: none; outline: none;
             color: #ececec; font-size: 0.95rem; padding: 0.5rem 0; }
    #input::placeholder { color: #868686; }
    .icon-btn { background: transparent; border: none; color: #aaa; cursor: pointer;
                font-size: 1.05rem; padding: 0.35rem 0.5rem; border-radius: 50%; }
    .icon-btn:hover { background: #2e2e2e; color: #fff; }
    .icon-btn.recording { color: #f87171; background: #3a2020; }
    button.send { padding: 0.55rem 1.1rem; border-radius: 20px; border: none;
                  background: #4f46e5; color: white; font-size: 0.88rem; cursor: pointer; }
    button.send:disabled { opacity: 0.4; cursor: default; }
    #status { max-width: 760px; margin: 0.4rem auto 0; font-size: 0.76rem; color: #888;
              min-height: 1rem; }
  </style>
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

  <script>
  const $ = id => document.getElementById(id);
  const log = $('log'), input = $('input'), send = $('send'), status = $('status');
  const menu = $('menu'), overlay = $('overlay');
  let current = null;
  let currentProject = null;
  let pendingProject = null;   // project a not-yet-created chat belongs to
  let sidebar = {projects: [], unfiled: []};
  let projectsOpen = false;
  let chatsOpen = true;
  // {role: 'user'|'assistant', content, actions?}[] for the roadmap,
  // project, and profile chat panels - reset when their screen is
  // freshly opened (not on a background refresh), never persisted.
  let roadmapChatLog = [];
  let projectChatLog = [];
  let profileChatLog = [];
  // Roadmap canvas viewport. Module-scope because every node edit
  // re-renders the whole canvas, and losing the user's zoom/pan on each
  // accept or note would be maddening.
  let roadmapView = {zoom: 1, panX: 0, panY: 0};
  const MIN_ZOOM = 0.2, MAX_ZOOM = 2;
  const openProjects = new Set();

  const api = async (path, opts) => (await fetch(path, opts)).json();
  const jsonSend = (path, body, method) => api(path, {
    method: method || 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const setStatus = m => { status.textContent = m || ''; };

  // ---------- modal ----------

  function modal(opts) {
    return new Promise(resolve => {
      overlay.innerHTML = '';
      const box = document.createElement('div');
      box.className = 'modal';

      const h = document.createElement('h3');
      h.textContent = opts.title;
      box.appendChild(h);

      if (opts.message) {
        const p = document.createElement('p');
        p.textContent = opts.message;
        box.appendChild(p);
      }

      let field = null;
      if (opts.input) {
        field = document.createElement(opts.multiline ? 'textarea' : 'input');
        if (opts.multiline) field.className = 'modal-textarea';
        field.value = opts.value || '';
        field.placeholder = opts.placeholder || '';
        box.appendChild(field);
      }

      const actions = document.createElement('div');
      actions.className = 'modal-actions';
      const cancel = document.createElement('button');
      cancel.className = 'btn-ghost';
      cancel.textContent = 'Cancel';
      const ok = document.createElement('button');
      ok.className = opts.danger ? 'btn-danger' : 'btn-primary';
      ok.textContent = opts.confirmLabel || 'OK';
      actions.appendChild(cancel);
      actions.appendChild(ok);
      box.appendChild(actions);

      overlay.appendChild(box);
      overlay.classList.add('open');

      const close = result => {
        overlay.classList.remove('open');
        overlay.innerHTML = '';
        document.removeEventListener('keydown', onKey);
        resolve(result);
      };
      const submit = () => close(opts.input ? (field.value.trim() || null) : true);
      const onKey = e => {
        if (e.key === 'Escape') { e.preventDefault(); close(null); }
        // Enter submits a single-line field; a textarea needs it to
        // insert a newline instead, so only Cmd/Ctrl+Enter submits.
        else if (e.key === 'Enter' && (!opts.multiline || e.metaKey || e.ctrlKey)) {
          e.preventDefault(); submit();
        }
      };

      cancel.onclick = () => close(null);
      ok.onclick = submit;
      overlay.onclick = e => { if (e.target === overlay) close(null); };
      document.addEventListener('keydown', onKey);
      if (field) { field.focus(); field.select(); }
      else ok.focus();
    });
  }

  // ---------- markdown ----------
  // Answers come back as markdown. Escaping happens first and the
  // converter only ever emits a fixed set of tags, so model output (which
  // includes text fetched from arbitrary web pages) cannot inject markup.

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
  }

  function inlineMarkdown(t) {
    return t
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
      .replace(/__([^_]+)__/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\\*([^*\\n]+)\\*/g, '$1<em>$2</em>')
      .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }

  const TABLE_ROW = /^\\s*\\|(.+)\\|\\s*$/;
  const TABLE_RULE = /^\\s*\\|?[\\s:-]*-[\\s:|-]*$/;

  function tableCells(line) {
    return line.replace(/^\\s*\\|/, '').replace(/\\|\\s*$/, '')
               .split('|').map(c => c.trim());
  }

  function renderMarkdown(src) {
    const lines = escapeHtml(src || '').split('\\n');
    let html = '', list = null;
    const closeList = () => { if (list) { html += '</' + list + '>'; list = null; } };

    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i];
      const line = raw.replace(/\\s+$/, '');
      if (!line.trim()) { closeList(); continue; }

      // Comparison answers come back as pipe tables; without this they
      // render as a wall of literal pipes.
      if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
        closeList();
        const head = tableCells(line);
        html += '<table><thead><tr>' +
                head.map(c => '<th>' + inlineMarkdown(c) + '</th>').join('') +
                '</tr></thead><tbody>';
        i += 2;
        while (i < lines.length && TABLE_ROW.test(lines[i])) {
          html += '<tr>' +
                  tableCells(lines[i]).map(c => '<td>' + inlineMarkdown(c) + '</td>').join('') +
                  '</tr>';
          i++;
        }
        i--;
        html += '</tbody></table>';
        continue;
      }

      let m;
      if ((m = line.match(/^(#{1,5})\\s+(.*)$/))) {
        closeList();
        const level = Math.min(m[1].length + 2, 6);
        html += '<h' + level + '>' + inlineMarkdown(m[2]) + '</h' + level + '>';
      } else if ((m = line.match(/^\\s*&gt;\\s?(.*)$/))) {
        closeList();
        html += '<blockquote>' + inlineMarkdown(m[1]) + '</blockquote>';
      } else if ((m = line.match(/^\\s*[-*+]\\s+(.*)$/))) {
        if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
        html += '<li>' + inlineMarkdown(m[1]) + '</li>';
      } else if ((m = line.match(/^\\s*\\d+[.)]\\s+(.*)$/))) {
        if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
        html += '<li>' + inlineMarkdown(m[1]) + '</li>';
      } else {
        closeList();
        html += '<p>' + inlineMarkdown(line) + '</p>';
      }
    }
    closeList();
    return html;
  }

  function setMarkdown(el, text) {
    el.classList.remove('pending');
    el.innerHTML = renderMarkdown(text);
  }

  // ---------- toasts ----------

  const TOAST_SECONDS = 8;

  function toast(message, opts) {
    opts = opts || {};
    const el = document.createElement('div');
    el.className = 'toast' + (opts.error ? ' err' : '');
    const msg = document.createElement('span');
    msg.className = 'msg';
    msg.textContent = message;
    el.appendChild(msg);

    let timer = null;
    const dismiss = () => {
      if (timer) clearInterval(timer);
      el.remove();
    };

    if (opts.undo) {
      // The countdown is shown rather than implied, so it is obvious how
      // long the undo actually lasts.
      let left = opts.seconds || TOAST_SECONDS;
      const btn = document.createElement('button');
      btn.className = 'undo';
      const label = () => { btn.textContent = 'Undo (' + left + ')'; };
      label();
      btn.onclick = async () => { dismiss(); await opts.undo(); };
      el.appendChild(btn);
      timer = setInterval(() => {
        left -= 1;
        if (left <= 0) dismiss(); else label();
      }, 1000);
    } else {
      timer = setTimeout(dismiss, (opts.seconds || 3) * 1000);
    }

    $('toasts').appendChild(el);
    return dismiss;
  }

  const askText = (title, value, placeholder) =>
    modal({title, value, placeholder, input: true});
  const askConfirm = (title, message, confirmLabel) =>
    modal({title, message, confirmLabel, danger: true});

  // ---------- sidebar ----------

  async function loadSidebar() {
    sidebar = await api('/api/sidebar');
    renderTree();
  }

  // Reload the sidebar, and the project screen too when one is open -
  // it renders its own copy of names and chat rows, so it goes stale
  // otherwise.
  async function refreshViews() {
    // Independent of each other, so they run together rather than one
    // after the other — this runs after most sidebar-menu actions
    // (rename, pin, move, delete), so halving its wait speeds up all of
    // them. background: true means "do not spend an API call
    // regenerating highlights" - this refresh is a side effect of a
    // move or rename, not the user asking to see the project.
    await Promise.all([
      loadSidebar(),
      currentProject ? openProject(currentProject, {background: true}) : null
    ]);
  }

  function sectionRow(label, opts) {
    const row = document.createElement('div');
    row.className = 'section' + (opts.onClick ? ' clickable' : '');
    if (opts.caret) {
      const c = document.createElement('span');
      c.className = 'sec-caret';
      c.textContent = opts.open ? '\\u25be' : '\\u25b8';
      row.appendChild(c);
    }
    const l = document.createElement('span');
    l.className = 'label';
    l.textContent = label;
    row.appendChild(l);
    if (opts.onAdd) {
      const b = document.createElement('button');
      b.className = 'add';
      b.textContent = '+';
      b.title = opts.addTitle || 'Add';
      b.onclick = e => { e.stopPropagation(); opts.onAdd(); };
      row.appendChild(b);
    }
    if (opts.onClick) makeClickable(row, opts.onClick);
    return row;
  }

  // Every clickable row in the app is a plain div with an onclick and no
  // other affordance for reaching it - Tab skips over all of them, and
  // there was no keyboard equivalent for the click at all. This makes a
  // div behave like a real button: reachable by Tab, activated by
  // Enter or Space, exposed to a screen reader as a button.
  function makeClickable(el, onClick) {
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    el.onclick = onClick;
    el.addEventListener('keydown', e => {
      if (e.target !== el) return; // let a real button/input inside handle its own key
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e); }
    });
  }

  function chatRow(c) {
    const row = document.createElement('div');
    row.className = 'chat' + (c.unread ? ' unread' : '') +
                    (current && current.id === c.id ? ' active' : '');
    if (c.unread) {
      const d = document.createElement('div'); d.className = 'dot';
      row.appendChild(d);
    }
    if (c.pinned) {
      const p = document.createElement('span');
      p.className = 'pin';
      p.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M12 17v5"/>' +
        '<path d="M9 3h6l1 5 3 2-1 3H6l-1-3 3-2 1-5Z"/></svg>';
      row.appendChild(p);
    }
    const title = document.createElement('span');
    title.className = 'chat-title';
    title.textContent = c.title;
    row.appendChild(title);
    const btn = document.createElement('button');
    btn.className = 'menu-btn';
    btn.textContent = '\\u22ef';
    btn.title = 'Chat options';
    btn.setAttribute('aria-label', 'Chat options');
    btn.onclick = e => { e.stopPropagation(); openChatMenu(e, c); };
    row.appendChild(btn);
    makeClickable(row, () => openConversation(c.id));
    return row;
  }

  function renderTree() {
    const tree = $('tree');
    tree.innerHTML = '';

    // Projects: click the header to open the section, then + to add one.
    tree.appendChild(sectionRow('Projects', {
      caret: true,
      open: projectsOpen,
      onAdd: projectsOpen ? createProject : null,
      addTitle: 'New project',
      onClick: () => { projectsOpen = !projectsOpen; renderTree(); }
    }));

    if (projectsOpen) {
      if (!sidebar.projects.length) {
        const hint = document.createElement('div');
        hint.className = 'empty-hint';
        hint.textContent = 'No projects yet \\u2014 use + to add one.';
        tree.appendChild(hint);
      }
      sidebar.projects.forEach(p => {
        const wrap = document.createElement('div');
        wrap.className = 'project';
        const expanded = openProjects.has(p.id);

        const head = document.createElement('div');
        head.className = 'project-head';
        const caret = document.createElement('span');
        caret.className = 'caret';
        caret.textContent = expanded ? '\\u25be' : '\\u25b8';
        head.appendChild(caret);
        const name = document.createElement('span');
        name.style.flex = '1';
        name.textContent = p.name;
        // Clicking the name opens the project screen; the caret to its
        // left is what expands the chat list inline.
        makeClickable(name, e => { e.stopPropagation(); openProject(p.id); });
        head.appendChild(name);
        const btn = document.createElement('button');
        btn.className = 'menu-btn';
        btn.textContent = '\\u22ef';
        btn.title = 'Project options';
        btn.setAttribute('aria-label', 'Project options');
        btn.onclick = e => { e.stopPropagation(); openProjectMenu(e, p); };
        head.appendChild(btn);
        makeClickable(head, () => {
          expanded ? openProjects.delete(p.id) : openProjects.add(p.id);
          renderTree();
        });
        wrap.appendChild(head);

        if (expanded) {
          const kids = document.createElement('div');
          kids.className = 'nested';
          if (!p.conversations.length) {
            const empty = document.createElement('div');
            empty.className = 'empty-hint';
            empty.textContent = 'Empty \\u2014 move a chat here.';
            kids.appendChild(empty);
          }
          p.conversations.forEach(c => kids.appendChild(chatRow(c)));
          wrap.appendChild(kids);
        }
        tree.appendChild(wrap);
      });
    }

    // Chats: click the header to minimize the list, + starts a new one.
    tree.appendChild(sectionRow('Chats', {
      caret: true,
      open: chatsOpen,
      onAdd: newChat,
      addTitle: 'New chat',
      onClick: () => { chatsOpen = !chatsOpen; renderTree(); }
    }));
    if (chatsOpen) {
      sidebar.unfiled.forEach(c => tree.appendChild(chatRow(c)));
    }
  }

  async function createProject() {
    const name = await askText('New project', '', 'e.g. Career');
    if (!name) return;
    const res = await jsonSend('/api/projects', {name});
    if (res.error) { toast(res.error, {error: true}); return; }
    projectsOpen = true;
    openProjects.add(res.id);
    await loadSidebar();
    toast('Created project "' + res.name + '"');
  }

  // ---------- context menus ----------

  function showMenu(e, items) {
    menu.innerHTML = '';
    items.forEach(it => {
      if (it.divider) { menu.appendChild(document.createElement('hr')); return; }
      const d = document.createElement('div');
      d.textContent = it.label;
      if (it.danger) d.className = 'danger';
      d.onclick = async () => { menu.style.display = 'none'; await it.run(); };
      menu.appendChild(d);
    });
    menu.style.display = 'block';
    menu.style.left = Math.min(e.clientX, window.innerWidth - 190) + 'px';
    menu.style.top = Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 10) + 'px';
  }

  document.addEventListener('click', e => {
    if (!menu.contains(e.target)) menu.style.display = 'none';
  });

  function openChatMenu(e, c) {
    const items = [
      {label: 'Rename', run: async () => {
        const t = await askText('Rename chat', c.title);
        if (!t) return;
        await jsonSend('/api/conversations/' + c.id, {title: t}, 'PATCH');
        if (current && current.id === c.id) { current.title = t; setBreadcrumb(); }
        await refreshViews();
        toast('Renamed to "' + t + '"', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {title: c.title}, 'PATCH');
          if (current && current.id === c.id) { current.title = c.title; setBreadcrumb(); }
          await refreshViews();
          toast('Rename undone');
        }});
      }},
      {label: c.pinned ? 'Unpin' : 'Pin', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {pinned: !c.pinned}, 'PATCH');
        await refreshViews();
        toast(c.pinned ? 'Unpinned' : 'Pinned', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {pinned: c.pinned}, 'PATCH');
          await refreshViews();
          toast('Reverted');
        }});
      }},
      {label: c.unread ? 'Mark as read' : 'Mark as unread', run: async () => {
        await jsonSend('/api/conversations/' + c.id, {unread: !c.unread}, 'PATCH');
        await refreshViews();
        toast(c.unread ? 'Marked as read' : 'Marked as unread', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {unread: c.unread}, 'PATCH');
          await refreshViews();
          toast('Reverted');
        }});
      }},
      {divider: true}
    ];

    sidebar.projects.filter(p => p.id !== c.project_id).forEach(p => {
      items.push({label: 'Move to ' + p.name, run: async () => {
        const previous = c.project_id;
        await jsonSend('/api/conversations/' + c.id, {project_id: p.id}, 'PATCH');
        projectsOpen = true; openProjects.add(p.id);
        if (current && current.id === c.id) { current.project_id = p.id; }
        await refreshViews();
        setBreadcrumb();
        toast('Moved to ' + p.name, {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {project_id: previous}, 'PATCH');
          if (current && current.id === c.id) { current.project_id = previous; }
          await refreshViews();
          setBreadcrumb();
          toast('Move undone');
        }});
      }});
    });
    if (c.project_id) {
      items.push({label: 'Remove from project', run: async () => {
        const previous = c.project_id;
        await jsonSend('/api/conversations/' + c.id, {project_id: null}, 'PATCH');
        if (current && current.id === c.id) { current.project_id = null; }
        await refreshViews();
        setBreadcrumb();
        toast('Removed from project', {undo: async () => {
          await jsonSend('/api/conversations/' + c.id, {project_id: previous}, 'PATCH');
          if (current && current.id === c.id) { current.project_id = previous; }
          await refreshViews();
          setBreadcrumb();
          toast('Move undone');
        }});
      }});
    }

    items.push({divider: true});
    items.push({label: 'Delete', danger: true, run: async () => {
      const ok = await askConfirm('Delete chat',
        '"' + c.title + '" and everything in it will be removed. This cannot be undone.',
        'Delete');
      if (!ok) return;
      const res = await api('/api/conversations/' + c.id, {method: 'DELETE'});
      if (current && current.id === c.id) newChat();
      await refreshViews();
      if (res.error) { toast(res.error, {error: true}); return; }
      toast('Deleted "' + c.title + '"', {undo: async () => {
        const back = await api('/api/undo-delete/' + c.id, {method: 'POST'});
        if (back.error) { toast(back.error, {error: true}); return; }
        await refreshViews();
        toast('Restored with ' + back.entries + ' message(s)');
      }});
    }});
    showMenu(e, items);
  }

  function openProjectMenu(e, p) {
    showMenu(e, [
      {label: 'Rename', run: async () => {
        const n = await askText('Rename project', p.name);
        if (!n) return;
        await jsonSend('/api/projects/' + p.id, {name: n}, 'PATCH');
        await loadSidebar();
        // The project screen renders its own copy of the name, so it has
        // to be re-read or it keeps showing the old one.
        if (currentProject === p.id) await openProject(p.id, {background: true});
        else setBreadcrumb();
        toast('Project renamed to "' + n + '"', {undo: async () => {
          await jsonSend('/api/projects/' + p.id, {name: p.name}, 'PATCH');
          await loadSidebar();
          if (currentProject === p.id) await openProject(p.id, {background: true});
          toast('Rename undone');
        }});
      }},
      {divider: true},
      {label: 'Delete project', danger: true, run: async () => {
        const ok = await askConfirm('Delete project',
          'Chats inside "' + p.name + '" are kept and moved out of the project.',
          'Delete project');
        if (!ok) return;
        await api('/api/projects/' + p.id, {method: 'DELETE'});
        openProjects.delete(p.id);
        if (currentProject === p.id) newChat();
        await loadSidebar();
        setBreadcrumb();
        toast('Deleted project "' + p.name + '" \\u2014 its chats were kept');
      }}
    ]);
  }

  // ---------- conversation view ----------

  function turn() {
    const d = document.createElement('div'); d.className = 'turn';
    log.appendChild(d); return d;
  }
  function userLine(c, text) {
    const row = document.createElement('div'); row.className = 'user-line';
    const s = document.createElement('span'); s.textContent = text;
    row.appendChild(s); c.appendChild(row);
  }
  function assistantText(c, text, kind, opts) {
    if (kind && kind !== 'research') {
      const t = document.createElement('div'); t.className = 'kind-tag';
      t.textContent = kind; c.appendChild(t);
    }
    const d = document.createElement('div'); d.className = 'assistant-text';
    // Uploaded documents are raw extracted text, not markdown, so they
    // are shown verbatim rather than run through the converter.
    if (opts && opts.plain) {
      d.style.whiteSpace = 'pre-wrap';
      d.textContent = text;
    } else {
      setMarkdown(d, text);
    }
    c.appendChild(d);
    return d;
  }
  function metaBlock(c, recalled, sources) {
    if (!(recalled || []).length && !(sources || []).length) return;
    const m = document.createElement('div'); m.className = 'meta';
    if ((recalled || []).length) {
      const r = document.createElement('div');
      r.textContent = 'Built on: ' + recalled.join(', ');
      m.appendChild(r);
    }
    (sources || []).forEach(u => {
      const a = document.createElement('a');
      a.href = u; a.target = '_blank'; a.rel = 'noopener'; a.textContent = u;
      m.appendChild(a);
    });
    c.appendChild(m);
  }

  function setBreadcrumb() {
    if (!current) { $('breadcrumb').textContent = 'New chat'; return; }
    const proj = sidebar.projects.find(p => p.id === current.project_id);
    $('breadcrumb').innerHTML = '';
    if (proj) {
      $('breadcrumb').appendChild(document.createTextNode(proj.name + ' / '));
    }
    const b = document.createElement('b');
    b.textContent = current.title;
    $('breadcrumb').appendChild(b);
  }

  function showEmptyState() {
    log.innerHTML = '';
    const d = document.createElement('div');
    d.className = 'empty-state';
    d.textContent = 'Ask anything. Answers are researched, sourced, and remembered.';
    log.appendChild(d);
  }

  // ---------- navigation history ----------
  // Tracks which conversations have been viewed, so back/forward move
  // through them the way browser history would. `replaying` suppresses
  // recording while moving through the stack, which would otherwise
  // append every step back onto the end.

  let navStack = [null];
  let navPos = 0;
  let replaying = false;

  function recordVisit(id) {
    if (replaying) return;
    if (navStack[navPos] === id) return;
    navStack = navStack.slice(0, navPos + 1);
    navStack.push(id);
    navPos = navStack.length - 1;
    updateNav();
  }

  function updateNav() {
    $('nav-back').disabled = navPos <= 0;
    $('nav-fwd').disabled = navPos >= navStack.length - 1;
  }

  async function goTo(pos) {
    if (pos < 0 || pos >= navStack.length) return;
    navPos = pos;
    replaying = true;
    const id = navStack[navPos];
    if (id) await openConversation(id);
    else newChat();
    replaying = false;
    updateNav();
  }

  $('nav-back').onclick = () => goTo(navPos - 1);
  $('nav-fwd').onclick = () => goTo(navPos + 1);

  $('toggle-sidebar').onclick = () => {
    $('sidebar').classList.toggle('collapsed');
  };

  // ---------- opening ----------

  async function openConversation(id) {
    const data = await api('/api/conversations/' + id);
    if (data.error) { setStatus(data.error); return; }
    showChatView();
    currentProject = null;
    pendingProject = null;
    current = data.conversation;
    log.innerHTML = '';
    data.entries.forEach(e => {
      const t = turn();
      userLine(t, e.query);
      assistantText(t, e.summary, e.kind, {plain: e.kind === 'document' || e.kind === 'note'});
      metaBlock(t, [], e.sources);
    });
    setBreadcrumb();
    recordVisit(id);
    await loadSidebar();
    log.scrollTop = log.scrollHeight;
  }

  function newChat() {
    current = null;
    currentProject = null;
    pendingProject = null;
    showChatView();
    showEmptyState();
    setBreadcrumb();
    recordVisit(null);
    renderTree();
    input.focus();
  }

  // ---------- project detail ----------

  function relTime(iso) {
    if (!iso) return '';
    const secs = (Date.now() - new Date(iso).getTime()) / 1000;
    if (secs < 90) return 'just now';
    if (secs < 3600) return Math.round(secs / 60) + ' min ago';
    if (secs < 86400) return Math.round(secs / 3600) + ' hours ago';
    return Math.round(secs / 86400) + ' days ago';
  }

  function card(title, buttonLabel, onClick) {
    const c = document.createElement('div');
    c.className = 'card';
    const h = document.createElement('h4');
    h.appendChild(document.createTextNode(title));
    const sp = document.createElement('span'); sp.className = 'spacer';
    h.appendChild(sp);
    if (buttonLabel) {
      const b = document.createElement('button');
      b.className = 'card-btn';
      b.textContent = buttonLabel;
      b.onclick = onClick;
      h.appendChild(b);
    }
    c.appendChild(h);
    return c;
  }

  // A compact propose/accept chat card - same safety property as the
  // roadmap's larger canvas-side panel (the model only ever proposes;
  // nothing changes until Accept is clicked), packaged for the project
  // and profile screens where a full side panel doesn't fit. `chatLog`
  // is the caller's persistent array (survives a parent re-render since
  // it lives outside this card); `applyAction` performs one accepted
  // action's real mutation and returns whether it succeeded;
  // `afterApply` runs after a successful accept to refresh whatever the
  // action changed.
  function buildAssistantCard(title, hint, chatLog, sendMessage, applyAction, afterApply) {
    const c = card(title, null, null);
    const log = document.createElement('div');
    log.className = 'rc-log';
    c.appendChild(log);

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
        note.textContent = action.resolved === 'accepted' ? '\\u2713 Applied' : '\\u2717 Dismissed';
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
        const ok = await applyAction(action);
        if (!ok) { accept.disabled = false; return; }
        action.resolved = 'accepted';
        await afterApply();
      };
      buttons.appendChild(accept);
      const reject = document.createElement('button');
      reject.className = 'rc-reject';
      reject.textContent = 'Dismiss';
      reject.onclick = () => { action.resolved = 'rejected'; renderLog(); };
      buttons.appendChild(reject);
      box.appendChild(buttons);
      return box;
    }

    function renderLog() {
      log.innerHTML = '';
      if (!chatLog.length) {
        const hintEl = document.createElement('div');
        hintEl.className = 'muted';
        hintEl.textContent = hint;
        log.appendChild(hintEl);
      }
      chatLog.forEach(entry => {
        const msg = document.createElement('div');
        msg.className = 'rc-msg ' + entry.role;
        msg.textContent = entry.content;
        log.appendChild(msg);
        (entry.actions || []).forEach(a => log.appendChild(renderActionCard(a)));
      });
      log.scrollTop = log.scrollHeight;
    }
    renderLog();

    const form = document.createElement('form');
    form.className = 'rc-form';
    const input = document.createElement('input');
    input.className = 'rc-input';
    input.placeholder = 'Ask\\u2026';
    form.appendChild(input);
    const sendBtn = document.createElement('button');
    sendBtn.className = 'send';
    sendBtn.type = 'submit';
    sendBtn.textContent = 'Send';
    form.appendChild(sendBtn);
    form.onsubmit = async e => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      sendBtn.disabled = input.disabled = true;

      const historyForRequest = chatLog.map(m => ({role: m.role, content: m.content}));
      chatLog.push({role: 'user', content: message});
      renderLog();

      const res = await sendMessage(message, historyForRequest);
      sendBtn.disabled = input.disabled = false;
      input.focus();
      if (res.error) {
        chatLog.push({role: 'assistant', content: 'Error: ' + res.error, actions: []});
      } else {
        chatLog.push({role: 'assistant', content: res.reply, actions: res.actions || []});
      }
      renderLog();
    };
    c.appendChild(form);
    return c;
  }

  function setActiveView(name) {
    $('project-view').classList.toggle('open', name === 'project');
    $('roadmap-view').classList.toggle('open', name === 'roadmap');
    $('profile-view').classList.toggle('open', name === 'profile');
    $('dashboard-view').classList.toggle('open', name === 'dashboard');
    log.style.display = name === 'chat' ? '' : 'none';
    $('composer').style.display = name === 'chat' ? '' : 'none';
  }

  function showChatView() { setActiveView('chat'); }
  function showProjectView() { setActiveView('project'); }
  function showRoadmapView() { setActiveView('roadmap'); }
  function showProfileView() { setActiveView('profile'); }
  function showDashboardView() { setActiveView('dashboard'); }

  async function openProject(id, opts) {
    opts = opts || {};
    currentProject = id;
    current = null;
    showProjectView();

    const view = $('project-view');
    if (!opts.background) {
      view.innerHTML = '<div class="muted">Loading project\\u2026</div>';
      $('breadcrumb').textContent = 'Projects';
      // A background refresh (e.g. after the chat assistant renames the
      // project) must not wipe the chat history it's about to redraw.
      projectChatLog = [];
    }

    // Opening a project must never block on a model call - background=1
    // always skips highlight generation here, regardless of opts.background
    // (which only controls the loading placeholder below). Stale or
    // missing highlights show as-is with a note; the Refresh button, not
    // navigation, is what pays the LLM round trip.
    const params = ['background=1'];
    if (opts.refresh) params.push('refresh=1');
    // Both requests are independent, so they're fired together instead of
    // one after the other — the roadmap fetch below just reads a promise
    // that has usually already resolved by the time it's needed.
    const dataPromise = api('/api/projects/' + id +
                            (params.length ? '?' + params.join('&') : ''));
    const rmDataPromise = api('/api/roadmap/' + id);
    const data = await dataPromise;
    if (data.error) { view.innerHTML = ''; setStatus(data.error); return; }

    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode('Projects / '));
    const b = document.createElement('b');
    b.textContent = data.name;
    $('breadcrumb').appendChild(b);

    view.innerHTML = '';
    const layout = document.createElement('div');
    layout.className = 'proj-layout';

    // --- left: title, new chat, conversations ---
    const main = document.createElement('div');
    main.className = 'proj-main';
    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = data.name;
    main.appendChild(title);

    const startCard = card('Start a chat in this project', null, null);
    const startBtn = document.createElement('button');
    startBtn.className = 'send';
    startBtn.textContent = '+ New chat here';
    startBtn.onclick = () => newChatInProject(id, data.name);
    startCard.appendChild(startBtn);
    main.appendChild(startCard);

    const chatsCard = card('Chats', null, null);
    if (!data.conversations.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No chats yet. Start one above, or move an existing chat here.';
      chatsCard.appendChild(p);
    }
    data.conversations.forEach(c => {
      const row = document.createElement('div');
      row.className = 'proj-chat';
      const t = document.createElement('span');
      t.style.flex = '1';
      if (c.pinned) {
        const pin = document.createElement('span');
        pin.className = 'pin';
        pin.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
          'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
          'stroke-linejoin="round"><path d="M12 17v5"/>' +
          '<path d="M9 3h6l1 5 3 2-1 3H6l-1-3 3-2 1-5Z"/></svg>';
        t.appendChild(pin);
      }
      t.appendChild(document.createTextNode(c.title));
      row.appendChild(t);
      const w = document.createElement('span');
      w.className = 'when';
      w.textContent = relTime(c.updated_at);
      row.appendChild(w);
      makeClickable(row, () => { showChatView(); openConversation(c.id); });
      chatsCard.appendChild(row);
    });
    main.appendChild(chatsCard);
    layout.appendChild(main);

    // --- right rail: highlights, instructions, files ---
    const rail = document.createElement('div');
    rail.className = 'proj-rail';

    // Refresh replaces only this panel's contents, so the rest of the
    // project screen does not flash while one card reloads.
    const hlCard = card('What\\u2019s next', '\\u21bb Refresh', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = '\\u21bb Refreshing\\u2026';
      const fresh = await api('/api/projects/' + id + '?refresh=1');
      btn.disabled = false;
      btn.textContent = '\\u21bb Refresh';
      if (fresh.error) { toast(fresh.error, {error: true}); return; }
      fillHighlights(hlCard, fresh, id);
      toast(fresh.highlights_error
        ? 'Could not refresh: ' + fresh.highlights_error
        : 'Suggestions updated', {error: !!fresh.highlights_error});
    });
    fillHighlights(hlCard, data, id);
    rail.appendChild(hlCard);

    const roadmapCard = card('Roadmap', null, null);
    const rmData = await rmDataPromise;
    if (!rmData.roadmap) {
      const goalInput = document.createElement('input');
      goalInput.placeholder = 'What are you working toward?';
      goalInput.style.cssText = 'width:100%;padding:0.5rem 0.65rem;border-radius:8px;' +
        'border:1px solid #333;background:#191919;color:#ececec;font-size:0.85rem;' +
        'margin:0.5rem 0;';
      roadmapCard.appendChild(goalInput);
      const genBtn = document.createElement('button');
      genBtn.className = 'send';
      genBtn.textContent = 'Generate roadmap';
      genBtn.onclick = async () => {
        const goal = goalInput.value.trim();
        if (!goal) { toast('Enter a goal first', {error: true}); return; }
        genBtn.disabled = true;
        genBtn.textContent = 'Generating\\u2026';
        const res = await jsonSend('/api/roadmap/' + id + '/generate', {goal});
        genBtn.disabled = false;
        genBtn.textContent = 'Generate roadmap';
        if (res.error) { toast(res.error, {error: true}); return; }
        openRoadmapView(id, data.name);
      };
      roadmapCard.appendChild(genBtn);
    } else {
      const summary = document.createElement('div');
      summary.className = 'muted';
      summary.textContent = rmData.roadmap.goal;
      roadmapCard.appendChild(summary);
      const openBtn = document.createElement('button');
      openBtn.className = 'send';
      openBtn.style.marginTop = '0.5rem';
      openBtn.textContent = 'Open roadmap';
      openBtn.onclick = () => openRoadmapView(id, data.name);
      roadmapCard.appendChild(openBtn);
    }
    rail.appendChild(roadmapCard);

    const instrCard = card('Instructions', null, null);
    const box = document.createElement('textarea');
    box.className = 'instructions-box';
    box.value = data.instructions || '';
    box.placeholder = 'Guidance applied to every answer in this project.';
    instrCard.appendChild(box);

    const saveRow = document.createElement('div');
    saveRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;margin-top:0.6rem;';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'send';
    saveBtn.textContent = 'Save instructions';
    saveBtn.disabled = true;
    const dirtyNote = document.createElement('span');
    dirtyNote.className = 'muted';
    saveRow.appendChild(saveBtn);
    saveRow.appendChild(dirtyNote);
    instrCard.appendChild(saveRow);

    // The button only lights up when there is something to save, so it
    // is obvious whether the current text is applied or not.
    const original = box.value;
    box.oninput = () => {
      const changed = box.value !== original;
      saveBtn.disabled = !changed;
      dirtyNote.textContent = changed ? 'Unsaved changes' : '';
    };
    saveBtn.onclick = async () => {
      const res = await jsonSend('/api/projects/' + id, {instructions: box.value}, 'PATCH');
      if (res.error) { toast(res.error, {error: true}); return; }
      saveBtn.disabled = true;
      dirtyNote.textContent = '';
      toast('Instructions saved', {undo: async () => {
        await jsonSend('/api/projects/' + id, {instructions: original}, 'PATCH');
        box.value = original;
        toast('Instructions reverted');
      }});
    };
    rail.appendChild(instrCard);

    const filesCard = card('Files', '+ Upload', () => uploadInto(id));
    if (!data.files.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No documents yet.';
      filesCard.appendChild(p);
    }
    data.files.forEach(f => {
      const chip = document.createElement('span');
      chip.className = 'file-chip';
      chip.textContent = f.name;
      makeClickable(chip, () => { showChatView(); openConversation(f.conversation_id); });
      filesCard.appendChild(chip);
    });
    rail.appendChild(filesCard);

    const assistantCard = buildAssistantCard(
      'Project Assistant',
      'Ask about this project, or tell it what to change \\u2014 it can ' +
      'propose renaming it or updating its instructions.',
      projectChatLog,
      (message, history) => jsonSend('/api/projects/' + id + '/chat', {message, history}),
      async action => {
        const patch = {};
        if (action.name !== null) patch.name = action.name;
        if (action.instructions !== null) patch.instructions = action.instructions;
        const res = await jsonSend('/api/projects/' + id, patch, 'PATCH');
        if (res.error) { toast(res.error, {error: true}); return false; }
        return true;
      },
      () => refreshViews()
    );
    rail.appendChild(assistantCard);

    layout.appendChild(rail);
    view.appendChild(layout);
  }

  // Rebuilds only the body of the What's next card, leaving its header
  // (and the Refresh button being clicked) in place.
  function fillHighlights(cardEl, data, projectId) {
    cardEl.querySelectorAll(':scope > *:not(h4)').forEach(n => n.remove());

    if (data.highlights_error) {
      const e = document.createElement('div');
      e.className = 'muted';
      e.textContent = 'Could not refresh \\u2014 ' + data.highlights_error +
                      '. Showing the previous suggestions.';
      cardEl.appendChild(e);
    }
    // Loading a project never generates automatically now, so an
    // entry_count > 0 project with zero highlights just hasn't had
    // Refresh clicked yet - distinct from one with nothing to work from.
    if (!data.highlights.length && !data.highlights_error) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = data.entry_count
        ? 'Not generated yet \\u2014 hit Refresh to see suggestions.'
        : 'Add chats or a document, and suggestions appear here.';
      cardEl.appendChild(p);
    }
    if (data.highlights_stale && data.highlights.length && !data.highlights_error) {
      const note = document.createElement('div');
      note.className = 'stale-note';
      note.textContent = 'New activity since these \\u2014 hit Refresh to update.';
      cardEl.appendChild(note);
    }

    data.highlights.forEach(h => {
      const tier = h.priority || 'next';
      const item = document.createElement('div');
      item.className = 'hl ' + tier;
      item.title = 'Click to expand';

      const head = document.createElement('div');
      head.className = 'hl-head';
      const badge = document.createElement('span');
      badge.className = 'tier ' + tier;
      badge.textContent = tier === 'now' ? 'Do now' : tier;
      head.appendChild(badge);
      head.appendChild(document.createTextNode(h.headline));
      item.appendChild(head);

      if (h.detail) {
        const d = document.createElement('div');
        d.className = 'hl-detail';
        d.textContent = h.detail;
        item.appendChild(d);
      }
      if (h.source) {
        const s = document.createElement('div');
        s.className = 'hl-source';
        // The prompt labels entries "[RESEARCH] ..." so the model can tell
        // documents from chats; that tag is internal and reads as noise here.
        s.textContent = 'from: ' + h.source.replace(/^\\[[A-Z]+\\]\\s*/, '');
        item.appendChild(s);
      }
      makeClickable(item, () => expandHighlight(h, data.name));
      cardEl.appendChild(item);
    });

    if (data.highlights_generated_at && data.highlights.length) {
      const stamp = document.createElement('div');
      stamp.className = 'stamp';
      stamp.textContent = 'Updated ' + relTime(data.highlights_generated_at) +
                          ' \\u00b7 based on ' + data.entry_count + ' item(s)';
      cardEl.appendChild(stamp);
    }
  }

  function expandHighlight(h, projectName) {
    const tier = h.priority || 'next';
    const parts = [];
    if (h.detail) parts.push(h.detail);
    if (h.source) {
      parts.push('Based on: ' + h.source.replace(/^\\[[A-Z]+\\]\\s*/, ''));
    }
    parts.push('Project: ' + projectName);
    modal({
      title: (tier === 'now' ? '\\u2605  ' : '') + h.headline,
      message: parts.join('\\n\\n'),
      confirmLabel: 'Ask about this'
    }).then(async ok => {
      if (!ok) return;
      // Turning a highlight into a question is the natural next move, so
      // it drops straight into the composer inside this project.
      newChatInProject(currentProject, projectName);
      input.value = h.headline;
      input.focus();
    });
  }

  function newChatInProject(projectId, projectName) {
    showChatView();
    current = null;
    pendingProject = {id: projectId, name: projectName};
    showEmptyState();
    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode(projectName + ' / '));
    const b = document.createElement('b');
    b.textContent = 'New chat';
    $('breadcrumb').appendChild(b);
    input.focus();
  }

  // ---------- roadmap ----------

  async function openRoadmapView(projectId, projectName) {
    currentProject = projectId;
    current = null;
    roadmapChatLog = [];
    roadmapView = {zoom: 1, panX: 0, panY: 0};
    showRoadmapView();
    $('breadcrumb').innerHTML = '';
    $('breadcrumb').appendChild(document.createTextNode(projectName + ' / '));
    const b = document.createElement('b');
    b.textContent = 'Roadmap';
    $('breadcrumb').appendChild(b);

    const view = $('roadmap-view');
    view.innerHTML = '<div class="muted" style="padding:1.5rem;">Loading roadmap\\u2026</div>';

    const data = await api('/api/roadmap/' + projectId);
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
        genBtn.disabled = true;
        genBtn.textContent = 'Generating\\u2026';
        const res = await jsonSend('/api/roadmap/' + projectId + '/generate', {goal});
        genBtn.disabled = false;
        genBtn.textContent = 'Generate roadmap';
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
      return;
    }
    renderRoadmap(projectId, projectName, data.roadmap, data.nodes, {fitView: true});
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

    const addBtn = document.createElement('button');
    addBtn.className = 'card-btn';
    addBtn.textContent = '+ Add step';
    addBtn.onclick = async () => {
      const title = await askText('New step', '', 'Title');
      if (!title) return;
      // Cascades new cards so repeated adds don't stack exactly on top
      // of each other before the user drags them apart.
      const offset = (nodesList.length % 6) * 40;
      const node = await jsonSend('/api/roadmap-node/' + roadmap.id,
                                  {title, x: 40 + offset, y: 40 + offset});
      if (node.error) { toast(node.error, {error: true}); return; }
      // The server hands back the full node, so the new card can be
      // added straight into the canvas instead of re-fetching everything.
      nodesList.push(node);
      renderRoadmap(projectId, projectName, roadmap, nodesList);
    };
    top.appendChild(addBtn);

    const tidyBtn = document.createElement('button');
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
    regenBtn.className = 'card-btn';
    regenBtn.textContent = '\\u21bb Regenerate';
    regenBtn.onclick = async () => {
      regenBtn.disabled = true;
      regenBtn.textContent = '\\u21bb Regenerating\\u2026';
      const res = await jsonSend('/api/roadmap/' + projectId + '/generate', {goal: roadmap.goal});
      regenBtn.disabled = false;
      regenBtn.textContent = '\\u21bb Regenerate';
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

    // Drag anywhere that isn't a card to pan.
    let panning = null;
    scroll.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.node, #zoom-controls')) return;
      panning = {x: ev.clientX, y: ev.clientY,
                 panX: roadmapView.panX, panY: roadmapView.panY};
      scroll.classList.add('panning');
      scroll.setPointerCapture(ev.pointerId);
    });
    scroll.addEventListener('pointermove', ev => {
      if (!panning) return;
      roadmapView.panX = panning.panX + (ev.clientX - panning.x);
      roadmapView.panY = panning.panY + (ev.clientY - panning.y);
      applyViewport();
    });
    const endPan = () => { panning = null; scroll.classList.remove('panning'); };
    scroll.addEventListener('pointerup', endPan);
    scroll.addEventListener('pointercancel', endPan);

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
    zoomBtn('\\u2212', 'Zoom out', () => zoomFromCentre(roadmapView.zoom / 1.2));
    const zoomLabel = document.createElement('span');
    zoomLabel.id = 'zoom-level';
    zoomControls.appendChild(zoomLabel);
    zoomBtn('+', 'Zoom in', () => zoomFromCentre(roadmapView.zoom * 1.2));
    zoomBtn('\\u2922', 'Fit to view', () => fitCanvasToContent());
    scroll.appendChild(zoomControls);

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
          const path = document.createElementNS(svgNS, 'path');
          path.setAttribute('d',
            'M' + from.x + ',' + from.y +
            ' C' + mx + ',' + from.y + ' ' + mx + ',' + to.y + ' ' + to.x + ',' + to.y);
          svg.appendChild(path);
        });
      });
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
        Object.assign(n, res);
      });
    }

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
      more.textContent = '\\u22ef';
      more.title = 'More actions for this step';
      more.setAttribute('aria-label', 'More actions for this step');
      more.onclick = ev => { ev.stopPropagation(); showMenu(ev, nodeMenuItems(n)); };
      el.appendChild(more);

      // Pointer events (not mouse events) so dragging works with touch too.
      let dragging = null;
      el.addEventListener('pointerdown', ev => {
        if (ev.target.closest('button, input, label')) return;
        dragging = {startX: ev.clientX, startY: ev.clientY, origX: n.x, origY: n.y};
        el.setPointerCapture(ev.pointerId);
      });
      el.addEventListener('pointermove', ev => {
        if (!dragging) return;
        // Cursor movement is in screen pixels but the card is positioned
        // in canvas pixels, so the delta has to be divided by the zoom
        // or a zoomed-out card outruns the cursor.
        n.x = dragging.origX + (ev.clientX - dragging.startX) / roadmapView.zoom;
        n.y = dragging.origY + (ev.clientY - dragging.startY) / roadmapView.zoom;
        el.style.left = n.x + 'px';
        el.style.top = n.y + 'px';
        drawEdges();
      });
      const endDrag = () => {
        if (!dragging) return;
        dragging = null;
        // The dragged position is already on screen, so this persists in
        // the background without the full-canvas re-render updateNode
        // does elsewhere — nothing here needs to change visually.
        jsonSend('/api/roadmap-node/' + n.id, {x: n.x, y: n.y}, 'PATCH').then(res => {
          if (res.error) toast(res.error, {error: true});
          else Object.assign(n, res);
        });
      };
      el.addEventListener('pointerup', endDrag);
      el.addEventListener('pointercancel', endDrag);

      canvas.appendChild(el);
      els[n.id] = el;
    });

    drawEdges();

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
        note.textContent = action.resolved === 'accepted' ? '\\u2713 Applied' : '\\u2717 Dismissed';
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
        hint.textContent = 'Ask about this roadmap, or tell it what changed \\u2014 ' +
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
    chatInput.placeholder = 'Ask about this roadmap\\u2026';
    form.appendChild(chatInput);
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

  // ---------- profile ----------

  async function openProfileView(opts) {
    opts = opts || {};
    currentProject = null;
    current = null;
    showProfileView();
    $('breadcrumb').textContent = 'Profile';
    // A background refresh (after the assistant saves a proposed
    // profile) must not wipe the chat history it's about to redraw.
    if (!opts.background) profileChatLog = [];

    const view = $('profile-view');
    view.innerHTML = '<div class="muted">Loading profile\\u2026</div>';
    const data = await api('/api/profile');
    view.innerHTML = '';

    const layout = document.createElement('div');
    layout.className = 'proj-layout';
    const main = document.createElement('div');
    main.className = 'proj-main';

    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'Profile';
    main.appendChild(title);

    const aboutCard = card('About you', 'Draft from my documents', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Drafting\\u2026';
      const res = await api('/api/profile/draft', {method: 'POST'});
      btn.disabled = false;
      btn.textContent = 'Draft from my documents';
      if (res.error) { toast(res.error, {error: true}); return; }
      box.value = res.draft;
      box.oninput();
      toast('Draft generated \\u2014 review and save');
    });

    const box = document.createElement('textarea');
    box.value = data.content || '';
    box.placeholder = 'Tell mindtrail about yourself \\u2014 role, goals, background. ' +
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

    main.appendChild(aboutCard);
    layout.appendChild(main);

    const rail = document.createElement('div');
    rail.className = 'proj-rail';
    const assistantCard = buildAssistantCard(
      'Profile Assistant',
      'Talk through what to put in your profile \\u2014 it can propose ' +
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

  // Notes were CLI-only until now, and the CLI version stores them with
  // no conversation attached - unreachable from the browser even after
  // the fact. This always creates one, so a note shows up in the
  // sidebar exactly like a chat or a document would.
  $('add-note').onclick = async () => {
    const text = await modal({
      title: 'New note', input: true, multiline: true,
      placeholder: 'Jot something down\\u2026', confirmLabel: 'Save',
    });
    if (!text) return;
    const res = await jsonSend('/api/note', {text});
    if (res.error) { toast(res.error, {error: true}); return; }
    await loadSidebar();
    showChatView();
    await openConversation(res.conversation_id);
    toast('Note saved');
  };

  // ---------- search ----------
  // Semantic search over everything stored - the app's core retrieval,
  // otherwise only reachable indirectly through a follow-up question.

  (() => {
    const input = $('search-input');
    const results = $('search-results');
    let debounceTimer = null;
    let latestQuery = '';

    function closeResults() {
      results.classList.remove('open');
      results.innerHTML = '';
    }

    function renderResults(items, query) {
      results.innerHTML = '';
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.style.padding = '0.5rem 0.6rem';
        empty.textContent = 'No matches for "' + query + '".';
        results.appendChild(empty);
        results.classList.add('open');
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
        sub.textContent = subParts.join(' \\u00b7 ');
        item.appendChild(sub);
        makeClickable(item, () => {
          closeResults();
          input.value = '';
          if (r.conversation_id) {
            showChatView();
            openConversation(r.conversation_id);
          }
        });
        results.appendChild(item);
      });
      results.classList.add('open');
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

    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.blur(); closeResults(); }
    });

    document.addEventListener('click', e => {
      if (!e.target.closest('#search-box')) closeResults();
    });
  })();

  // ---------- dashboard ----------

  function dashItem(titleText, subText, onClick) {
    const item = document.createElement('div');
    item.className = 'dash-item';
    const t = document.createElement('div');
    t.className = 'dash-item-title';
    t.textContent = titleText;
    item.appendChild(t);
    if (subText) {
      const s = document.createElement('div');
      s.className = 'dash-item-sub';
      s.textContent = subText;
      item.appendChild(s);
    }
    makeClickable(item, onClick);
    return item;
  }

  async function openDashboardView() {
    currentProject = null;
    current = null;
    showDashboardView();
    $('breadcrumb').textContent = 'Today';

    const view = $('dashboard-view');
    view.innerHTML = '<div class="muted">Loading\\u2026</div>';
    const data = await api('/api/dashboard');
    view.innerHTML = '';

    const title = document.createElement('div');
    title.className = 'proj-title';
    title.textContent = 'Today';
    view.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'dash-grid';

    // Next up leads - accepted roadmap steps are the most actionable
    // thing on this screen, so they get first position, not third.
    const nextCard = card('Next up', null, null);
    if (!data.next_up.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'No accepted roadmap steps waiting yet.';
      nextCard.appendChild(p);
    }
    data.next_up.forEach(n => {
      const sub = n.project_name + (n.note ? ' \\u2014 ' + n.note : '');
      nextCard.appendChild(dashItem(n.title, sub,
                                    () => openRoadmapView(n.project_id, n.project_name)));
    });
    grid.appendChild(nextCard);

    const hlCard = card('Across your projects', null, null);
    if (!data.highlights.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing yet \\u2014 project highlights show up here.';
      hlCard.appendChild(p);
    }
    data.highlights.forEach(h => {
      hlCard.appendChild(dashItem(h.headline, h.project_name,
                                  () => openProject(h.project_id)));
    });
    grid.appendChild(hlCard);

    const recentCard = card('Recent', null, null);
    if (!data.recent.length) {
      const p = document.createElement('div');
      p.className = 'muted';
      p.textContent = 'Nothing yet \\u2014 start a chat to see it here.';
      recentCard.appendChild(p);
    }
    data.recent.forEach(c => {
      const sub = (c.project_name ? c.project_name + ' \\u00b7 ' : '') + relTime(c.updated_at);
      recentCard.appendChild(dashItem(c.title, sub,
                                      () => { showChatView(); openConversation(c.id); }));
    });
    grid.appendChild(recentCard);

    view.appendChild(grid);
  }

  $('brand').onclick = () => openDashboardView();

  // ---------- asking ----------

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
    const dismiss = toast('Uploading ' + f.name + '\\u2026', {seconds: 120});

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

  let recorder = null, chunks = [];
  $('mic').onclick = async () => {
    const mic = $('mic');
    if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = ev => chunks.push(ev.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        mic.classList.remove('recording');
        mic.title = mic.ariaLabel = 'Dictate';
        setStatus('Transcribing\\u2026');
        const blob = new Blob(chunks, {type: 'audio/webm'});
        const res = await fetch('/api/transcribe', {method: 'POST', body: blob});
        const data = await res.json();
        if (data.error) { setStatus('Dictation failed: ' + data.error); return; }
        setStatus('');
        input.value = (input.value ? input.value + ' ' : '') + data.text;
        input.focus();
      };
      recorder.start();
      mic.classList.add('recording');
      mic.title = mic.ariaLabel = 'Stop recording';
      setStatus('Recording\\u2026 click the mic again to stop.');
    } catch (err) {
      setStatus('Microphone unavailable: ' + err.message);
    }
  };

  openDashboardView();
  updateNav();
  loadSidebar();
  </script>
</body>
</html>"""
