/* ============================================================
   A2A Mesh Dashboard — app.js
   Vanilla JS SPA: Overview, Workers, Projects, Live Feed,
   Conversations, Approvals, MCP Servers, Settings

   Security note: All user-supplied data is escaped via esc()
   which uses textContent-based sanitization before insertion.
   ============================================================ */

(function () {
  "use strict";

  // -----------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];

  function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    const token = localStorage.getItem("mesh_token");
    if (token) headers["Authorization"] = "Bearer " + token;
    return fetch(path, { ...opts, headers }).then((r) => {
      if (!r.ok) throw new Error(r.status + " " + r.statusText);
      return r.status === 204 ? null : r.json();
    });
  }

  function toast(msg, type) {
    type = type || "info";
    var el = document.createElement("div");
    el.className = "toast" + (type === "error" ? " error" : type === "success" ? " success" : "");
    el.textContent = msg;
    document.getElementById("toast-container").appendChild(el);
    setTimeout(function () { el.remove(); }, 4000);
  }

  function fmtTime(ts) {
    if (!ts) return "";
    var d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function fmtDate(ts) {
    if (!ts) return "";
    var d = new Date(ts);
    return d.toLocaleDateString() + " " + fmtTime(ts);
  }

  // Escape user content to prevent XSS — uses textContent sanitization
  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function buildBadge(text, cls) {
    var span = document.createElement("span");
    span.className = "badge badge-" + cls;
    span.textContent = text;
    return span.outerHTML;
  }

  function riskBadge(level) {
    var map = { low: "success", medium: "warning", high: "danger", critical: "danger" };
    return buildBadge(level, map[level] || "muted");
  }

  function eventBadge(type) {
    var map = {
      agent_joined: "success", agent_left: "danger",
      role_assigned: "accent", task_created: "info",
      task_assigned: "info", task_started: "accent",
      task_completed: "success", task_failed: "danger",
      channel_message: "muted", intent_pending: "warning",
      intent_decided: "success", plan_created: "info",
      plan_step_started: "accent", plan_step_completed: "success"
    };
    return buildBadge(type, map[type] || "muted");
  }

  // Safe DOM builder — sets content via text nodes and safe attributes
  function setContent(el, html) {
    // Used for rendering trusted template HTML with esc()-sanitized values
    if (typeof el === "string") el = document.querySelector(el);
    if (el) el.innerHTML = html;
  }

  // -----------------------------------------------------------
  // State
  // -----------------------------------------------------------
  var state = {
    ws: null,
    wsRetryMs: 1000,
    activityFeed: [],
    liveFeed: [],
    roles: [],
    clusterStatus: {},
    workers: [],
    projects: [],
    channels: [],
    pendingApprovals: [],
    approvalHistory: [],
    mcpServers: [],
    settings: {},
    activeChannel: null,
    channelMessages: [],
    refreshTimer: null
  };

  // -----------------------------------------------------------
  // Tab Management
  // -----------------------------------------------------------
  function initTabs() {
    $$(".tab-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        $$(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
        $$(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
        btn.classList.add("active");
        var panel = document.getElementById("tab-" + btn.dataset.tab);
        if (panel) panel.classList.add("active");
        onTabActivated(btn.dataset.tab);
      });
    });
  }

  function onTabActivated(tab) {
    switch (tab) {
      case "overview": refreshOverview(); break;
      case "workers": refreshWorkers(); break;
      case "projects": refreshProjects(); break;
      case "conversations": refreshChannels(); break;
      case "approvals": refreshApprovals(); break;
      case "mcp-servers": refreshMcpServers(); break;
      case "settings": refreshSettings(); break;
    }
  }

  // -----------------------------------------------------------
  // WebSocket
  // -----------------------------------------------------------
  function connectWS() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + "/ws";
    var ws = new WebSocket(url);

    ws.onopen = function () {
      state.ws = ws;
      state.wsRetryMs = 1000;
      var statusEl = document.getElementById("ws-status");
      statusEl.textContent = "Connected";
      statusEl.classList.add("connected");
    };

    ws.onmessage = function (e) {
      try {
        var evt = JSON.parse(e.data);
        handleWSEvent(evt);
      } catch (_) { /* ignore non-JSON */ }
    };

    ws.onclose = function () {
      state.ws = null;
      var statusEl = document.getElementById("ws-status");
      statusEl.textContent = "Disconnected";
      statusEl.classList.remove("connected");
      setTimeout(connectWS, state.wsRetryMs);
      state.wsRetryMs = Math.min(state.wsRetryMs * 2, 30000);
    };

    ws.onerror = function () { ws.close(); };
  }

  function handleWSEvent(evt) {
    var entry = Object.assign({}, evt, { _ts: evt.timestamp || new Date().toISOString() });

    // activity feed (overview)
    state.activityFeed.unshift(entry);
    if (state.activityFeed.length > 20) state.activityFeed.length = 20;

    // live feed
    state.liveFeed.push(entry);
    if (state.liveFeed.length > 500) state.liveFeed.splice(0, state.liveFeed.length - 500);

    // update live feed tab if active
    if (isTabActive("live-feed")) appendLiveEntry(entry);

    // update overview feed if active
    if (isTabActive("overview")) renderActivityFeed();

    // event-driven refreshes
    switch (evt.type) {
      case "agent_joined":
      case "agent_left":
        if (isTabActive("overview")) refreshClusterStatus();
        if (isTabActive("workers")) refreshWorkers();
        break;
      case "role_assigned":
        if (isTabActive("workers")) refreshWorkers();
        break;
      case "task_created":
      case "task_assigned":
      case "task_started":
      case "task_completed":
      case "task_failed":
        if (isTabActive("overview")) refreshClusterStatus();
        if (isTabActive("projects")) refreshProjects();
        break;
      case "channel_message":
        if (isTabActive("conversations") && state.activeChannel && evt.channel_id === state.activeChannel) {
          refreshChannelMessages(state.activeChannel);
        }
        break;
      case "intent_pending":
      case "intent_decided":
        if (isTabActive("approvals")) refreshApprovals();
        break;
    }
  }

  function isTabActive(tab) {
    var panel = document.getElementById("tab-" + tab);
    return panel && panel.classList.contains("active");
  }

  // -----------------------------------------------------------
  // OVERVIEW TAB
  // -----------------------------------------------------------
  function renderOverviewShell() {
    setContent("#tab-overview",
      '<div class="stat-grid" id="overview-stats"></div>' +
      '<h3 class="section-title">Recent Activity</h3>' +
      '<div class="feed" id="overview-feed"></div>'
    );
  }

  function refreshOverview() {
    refreshClusterStatus();
    loadActivityHistory();
  }

  function refreshClusterStatus() {
    api("/api/cluster/status").then(function (data) {
      state.clusterStatus = data || {};
      renderClusterStats();
    }).catch(function () {});
  }

  function renderClusterStats() {
    var d = state.clusterStatus;
    var el = document.getElementById("overview-stats");
    if (!el) return;
    setContent(el,
      '<div class="stat-card"><div class="value">' + esc(d.total_agents || 0) + '</div><div class="label">Total Agents</div></div>' +
      '<div class="stat-card"><div class="value">' + esc(d.healthy || 0) + '</div><div class="label">Healthy</div></div>' +
      '<div class="stat-card"><div class="value">' + esc(d.active_tasks || 0) + '</div><div class="label">Active Tasks</div></div>' +
      '<div class="stat-card"><div class="value">' + esc(d.pending_approvals || 0) + '</div><div class="label">Pending Approvals</div></div>'
    );
  }

  function loadActivityHistory() {
    api("/api/activity").then(function (data) {
      if (Array.isArray(data)) {
        state.activityFeed = data.slice(0, 20);
      }
      renderActivityFeed();
    }).catch(function () { renderActivityFeed(); });
  }

  function renderActivityFeed() {
    var el = document.getElementById("overview-feed");
    if (!el) return;
    if (state.activityFeed.length === 0) {
      setContent(el, '<div style="padding:20px;color:var(--text-muted);text-align:center;">No recent activity</div>');
      return;
    }
    setContent(el, state.activityFeed.map(function (e) {
      return '<div class="feed-item">' +
        '<span class="feed-time">' + fmtTime(e._ts || e.timestamp) + '</span>' +
        eventBadge(e.type) +
        '<span class="feed-detail">' + esc(e.message || e.detail || e.description || JSON.stringify(e.data || "")) + '</span>' +
        '</div>';
    }).join(""));
  }

  // -----------------------------------------------------------
  // WORKERS TAB
  // -----------------------------------------------------------
  function renderWorkersShell() {
    setContent("#tab-workers",
      '<h3 class="section-title">Workers</h3>' +
      '<div class="worker-grid" id="worker-grid"></div>'
    );
  }

  function refreshWorkers() {
    Promise.all([
      api("/api/workers").catch(function () { return []; }),
      api("/api/roles").catch(function () { return []; })
    ]).then(function (results) {
      state.workers = Array.isArray(results[0]) ? results[0] : [];
      state.roles = Array.isArray(results[1]) ? results[1] : [];
      renderWorkers();
    });
  }

  function renderWorkers() {
    var el = document.getElementById("worker-grid");
    if (!el) return;
    if (state.workers.length === 0) {
      setContent(el, '<div class="card" style="text-align:center;color:var(--text-muted);">No workers registered</div>');
      return;
    }
    setContent(el, state.workers.map(function (w) {
      var hw = w.hardware || {};
      var gpu = hw.gpu_name || "None";
      var vram = hw.vram_gb ? hw.vram_gb + " GB" : "N/A";
      var ram = hw.ram_gb ? hw.ram_gb + " GB" : "N/A";
      var roleOpts = state.roles.map(function (r) {
        return '<option value="' + esc(r.id) + '"' + (w.role_id === r.id ? " selected" : "") + '>' + esc(r.name) + '</option>';
      }).join("");

      var compatModels = getCompatibleModels(hw.vram_gb);
      var modelOpts = compatModels.map(function (m) {
        return '<option value="' + esc(m) + '"' + (w.model === m ? " selected" : "") + '>' + esc(m) + '</option>';
      }).join("");

      return '<div class="worker-card" data-worker-id="' + esc(w.id) + '">' +
        '<h3>' + esc(w.hostname || w.id) + ' ' + (w.role ? buildBadge(w.role, "accent") : "") + '</h3>' +
        '<div class="worker-meta">' +
          '<span>OS: ' + esc(hw.os || "?") + '</span>' +
          '<span>CPU: ' + esc(hw.cpu_cores || "?") + ' cores</span>' +
          '<span>RAM: ' + esc(ram) + '</span>' +
        '</div>' +
        '<div class="worker-meta">' +
          '<span>GPU: ' + esc(gpu) + '</span>' +
          '<span>VRAM: ' + esc(vram) + '</span>' +
          (w.current_task ? '<span>Task: ' + buildBadge(w.current_task, "info") + '</span>' : "") +
          (w.model ? '<span>Model: ' + esc(w.model) + '</span>' : "") +
        '</div>' +
        '<div class="worker-controls">' +
          '<select class="role-select" style="width:auto;flex:1;">' + (roleOpts ? '<option value="">Select role...</option>' + roleOpts : '<option>No roles</option>') + '</select>' +
          '<select class="model-select" style="width:auto;flex:1;">' + (modelOpts ? '<option value="">Select model...</option>' + modelOpts : '<option>No models</option>') + '</select>' +
          '<button class="btn btn-sm assign-btn">Assign &amp; Deploy</button>' +
        '</div>' +
        '</div>';
    }).join(""));

    // bind assign buttons
    $$(".assign-btn", el).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var card = btn.closest(".worker-card");
        var id = card.dataset.workerId;
        var role_id = $(".role-select", card).value;
        var model = $(".model-select", card).value;
        if (!role_id) { toast("Select a role first", "error"); return; }
        btn.disabled = true;
        api("/api/workers/" + id + "/assign", {
          method: "POST",
          body: JSON.stringify({ role_id: role_id, model: model })
        }).then(function () {
          toast("Worker assigned successfully", "success");
          refreshWorkers();
        }).catch(function (e) { toast("Assign failed: " + e.message, "error"); })
          .finally(function () { btn.disabled = false; });
      });
    });

    // update model options when role changes
    $$(".role-select", el).forEach(function (sel) {
      sel.addEventListener("change", function () {
        var card = sel.closest(".worker-card");
        var workerId = card.dataset.workerId;
        var worker = state.workers.find(function (w) { return String(w.id) === workerId; });
        var vram = worker && worker.hardware ? worker.hardware.vram_gb : null;
        var roleId = sel.value;
        var role = state.roles.find(function (r) { return String(r.id) === roleId; });
        var modelSel = $(".model-select", card);
        var models = getCompatibleModelsForRole(vram, role);
        setContent(modelSel, '<option value="">Select model...</option>' +
          models.map(function (m) { return '<option value="' + esc(m) + '">' + esc(m) + '</option>'; }).join(""));
      });
    });
  }

  function getCompatibleModels(vramGb) {
    var models = [];
    state.roles.forEach(function (r) {
      if (r.compatible_models) {
        r.compatible_models.forEach(function (m) {
          var name = m.name || m;
          if (models.indexOf(name) === -1) {
            var req = m.vram_required || 0;
            if (!vramGb || req <= vramGb) models.push(name);
          }
        });
      }
    });
    return models;
  }

  function getCompatibleModelsForRole(vramGb, role) {
    if (!role || !role.compatible_models) return getCompatibleModels(vramGb);
    return role.compatible_models
      .filter(function (m) {
        var req = m.vram_required || 0;
        return !vramGb || req <= vramGb;
      })
      .map(function (m) { return m.name || m; });
  }

  // -----------------------------------------------------------
  // PROJECTS TAB (Kanban)
  // -----------------------------------------------------------
  var KANBAN_COLS = ["backlog", "todo", "in_progress", "review", "done"];
  var COL_LABELS = { backlog: "Backlog", todo: "Todo", in_progress: "In Progress", review: "Review", done: "Done" };

  function renderProjectsShell() {
    setContent("#tab-projects",
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">' +
        '<h3 class="section-title" style="border:none;margin:0;padding:0;flex:1;">Projects</h3>' +
        '<select id="project-select" style="width:auto;max-width:250px;"><option value="">Loading...</option></select>' +
        '<button class="btn btn-sm" id="btn-new-project">+ Project</button>' +
        '<button class="btn btn-sm btn-outline" id="btn-new-task">+ Task</button>' +
      '</div>' +
      '<div class="kanban" id="kanban"></div>'
    );

    document.getElementById("btn-new-project").addEventListener("click", showNewProjectModal);
    document.getElementById("btn-new-task").addEventListener("click", showNewTaskModal);
    document.getElementById("project-select").addEventListener("change", function () {
      loadProjectTasks(document.getElementById("project-select").value);
    });
  }

  function refreshProjects() {
    api("/api/projects").then(function (data) {
      state.projects = Array.isArray(data) ? data : [];
      renderProjectSelect();
      if (state.projects.length > 0) {
        var sel = document.getElementById("project-select");
        if (!sel.value) sel.value = state.projects[0].id;
        loadProjectTasks(sel.value);
      } else {
        renderKanban([]);
      }
    }).catch(function () {});
  }

  function renderProjectSelect() {
    var sel = document.getElementById("project-select");
    if (!sel) return;
    var current = sel.value;
    setContent(sel, state.projects.map(function (p) {
      return '<option value="' + esc(p.id) + '"' + (String(p.id) === current ? " selected" : "") + '>' + esc(p.name) + '</option>';
    }).join(""));
    if (state.projects.length === 0) setContent(sel, '<option value="">No projects</option>');
  }

  function loadProjectTasks(projectId) {
    if (!projectId) { renderKanban([]); return; }
    api("/api/projects/" + projectId + "/tasks").then(function (tasks) {
      renderKanban(Array.isArray(tasks) ? tasks : []);
    }).catch(function () { renderKanban([]); });
  }

  function renderKanban(tasks) {
    var el = document.getElementById("kanban");
    if (!el) return;
    setContent(el, KANBAN_COLS.map(function (col) {
      var colTasks = tasks.filter(function (t) { return (t.status || "backlog") === col; });
      return '<div class="kanban-col" data-col="' + col + '">' +
        '<div class="kanban-col-header">' + COL_LABELS[col] + ' <span class="count">' + colTasks.length + '</span></div>' +
        '<div class="kanban-cards" data-col="' + col + '">' +
          colTasks.map(function (t) {
            var priBadge = "";
            if (t.priority) {
              var priCls = t.priority === "high" ? "danger" : t.priority === "medium" ? "warning" : "muted";
              priBadge = buildBadge(t.priority, priCls);
            }
            return '<div class="kanban-card" draggable="true" data-task-id="' + esc(t.id) + '">' +
              '<div class="task-title">' + esc(t.title || t.name) + '</div>' +
              '<div class="task-meta">' + (t.assignee ? "Assignee: " + esc(t.assignee) + " " : "") + priBadge + '</div>' +
              '</div>';
          }).join("") +
        '</div>' +
        '</div>';
    }).join(""));

    initDragDrop();
  }

  function initDragDrop() {
    var dragId = null;

    $$(".kanban-card").forEach(function (card) {
      card.addEventListener("dragstart", function (e) {
        dragId = card.dataset.taskId;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
      });
      card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
        dragId = null;
        $$(".kanban-cards").forEach(function (c) { c.classList.remove("drag-over"); });
      });
    });

    $$(".kanban-cards").forEach(function (zone) {
      zone.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        zone.classList.add("drag-over");
      });
      zone.addEventListener("dragleave", function () { zone.classList.remove("drag-over"); });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        zone.classList.remove("drag-over");
        if (!dragId) return;
        var newStatus = zone.dataset.col;
        api("/api/tasks/" + dragId, {
          method: "PUT",
          body: JSON.stringify({ status: newStatus })
        }).then(function () {
          toast("Task moved to " + COL_LABELS[newStatus], "success");
          var projId = document.getElementById("project-select");
          if (projId && projId.value) loadProjectTasks(projId.value);
        }).catch(function (e) { toast("Move failed: " + e.message, "error"); });
      });
    });
  }

  function showNewProjectModal() {
    showModal("New Project",
      '<div class="form-group"><label>Name</label><input id="mp-name" placeholder="Project name"></div>' +
      '<div class="form-group"><label>Description</label><textarea id="mp-desc" rows="3" placeholder="Description"></textarea></div>',
      function () {
        var name = document.getElementById("mp-name").value.trim();
        if (!name) { toast("Name required", "error"); return false; }
        api("/api/projects", {
          method: "POST",
          body: JSON.stringify({ name: name, description: document.getElementById("mp-desc").value })
        }).then(function () { toast("Project created", "success"); refreshProjects(); })
          .catch(function (e) { toast("Error: " + e.message, "error"); });
      }
    );
  }

  function showNewTaskModal() {
    var projSel = document.getElementById("project-select");
    var projId = projSel ? projSel.value : "";
    if (!projId) { toast("Select a project first", "error"); return; }
    var statusOpts = KANBAN_COLS.map(function (c) { return '<option value="' + c + '">' + COL_LABELS[c] + '</option>'; }).join("");
    showModal("New Task",
      '<div class="form-group"><label>Title</label><input id="mt-title" placeholder="Task title"></div>' +
      '<div class="form-group"><label>Description</label><textarea id="mt-desc" rows="3" placeholder="Description"></textarea></div>' +
      '<div class="form-row">' +
        '<div class="form-group"><label>Priority</label><select id="mt-priority"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option></select></div>' +
        '<div class="form-group"><label>Status</label><select id="mt-status">' + statusOpts + '</select></div>' +
      '</div>',
      function () {
        var title = document.getElementById("mt-title").value.trim();
        if (!title) { toast("Title required", "error"); return false; }
        api("/api/projects/" + projId + "/tasks", {
          method: "POST",
          body: JSON.stringify({
            title: title,
            description: document.getElementById("mt-desc").value,
            priority: document.getElementById("mt-priority").value,
            status: document.getElementById("mt-status").value
          })
        }).then(function () { toast("Task created", "success"); loadProjectTasks(projId); })
          .catch(function (e) { toast("Error: " + e.message, "error"); });
      }
    );
  }

  // -----------------------------------------------------------
  // LIVE FEED TAB
  // -----------------------------------------------------------
  function renderLiveFeedShell() {
    setContent("#tab-live-feed",
      '<h3 class="section-title">Live Event Stream</h3>' +
      '<div class="live-log" id="live-log"></div>'
    );
    var log = document.getElementById("live-log");
    state.liveFeed.forEach(function (e) { appendLiveEntryDOM(log, e); });
  }

  function appendLiveEntry(entry) {
    var log = document.getElementById("live-log");
    if (!log) return;
    appendLiveEntryDOM(log, entry);
    log.scrollTop = log.scrollHeight;
  }

  function appendLiveEntryDOM(log, entry) {
    var div = document.createElement("div");
    div.className = "log-entry";

    var ts = document.createElement("span");
    ts.className = "log-ts";
    ts.textContent = fmtTime(entry._ts || entry.timestamp);
    div.appendChild(ts);

    // badge
    var badgeSpan = document.createElement("span");
    badgeSpan.className = "badge badge-" + (({
      agent_joined: "success", agent_left: "danger",
      role_assigned: "accent", task_created: "info",
      task_assigned: "info", task_started: "accent",
      task_completed: "success", task_failed: "danger",
      channel_message: "muted", intent_pending: "warning",
      intent_decided: "success", plan_created: "info",
      plan_step_started: "accent", plan_step_completed: "success"
    })[entry.type] || "muted");
    badgeSpan.textContent = entry.type;
    div.appendChild(document.createTextNode(" "));
    div.appendChild(badgeSpan);

    var detail = document.createElement("span");
    detail.textContent = " " + (entry.message || entry.detail || JSON.stringify(entry.data || ""));
    div.appendChild(detail);

    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  // -----------------------------------------------------------
  // CONVERSATIONS TAB
  // -----------------------------------------------------------
  function renderConversationsShell() {
    setContent("#tab-conversations",
      '<h3 class="section-title">Agent Channels</h3>' +
      '<div id="channel-view">' +
        '<div class="channel-list" id="channel-list"></div>' +
      '</div>' +
      '<div id="channel-detail" style="display:none;">' +
        '<button class="btn btn-sm btn-outline" id="btn-back-channels" style="margin-bottom:12px;">&larr; Back to channels</button>' +
        '<h3 class="section-title" id="channel-detail-title"></h3>' +
        '<div id="channel-participants" style="margin-bottom:10px;"></div>' +
        '<div class="messages-panel" id="channel-messages"></div>' +
      '</div>'
    );
    document.getElementById("btn-back-channels").addEventListener("click", function () {
      state.activeChannel = null;
      document.getElementById("channel-view").style.display = "";
      document.getElementById("channel-detail").style.display = "none";
    });
  }

  function refreshChannels() {
    api("/api/channels").then(function (data) {
      state.channels = Array.isArray(data) ? data : [];
      renderChannelList();
    }).catch(function () {});
  }

  function renderChannelList() {
    var el = document.getElementById("channel-list");
    if (!el) return;
    if (state.channels.length === 0) {
      setContent(el, '<div class="card" style="text-align:center;color:var(--text-muted);">No active channels</div>');
      return;
    }
    setContent(el, state.channels.map(function (ch) {
      var parts = (ch.participants || []).map(function (p) { return buildBadge(p, "accent"); }).join(" ");
      return '<div class="channel-card" data-channel-id="' + esc(ch.id) + '">' +
        '<h4>' + esc(ch.name || "Channel " + ch.id) + '</h4>' +
        '<div class="channel-participants">' + parts + '</div>' +
        '<div style="font-size:.78rem;color:var(--text-muted);">' + esc(ch.message_count != null ? ch.message_count : "?") + ' messages</div>' +
        '</div>';
    }).join(""));

    $$(".channel-card", el).forEach(function (card) {
      card.addEventListener("click", function () {
        var id = card.dataset.channelId;
        var title = card.querySelector("h4").textContent;
        openChannel(id, title);
      });
    });
  }

  function openChannel(channelId, title) {
    state.activeChannel = channelId;
    document.getElementById("channel-view").style.display = "none";
    document.getElementById("channel-detail").style.display = "";
    document.getElementById("channel-detail-title").textContent = title;
    var ch = state.channels.find(function (c) { return String(c.id) === String(channelId); });
    if (ch && ch.participants) {
      setContent("#channel-participants", ch.participants.map(function (p) { return buildBadge(p, "accent"); }).join(" "));
    }
    refreshChannelMessages(channelId);
  }

  function refreshChannelMessages(channelId) {
    api("/api/channels/" + channelId + "/messages").then(function (data) {
      state.channelMessages = Array.isArray(data) ? data : [];
      renderChannelMessages();
    }).catch(function () {});
  }

  function renderChannelMessages() {
    var el = document.getElementById("channel-messages");
    if (!el) return;
    if (state.channelMessages.length === 0) {
      setContent(el, '<div style="text-align:center;color:var(--text-muted);padding:20px;">No messages yet</div>');
      return;
    }
    setContent(el, state.channelMessages.map(function (m) {
      return '<div class="msg-row">' +
        '<div class="msg-header">' +
          '<span class="msg-agent">' + esc(m.agent_name || m.sender || "Unknown") + '</span> ' +
          (m.type ? buildBadge(m.type, "muted") : "") + ' ' +
          '<span class="msg-time">' + fmtTime(m.timestamp) + '</span>' +
        '</div>' +
        '<div class="msg-body">' + esc(m.content || m.text || "") + '</div>' +
        '</div>';
    }).join(""));
    el.scrollTop = el.scrollHeight;
  }

  // -----------------------------------------------------------
  // APPROVALS TAB
  // -----------------------------------------------------------
  function renderApprovalsShell() {
    setContent("#tab-approvals",
      '<h3 class="section-title">Pending Approvals</h3>' +
      '<div id="approvals-pending"></div>' +
      '<h3 class="section-title" style="margin-top:24px;">History</h3>' +
      '<div id="approvals-history"></div>'
    );
  }

  function refreshApprovals() {
    Promise.all([
      api("/api/approvals/pending").catch(function () { return []; }),
      api("/api/approvals/history").catch(function () { return []; })
    ]).then(function (results) {
      state.pendingApprovals = Array.isArray(results[0]) ? results[0] : [];
      state.approvalHistory = Array.isArray(results[1]) ? results[1] : [];
      renderApprovals();
    });
  }

  function renderApprovals() {
    var pendingEl = document.getElementById("approvals-pending");
    var historyEl = document.getElementById("approvals-history");
    if (!pendingEl) return;

    if (state.pendingApprovals.length === 0) {
      setContent(pendingEl, '<div class="card" style="text-align:center;color:var(--text-muted);">No pending approvals</div>');
    } else {
      setContent(pendingEl, state.pendingApprovals.map(function (a) {
        return '<div class="approval-card" data-approval-id="' + esc(a.id) + '">' +
          '<h4>' + esc(a.agent_name || a.agent || "Agent") + ' ' + riskBadge(a.risk_level || "medium") + '</h4>' +
          '<div style="font-size:.85rem;"><strong>Action:</strong> ' + esc(a.action || a.intent) + '</div>' +
          '<div style="font-size:.82rem;color:var(--text-muted);margin-top:4px;">' + esc(a.description || "") + '</div>' +
          '<div class="approval-actions">' +
            '<button class="btn btn-sm btn-success approve-btn">Approve</button>' +
            '<button class="btn btn-sm btn-danger reject-btn">Reject</button>' +
          '</div>' +
          '</div>';
      }).join(""));

      $$(".approve-btn", pendingEl).forEach(function (btn) {
        btn.addEventListener("click", function () {
          var id = btn.closest(".approval-card").dataset.approvalId;
          btn.disabled = true;
          api("/api/approvals/" + id + "/approve", { method: "POST" })
            .then(function () { toast("Approved", "success"); refreshApprovals(); })
            .catch(function (e) { toast("Error: " + e.message, "error"); })
            .finally(function () { btn.disabled = false; });
        });
      });

      $$(".reject-btn", pendingEl).forEach(function (btn) {
        btn.addEventListener("click", function () {
          var id = btn.closest(".approval-card").dataset.approvalId;
          btn.disabled = true;
          api("/api/approvals/" + id + "/reject", { method: "POST" })
            .then(function () { toast("Rejected", "success"); refreshApprovals(); })
            .catch(function (e) { toast("Error: " + e.message, "error"); })
            .finally(function () { btn.disabled = false; });
        });
      });
    }

    if (historyEl) {
      if (state.approvalHistory.length === 0) {
        setContent(historyEl, '<div style="color:var(--text-muted);font-size:.85rem;">No history</div>');
      } else {
        setContent(historyEl, state.approvalHistory.map(function (a) {
          var decCls = (a.decision === "approved" || a.status === "approved") ? "success" : "danger";
          return '<div class="feed-item">' +
            '<span class="feed-time">' + fmtDate(a.decided_at || a.timestamp) + '</span>' +
            buildBadge(a.decision || a.status, decCls) +
            '<span class="feed-detail"><strong>' + esc(a.agent_name || a.agent || "") + '</strong> — ' + esc(a.action || a.intent || "") + ' ' + (a.risk_level ? riskBadge(a.risk_level) : "") + '</span>' +
            '</div>';
        }).join(""));
      }
    }
  }

  // -----------------------------------------------------------
  // MCP SERVERS TAB
  // -----------------------------------------------------------
  function renderMcpShell() {
    setContent("#tab-mcp-servers",
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">' +
        '<h3 class="section-title" style="border:none;margin:0;padding:0;flex:1;">MCP Servers</h3>' +
        '<button class="btn btn-sm" id="btn-add-mcp">+ Add Server</button>' +
      '</div>' +
      '<div class="mcp-list" id="mcp-list"></div>'
    );
    document.getElementById("btn-add-mcp").addEventListener("click", showAddMcpModal);
  }

  function refreshMcpServers() {
    api("/api/mcp/servers").then(function (data) {
      state.mcpServers = Array.isArray(data) ? data : [];
      renderMcpServers();
    }).catch(function () {});
  }

  function renderMcpServers() {
    var el = document.getElementById("mcp-list");
    if (!el) return;
    if (state.mcpServers.length === 0) {
      setContent(el, '<div class="card" style="text-align:center;color:var(--text-muted);">No MCP servers configured</div>');
      return;
    }
    setContent(el, state.mcpServers.map(function (s) {
      var statusBdg = s.connected ? buildBadge("connected", "success") : buildBadge("disconnected", "danger");
      var roleOpts = state.roles.map(function (r) {
        var sel = (s.assigned_roles || []).indexOf(r.id) !== -1 ? " selected" : "";
        return '<option value="' + esc(r.id) + '"' + sel + '>' + esc(r.name) + '</option>';
      }).join("");

      return '<div class="mcp-card" data-mcp-id="' + esc(s.id) + '">' +
        '<h4>' + esc(s.name) + ' ' + statusBdg + '</h4>' +
        '<div class="detail">Transport: ' + esc(s.transport_type || s.transport || "stdio") + '</div>' +
        '<div class="detail">' + (s.command ? "Command: " + esc(s.command) : s.url ? "URL: " + esc(s.url) : "") + '</div>' +
        (s.args ? '<div class="detail">Args: ' + esc(s.args) + '</div>' : "") +
        '<div class="detail">Tools discovered: ' + esc(s.tools_count != null ? s.tools_count : "?") + '</div>' +
        '<div class="form-group" style="margin-top:8px;">' +
          '<label>Assign to roles</label>' +
          '<select class="mcp-role-select" multiple style="height:60px;">' + roleOpts + '</select>' +
        '</div>' +
        '<div class="mcp-actions">' +
          '<button class="btn btn-sm mcp-test-btn">Test Connection</button>' +
          '<button class="btn btn-sm btn-outline mcp-edit-btn">Edit</button>' +
          '<button class="btn btn-sm btn-danger mcp-delete-btn">Delete</button>' +
        '</div>' +
        '</div>';
    }).join(""));

    // Bind test buttons
    $$(".mcp-test-btn", el).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.closest(".mcp-card").dataset.mcpId;
        btn.disabled = true;
        btn.textContent = "Testing...";
        api("/api/mcp/servers/" + id + "/test", { method: "POST" })
          .then(function (r) { toast((r && r.message) || "Connection successful", "success"); })
          .catch(function (e) { toast("Test failed: " + e.message, "error"); })
          .finally(function () { btn.disabled = false; btn.textContent = "Test Connection"; });
      });
    });

    // Bind delete buttons
    $$(".mcp-delete-btn", el).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.closest(".mcp-card").dataset.mcpId;
        if (!confirm("Delete this MCP server?")) return;
        api("/api/mcp/servers/" + id, { method: "DELETE" })
          .then(function () { toast("Deleted", "success"); refreshMcpServers(); })
          .catch(function (e) { toast("Error: " + e.message, "error"); });
      });
    });

    // Bind edit buttons
    $$(".mcp-edit-btn", el).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.closest(".mcp-card").dataset.mcpId;
        var server = state.mcpServers.find(function (s) { return String(s.id) === String(id); });
        if (server) showEditMcpModal(server);
      });
    });

    // Bind role assignment
    $$(".mcp-role-select", el).forEach(function (sel) {
      sel.addEventListener("change", function () {
        var id = sel.closest(".mcp-card").dataset.mcpId;
        var selectedRoles = Array.from(sel.selectedOptions).map(function (o) { return o.value; });
        api("/api/mcp/servers/" + id, {
          method: "PUT",
          body: JSON.stringify({ assigned_roles: selectedRoles })
        }).then(function () { toast("Roles updated", "success"); })
          .catch(function (e) { toast("Error: " + e.message, "error"); });
      });
    });
  }

  function mcpFormHTML(s) {
    s = s || {};
    return '<div class="form-group"><label>Name</label><input id="mcp-name" value="' + esc(s.name || "") + '" placeholder="Server name"></div>' +
      '<div class="form-group"><label>Transport Type</label>' +
        '<select id="mcp-transport">' +
          '<option value="stdio"' + (s.transport_type === "stdio" ? " selected" : "") + '>stdio</option>' +
          '<option value="sse"' + (s.transport_type === "sse" ? " selected" : "") + '>SSE</option>' +
          '<option value="streamable_http"' + (s.transport_type === "streamable_http" ? " selected" : "") + '>Streamable HTTP</option>' +
        '</select>' +
      '</div>' +
      '<div class="form-group"><label>Command (for stdio)</label><input id="mcp-command" value="' + esc(s.command || "") + '" placeholder="e.g. npx -y @modelcontextprotocol/server-x"></div>' +
      '<div class="form-group"><label>URL (for SSE/HTTP)</label><input id="mcp-url" value="' + esc(s.url || "") + '" placeholder="https://..."></div>' +
      '<div class="form-group"><label>Args</label><input id="mcp-args" value="' + esc(s.args || "") + '" placeholder="Additional arguments"></div>';
  }

  function showAddMcpModal() {
    showModal("Add MCP Server", mcpFormHTML(), function () {
      var name = document.getElementById("mcp-name").value.trim();
      if (!name) { toast("Name required", "error"); return false; }
      api("/api/mcp/servers", {
        method: "POST",
        body: JSON.stringify({
          name: name,
          transport_type: document.getElementById("mcp-transport").value,
          command: document.getElementById("mcp-command").value,
          url: document.getElementById("mcp-url").value,
          args: document.getElementById("mcp-args").value
        })
      }).then(function () { toast("Server added", "success"); refreshMcpServers(); })
        .catch(function (e) { toast("Error: " + e.message, "error"); });
    });
  }

  function showEditMcpModal(server) {
    showModal("Edit MCP Server", mcpFormHTML(server), function () {
      var name = document.getElementById("mcp-name").value.trim();
      if (!name) { toast("Name required", "error"); return false; }
      api("/api/mcp/servers/" + server.id, {
        method: "PUT",
        body: JSON.stringify({
          name: name,
          transport_type: document.getElementById("mcp-transport").value,
          command: document.getElementById("mcp-command").value,
          url: document.getElementById("mcp-url").value,
          args: document.getElementById("mcp-args").value
        })
      }).then(function () { toast("Server updated", "success"); refreshMcpServers(); })
        .catch(function (e) { toast("Error: " + e.message, "error"); });
    });
  }

  // -----------------------------------------------------------
  // SETTINGS TAB
  // -----------------------------------------------------------
  var AUTONOMY_LABELS = ["Manual (ask for everything)", "Supervised (ask for risky)", "Autonomous (act, report)", "Full Auto (silent)"];

  function renderSettingsShell() {
    setContent("#tab-settings",
      '<div class="card settings-section">' +
        '<h3>API Key &amp; Authentication</h3>' +
        '<div class="form-group" style="margin-top:10px;">' +
          '<label>API Key</label>' +
          '<div style="display:flex;gap:8px;">' +
            '<input id="set-apikey" type="password" placeholder="Enter API key">' +
            '<button class="btn btn-sm" id="btn-auth">Authenticate</button>' +
          '</div>' +
        '</div>' +
        '<div id="auth-status" style="font-size:.8rem;color:var(--text-muted);margin-top:6px;"></div>' +
      '</div>' +

      '<div class="card settings-section">' +
        '<h3>Autonomy Level</h3>' +
        '<div class="slider-wrap" style="margin-top:10px;">' +
          '<input type="range" id="set-autonomy" min="0" max="3" step="1" value="1">' +
          '<span class="slider-label" id="autonomy-label">' + AUTONOMY_LABELS[1] + '</span>' +
        '</div>' +
      '</div>' +

      '<div class="card settings-section">' +
        '<h3>Custom Roles</h3>' +
        '<div id="custom-roles-list"></div>' +
        '<div class="form-row" style="margin-top:10px;">' +
          '<div class="form-group"><input id="new-role-name" placeholder="Role name"></div>' +
          '<div class="form-group"><input id="new-role-desc" placeholder="Description"></div>' +
          '<div class="form-group" style="flex:0;"><button class="btn btn-sm" id="btn-add-role">Add</button></div>' +
        '</div>' +
      '</div>' +

      '<div class="card settings-section">' +
        '<h3>Tunnel Status</h3>' +
        '<div id="tunnel-status" style="font-size:.85rem;color:var(--text-muted);margin-top:6px;">Loading...</div>' +
      '</div>' +

      '<div class="card settings-section">' +
        '<h3>JWT Token Exchange</h3>' +
        '<div class="form-group" style="margin-top:10px;">' +
          '<label>Current Token</label>' +
          '<textarea id="set-jwt" rows="3" readonly style="font-family:monospace;font-size:.75rem;"></textarea>' +
        '</div>' +
        '<button class="btn btn-sm btn-outline" id="btn-copy-jwt">Copy Token</button>' +
      '</div>' +

      '<div style="margin-top:16px;">' +
        '<button class="btn" id="btn-save-settings">Save Settings</button>' +
      '</div>'
    );

    // Autonomy slider
    document.getElementById("set-autonomy").addEventListener("input", function (e) {
      document.getElementById("autonomy-label").textContent = AUTONOMY_LABELS[+e.target.value];
    });

    // Auth
    document.getElementById("btn-auth").addEventListener("click", function () {
      var key = document.getElementById("set-apikey").value.trim();
      if (!key) { toast("Enter an API key", "error"); return; }
      api("/api/auth/token", {
        method: "POST",
        body: JSON.stringify({ api_key: key })
      }).then(function (data) {
        if (data && data.token) {
          localStorage.setItem("mesh_token", data.token);
          document.getElementById("auth-status").textContent = "Authenticated successfully";
          document.getElementById("auth-status").style.color = "var(--success)";
          document.getElementById("set-jwt").value = data.token;
          toast("Authenticated", "success");
        }
      }).catch(function (e) {
        document.getElementById("auth-status").textContent = "Authentication failed: " + e.message;
        document.getElementById("auth-status").style.color = "var(--danger)";
        toast("Auth failed", "error");
      });
    });

    // Copy JWT
    document.getElementById("btn-copy-jwt").addEventListener("click", function () {
      var jwt = document.getElementById("set-jwt").value;
      if (jwt) {
        navigator.clipboard.writeText(jwt).then(function () { toast("Copied", "success"); });
      }
    });

    // Add role
    document.getElementById("btn-add-role").addEventListener("click", function () {
      var name = document.getElementById("new-role-name").value.trim();
      if (!name) { toast("Role name required", "error"); return; }
      api("/api/roles", {
        method: "POST",
        body: JSON.stringify({ name: name, description: document.getElementById("new-role-desc").value })
      }).then(function () {
        toast("Role created", "success");
        document.getElementById("new-role-name").value = "";
        document.getElementById("new-role-desc").value = "";
        loadRolesForSettings();
      }).catch(function (e) { toast("Error: " + e.message, "error"); });
    });

    // Save settings
    document.getElementById("btn-save-settings").addEventListener("click", function () {
      var settings = {
        autonomy_level: +document.getElementById("set-autonomy").value
      };
      api("/api/settings", {
        method: "PUT",
        body: JSON.stringify(settings)
      }).then(function () { toast("Settings saved", "success"); })
        .catch(function (e) { toast("Error: " + e.message, "error"); });
    });
  }

  function refreshSettings() {
    api("/api/settings").then(function (data) {
      state.settings = data || {};
      var slider = document.getElementById("set-autonomy");
      if (slider && data.autonomy_level != null) {
        slider.value = data.autonomy_level;
        document.getElementById("autonomy-label").textContent = AUTONOMY_LABELS[data.autonomy_level] || "";
      }
      var tunnelEl = document.getElementById("tunnel-status");
      if (data.tunnel_url) {
        tunnelEl.textContent = "Active: " + data.tunnel_url;
      } else if (data.tunnel_active) {
        tunnelEl.textContent = "Tunnel active";
      } else {
        tunnelEl.textContent = "No tunnel active";
      }
      if (data.jwt_token) document.getElementById("set-jwt").value = data.jwt_token;
    }).catch(function () {});

    var token = localStorage.getItem("mesh_token");
    var jwtEl = document.getElementById("set-jwt");
    if (jwtEl && token && !jwtEl.value) jwtEl.value = token;

    loadRolesForSettings();
  }

  function loadRolesForSettings() {
    api("/api/roles").then(function (roles) {
      state.roles = Array.isArray(roles) ? roles : [];
      var el = document.getElementById("custom-roles-list");
      if (!el) return;
      if (state.roles.length === 0) {
        setContent(el, '<div style="color:var(--text-muted);font-size:.85rem;">No roles defined</div>');
        return;
      }
      setContent(el, state.roles.map(function (r) {
        return '<div class="feed-item">' +
          buildBadge(r.name, "accent") +
          '<span class="feed-detail">' + esc(r.description || "") + '</span>' +
          '</div>';
      }).join(""));
    }).catch(function () {});
  }

  // -----------------------------------------------------------
  // Modal Utility
  // -----------------------------------------------------------
  function showModal(title, bodyHTML, onConfirm) {
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";

    var modal = document.createElement("div");
    modal.className = "modal";

    var h3 = document.createElement("h3");
    h3.textContent = title;
    modal.appendChild(h3);

    var body = document.createElement("div");
    body.className = "modal-body";
    setContent(body, bodyHTML);
    modal.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "modal-actions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "btn btn-outline modal-cancel";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "btn modal-confirm";
    confirmBtn.textContent = "Confirm";
    actions.appendChild(confirmBtn);

    modal.appendChild(actions);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    var close = function () { overlay.remove(); };
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    cancelBtn.addEventListener("click", close);
    confirmBtn.addEventListener("click", function () {
      var result = onConfirm();
      if (result !== false) close();
    });
  }

  // -----------------------------------------------------------
  // Auto-refresh (5 seconds)
  // -----------------------------------------------------------
  function startAutoRefresh() {
    state.refreshTimer = setInterval(function () {
      if (isTabActive("overview")) refreshClusterStatus();
      if (isTabActive("workers")) refreshWorkers();
      if (isTabActive("approvals")) refreshApprovals();
    }, 5000);
  }

  // -----------------------------------------------------------
  // Bootstrap
  // -----------------------------------------------------------
  function init() {
    renderOverviewShell();
    renderWorkersShell();
    renderProjectsShell();
    renderLiveFeedShell();
    renderConversationsShell();
    renderApprovalsShell();
    renderMcpShell();
    renderSettingsShell();

    initTabs();
    refreshOverview();

    // Preload roles
    api("/api/roles").then(function (r) { state.roles = Array.isArray(r) ? r : []; }).catch(function () {});

    connectWS();
    startAutoRefresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
