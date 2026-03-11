"""REST API backend for the Web UI — all phases."""

from __future__ import annotations

import logging
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, FileResponse
from starlette.routing import Route, Router, Mount
from starlette.staticfiles import StaticFiles

from mesh.network.registry import get_registry
from mesh.orchestrator.intent import IntentQueue

logger = logging.getLogger(__name__)

# Module-level references set during server setup
_intent_queue: IntentQueue | None = None
_orchestrator = None
_role_manager = None
_channel_manager = None
_mcp_registry = None
_memory_store = None
_knowledge_base = None
_project_manager = None
_tunnel_manager = None
_activity_log: list[dict] = []

MAX_ACTIVITY = 200


def set_orchestrator(orchestrator):
    global _orchestrator, _intent_queue
    _orchestrator = orchestrator
    if orchestrator:
        _intent_queue = orchestrator.intent_queue


def set_role_manager(role_manager):
    global _role_manager
    _role_manager = role_manager


def set_channel_manager(channel_manager):
    global _channel_manager
    _channel_manager = channel_manager


def set_mcp_registry(mcp_registry):
    global _mcp_registry
    _mcp_registry = mcp_registry


def set_memory_store(memory_store):
    global _memory_store
    _memory_store = memory_store


def set_knowledge_base(knowledge_base):
    global _knowledge_base
    _knowledge_base = knowledge_base


def set_project_manager(project_manager):
    global _project_manager
    _project_manager = project_manager


def set_tunnel_manager(tunnel_manager):
    global _tunnel_manager
    _tunnel_manager = tunnel_manager


def log_activity(event_type: str, detail: str, agent: str = ""):
    from datetime import datetime, timezone
    entry = {
        "type": event_type,
        "detail": detail,
        "agent": agent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _activity_log.append(entry)
    if len(_activity_log) > MAX_ACTIVITY:
        _activity_log.pop(0)


# ---- Dashboard ----


STATIC_DIR = Path(__file__).parent / "static"


async def handle_dashboard(request: Request) -> HTMLResponse | FileResponse:
    """GET / — Serve the dashboard."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>A2A Mesh</h1><p>Dashboard static files not found.</p>")


# ---- Cluster Status ----


async def handle_cluster_status(request: Request) -> JSONResponse:
    """GET /api/cluster/status — Cluster overview."""
    registry = get_registry()
    agents = registry.get_all_agents()
    healthy = [a for a in agents if a.healthy]
    return JSONResponse({
        "total_agents": len(agents),
        "healthy_agents": len(healthy),
        "agents": [a.to_dict() for a in agents],
    })


async def handle_agents(request: Request) -> JSONResponse:
    """GET /api/agents — List all agents."""
    registry = get_registry()
    return JSONResponse([a.to_dict() for a in registry.get_all_agents()])


async def handle_agent_detail(request: Request) -> JSONResponse:
    """GET /api/agents/{agent_id} — Agent detail."""
    agent_id = request.path_params["agent_id"]
    agent = get_registry().get_agent(agent_id)
    if not agent:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(agent.to_dict())


# ---- Workers (Phase 2) ----


async def handle_workers(request: Request) -> JSONResponse:
    """GET /api/workers — List workers with hardware info."""
    registry = get_registry()
    agents = registry.get_all_agents()
    workers = [a for a in agents if a.role == "slave"]
    return JSONResponse([a.to_dict() for a in workers])


async def handle_assign_worker(request: Request) -> JSONResponse:
    """POST /api/workers/{id}/assign — Assign role and model to a worker."""
    worker_id = request.path_params["id"]
    body = await request.json()
    role_id = body.get("role_id", "")
    model = body.get("model", "")

    if not role_id:
        return JSONResponse({"error": "role_id required"}, status_code=400)

    registry = get_registry()
    agent = registry.get_agent(worker_id)
    if not agent:
        return JSONResponse({"error": "Worker not found"}, status_code=404)

    # Get role template for system prompt and skills
    role_config = {}
    if _role_manager:
        role = _role_manager.get_role(role_id)
        if role:
            role_config = {
                "system_prompt": role.system_prompt,
                "skills": role.skills,
                "tools": role.tools,
                "autonomy_level": role.autonomy_level,
                "mcp_servers": role.mcp_servers,
            }

    llm_config = {"model": model} if model else {}
    llm_config.update(role_config)

    if registry.assign_role(worker_id, role_id, llm_config):
        log_activity("role_assigned", f"Assigned {role_id} to {agent.name}", agent.name)
        return JSONResponse({"status": "assigned", "role_id": role_id, "model": model})
    return JSONResponse({"error": "Assignment failed"}, status_code=500)


# ---- Roles (Phase 2) ----


async def handle_list_roles(request: Request) -> JSONResponse:
    """GET /api/roles — List all role templates."""
    if not _role_manager:
        return JSONResponse([])
    roles = _role_manager.get_all_roles()
    return JSONResponse([r.to_dict() for r in roles])


# ---- Chat ----


async def handle_chat_send(request: Request) -> JSONResponse:
    """POST /api/chat/send — Send message to orchestrator."""
    body = await request.json()
    message = body.get("message", "")
    project_id = body.get("project_id", "")

    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)

    if not _orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, status_code=503)

    try:
        plan = await _orchestrator.handle_user_request(message, project_id=project_id)
        result = await _orchestrator.execute_plan(plan)
        log_activity("plan_completed", f"Plan {result.plan_id}: {message[:80]}")
        return JSONResponse({
            "plan_id": result.plan_id,
            "status": result.status,
            "steps": [
                {
                    "step": s.step,
                    "description": s.description,
                    "agent": s.agent.name if s.agent else None,
                    "status": s.status,
                    "result": s.result,
                }
                for s in result.steps
            ],
        })
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---- Approvals ----


async def handle_pending_approvals(request: Request) -> JSONResponse:
    """GET /api/approvals/pending — List pending intents."""
    if not _intent_queue:
        return JSONResponse([])
    pending = _intent_queue.get_pending()
    return JSONResponse([i.to_dict() for i in pending])


async def handle_approve_intent(request: Request) -> JSONResponse:
    """POST /api/approvals/{intent_id}/approve — Approve an intent."""
    intent_id = request.path_params["intent_id"]
    if not _intent_queue:
        return JSONResponse({"error": "No intent queue"}, status_code=503)
    if _intent_queue.approve(intent_id, by="human"):
        return JSONResponse({"status": "approved"})
    return JSONResponse({"error": "Intent not found"}, status_code=404)


async def handle_reject_intent(request: Request) -> JSONResponse:
    """POST /api/approvals/{intent_id}/reject — Reject an intent."""
    intent_id = request.path_params["intent_id"]
    body = await request.json()
    reason = body.get("reason", "")
    if not _intent_queue:
        return JSONResponse({"error": "No intent queue"}, status_code=503)
    if _intent_queue.reject(intent_id, by="human", reason=reason):
        return JSONResponse({"status": "rejected"})
    return JSONResponse({"error": "Intent not found"}, status_code=404)


async def handle_approval_history(request: Request) -> JSONResponse:
    """GET /api/approvals/history — Approval history."""
    if not _intent_queue:
        return JSONResponse([])
    return JSONResponse(_intent_queue.get_history())


# ---- Channels (Phase 3) ----


async def handle_list_channels(request: Request) -> JSONResponse:
    """GET /api/channels — List conversation channels."""
    if not _channel_manager:
        return JSONResponse([])
    channels = _channel_manager.get_all_channels()
    return JSONResponse([ch.to_dict() for ch in channels])


async def handle_channel_messages(request: Request) -> JSONResponse:
    """GET /api/channels/{id}/messages — Get channel messages."""
    channel_id = request.path_params["id"]
    if not _channel_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    channel = _channel_manager.get_channel(channel_id)
    if not channel:
        return JSONResponse({"error": "Channel not found"}, status_code=404)
    return JSONResponse(channel.to_dict_full())


# ---- MCP Servers (Phase 4) ----


async def handle_list_mcp_servers(request: Request) -> JSONResponse:
    """GET /api/mcp/servers — List MCP server configs."""
    if not _mcp_registry:
        return JSONResponse([])
    return JSONResponse([s.to_dict() for s in _mcp_registry.get_all()])


async def handle_create_mcp_server(request: Request) -> JSONResponse:
    """POST /api/mcp/servers — Add MCP server config."""
    if not _mcp_registry:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    from mesh.mcp.registry import MCPServerConfig
    config = MCPServerConfig.from_dict(body)
    result = _mcp_registry.add(config)
    return JSONResponse(result.to_dict(), status_code=201)


async def handle_update_mcp_server(request: Request) -> JSONResponse:
    """PUT /api/mcp/servers/{id} — Update MCP server config."""
    server_id = request.path_params["id"]
    if not _mcp_registry:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    result = _mcp_registry.update(server_id, body)
    if not result:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(result.to_dict())


async def handle_delete_mcp_server(request: Request) -> JSONResponse:
    """DELETE /api/mcp/servers/{id} — Delete MCP server config."""
    server_id = request.path_params["id"]
    if not _mcp_registry:
        return JSONResponse({"error": "Not available"}, status_code=503)
    if _mcp_registry.remove(server_id):
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)


async def handle_test_mcp_server(request: Request) -> JSONResponse:
    """POST /api/mcp/servers/{id}/test — Test MCP server connection."""
    server_id = request.path_params["id"]
    if not _mcp_registry:
        return JSONResponse({"error": "Not available"}, status_code=503)
    config = _mcp_registry.get(server_id)
    if not config:
        return JSONResponse({"error": "Not found"}, status_code=404)

    from mesh.mcp.client import MCPToolBridge
    bridge = MCPToolBridge(config)
    success = await bridge.connect()
    tools = bridge.get_tools() if success else []
    await bridge.disconnect()

    return JSONResponse({
        "connected": success,
        "tools_count": len(tools),
        "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
    })


# ---- Memory (Phase 5) ----


async def handle_memory_search(request: Request) -> JSONResponse:
    """GET /api/memory/search?q=... — Search task memory."""
    if not _memory_store:
        return JSONResponse([])
    query = request.query_params.get("q", "")
    if not query:
        return JSONResponse({"error": "q parameter required"}, status_code=400)
    results = await _memory_store.search_similar(query, limit=10)
    return JSONResponse(results)


async def handle_knowledge_list(request: Request) -> JSONResponse:
    """GET /api/knowledge — List knowledge entries."""
    if not _knowledge_base:
        return JSONResponse([])
    tag = request.query_params.get("tag")
    if tag:
        entries = await _knowledge_base.get_by_tag(tag)
    else:
        entries = await _knowledge_base.get_all()
    return JSONResponse(entries)


async def handle_knowledge_create(request: Request) -> JSONResponse:
    """POST /api/knowledge — Create knowledge entry."""
    if not _knowledge_base:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    entry_id = await _knowledge_base.add_entry(
        title=body.get("title", ""),
        content=body.get("content", ""),
        tags=body.get("tags", []),
        source_task_id=body.get("source_task_id", ""),
    )
    return JSONResponse({"id": entry_id}, status_code=201)


async def handle_knowledge_delete(request: Request) -> JSONResponse:
    """DELETE /api/knowledge/{id} — Delete knowledge entry."""
    entry_id = int(request.path_params["id"])
    if not _knowledge_base:
        return JSONResponse({"error": "Not available"}, status_code=503)
    if await _knowledge_base.delete_entry(entry_id):
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)


# ---- Projects (Phase 6) ----


async def handle_list_projects(request: Request) -> JSONResponse:
    """GET /api/projects — List projects."""
    if not _project_manager:
        return JSONResponse([])
    projects = await _project_manager.list_projects()
    return JSONResponse([p.to_dict() for p in projects])


async def handle_create_project(request: Request) -> JSONResponse:
    """POST /api/projects — Create project."""
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    project = await _project_manager.create_project(
        name=body.get("name", ""),
        description=body.get("description", ""),
        config=body.get("config", {}),
    )
    return JSONResponse(project.to_dict(), status_code=201)


async def handle_update_project(request: Request) -> JSONResponse:
    """PUT /api/projects/{id} — Update project."""
    project_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    project = await _project_manager.update_project(project_id, **body)
    if not project:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(project.to_dict())


async def handle_delete_project(request: Request) -> JSONResponse:
    """DELETE /api/projects/{id} — Delete project."""
    project_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    if await _project_manager.delete_project(project_id):
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)


async def handle_list_tasks(request: Request) -> JSONResponse:
    """GET /api/projects/{id}/tasks — List project tasks."""
    project_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse([])
    tasks = await _project_manager.list_tasks(project_id)
    return JSONResponse([t.to_dict() for t in tasks])


async def handle_create_task(request: Request) -> JSONResponse:
    """POST /api/projects/{id}/tasks — Create task."""
    project_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    task = await _project_manager.create_task(
        project_id=project_id,
        title=body.get("title", ""),
        description=body.get("description", ""),
        depends_on=body.get("depends_on", []),
        priority=body.get("priority", 0),
        parent_task_id=body.get("parent_task_id", ""),
    )
    return JSONResponse(task.to_dict(), status_code=201)


async def handle_update_task(request: Request) -> JSONResponse:
    """PUT /api/tasks/{id} — Update task."""
    task_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    task = await _project_manager.update_task(task_id, **body)
    if not task:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(task.to_dict())


async def handle_delete_task(request: Request) -> JSONResponse:
    """DELETE /api/tasks/{id} — Delete task."""
    task_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    if await _project_manager.delete_task(task_id):
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)


# ---- Routines (Phase 6) ----


async def handle_list_routines(request: Request) -> JSONResponse:
    """GET /api/routines — List routines."""
    if not _project_manager:
        return JSONResponse([])
    routines = await _project_manager.list_routines()
    return JSONResponse([r.to_dict() for r in routines])


async def handle_create_routine(request: Request) -> JSONResponse:
    """POST /api/routines — Create routine."""
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    body = await request.json()
    routine = await _project_manager.create_routine(
        name=body.get("name", ""),
        schedule=body.get("schedule", ""),
        task_template=body.get("task_template", {}),
        project_id=body.get("project_id", ""),
        enabled=body.get("enabled", True),
    )
    return JSONResponse(routine.to_dict(), status_code=201)


async def handle_delete_routine(request: Request) -> JSONResponse:
    """DELETE /api/routines/{id} — Delete routine."""
    routine_id = request.path_params["id"]
    if not _project_manager:
        return JSONResponse({"error": "Not available"}, status_code=503)
    if await _project_manager.delete_routine(routine_id):
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Not found"}, status_code=404)


# ---- Activity & Metrics (Phase 7) ----


async def handle_activity(request: Request) -> JSONResponse:
    """GET /api/activity — Recent activity log."""
    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(_activity_log[-limit:])


async def handle_metrics(request: Request) -> JSONResponse:
    """GET /api/metrics — System metrics."""
    registry = get_registry()
    agents = registry.get_all_agents()
    healthy = [a for a in agents if a.healthy]
    workers = [a for a in agents if a.role == "slave"]

    return JSONResponse({
        "agents": {"total": len(agents), "healthy": len(healthy), "workers": len(workers)},
        "plans": {"active": len(_orchestrator.active_plans) if _orchestrator else 0},
        "tunnel": {
            "active": _tunnel_manager.active if _tunnel_manager else False,
            "url": _tunnel_manager.url if _tunnel_manager else "",
            "provider": _tunnel_manager.provider if _tunnel_manager else "",
        },
    })


# ---- Auth (Phase 8) ----


async def handle_token_exchange(request: Request) -> JSONResponse:
    """POST /api/auth/token — Exchange API key for JWT."""
    body = await request.json()
    api_key = body.get("api_key", "")

    if not api_key:
        return JSONResponse({"error": "api_key required"}, status_code=400)

    try:
        from mesh.security.jwt_handler import create_token
        token = create_token(subject="api_user")
        if token:
            return JSONResponse({"token": token, "type": "Bearer"})
        return JSONResponse({"error": "JWT not configured"}, status_code=503)
    except ImportError:
        return JSONResponse({"error": "JWT not available"}, status_code=503)


# ---- Settings ----


async def handle_get_settings(request: Request) -> JSONResponse:
    """GET /api/settings — Get current settings."""
    return JSONResponse({
        "autonomy_level": 1,
        "auto_approve_skills": ["research", "summarize"],
        "require_approval_skills": ["execute_command", "deploy"],
    })


async def handle_update_settings(request: Request) -> JSONResponse:
    """PUT /api/settings — Update settings."""
    body = await request.json()
    # For now, log the update
    logger.info(f"Settings update: {body}")
    return JSONResponse({"status": "updated"})


# ---- Health ----


async def handle_health(request: Request) -> JSONResponse:
    """GET /health — Health check endpoint."""
    return JSONResponse({"status": "ok"})


def create_ui_routes() -> Router:
    """Create Starlette routes for the UI API."""
    routes = [
        # Dashboard
        Route("/", handle_dashboard, methods=["GET"]),
        Route("/health", handle_health, methods=["GET"]),
        # Cluster
        Route("/api/cluster/status", handle_cluster_status, methods=["GET"]),
        Route("/api/agents", handle_agents, methods=["GET"]),
        Route("/api/agents/{agent_id}", handle_agent_detail, methods=["GET"]),
        # Workers (Phase 2)
        Route("/api/workers", handle_workers, methods=["GET"]),
        Route("/api/workers/{id}/assign", handle_assign_worker, methods=["POST"]),
        # Roles (Phase 2)
        Route("/api/roles", handle_list_roles, methods=["GET"]),
        # Chat
        Route("/api/chat/send", handle_chat_send, methods=["POST"]),
        # Approvals
        Route("/api/approvals/pending", handle_pending_approvals, methods=["GET"]),
        Route("/api/approvals/{intent_id}/approve", handle_approve_intent, methods=["POST"]),
        Route("/api/approvals/{intent_id}/reject", handle_reject_intent, methods=["POST"]),
        Route("/api/approvals/history", handle_approval_history, methods=["GET"]),
        # Channels (Phase 3)
        Route("/api/channels", handle_list_channels, methods=["GET"]),
        Route("/api/channels/{id}/messages", handle_channel_messages, methods=["GET"]),
        # MCP (Phase 4)
        Route("/api/mcp/servers", handle_list_mcp_servers, methods=["GET"]),
        Route("/api/mcp/servers", handle_create_mcp_server, methods=["POST"]),
        Route("/api/mcp/servers/{id}", handle_update_mcp_server, methods=["PUT"]),
        Route("/api/mcp/servers/{id}", handle_delete_mcp_server, methods=["DELETE"]),
        Route("/api/mcp/servers/{id}/test", handle_test_mcp_server, methods=["POST"]),
        # Memory (Phase 5)
        Route("/api/memory/search", handle_memory_search, methods=["GET"]),
        Route("/api/knowledge", handle_knowledge_list, methods=["GET"]),
        Route("/api/knowledge", handle_knowledge_create, methods=["POST"]),
        Route("/api/knowledge/{id}", handle_knowledge_delete, methods=["DELETE"]),
        # Projects (Phase 6)
        Route("/api/projects", handle_list_projects, methods=["GET"]),
        Route("/api/projects", handle_create_project, methods=["POST"]),
        Route("/api/projects/{id}", handle_update_project, methods=["PUT"]),
        Route("/api/projects/{id}", handle_delete_project, methods=["DELETE"]),
        Route("/api/projects/{id}/tasks", handle_list_tasks, methods=["GET"]),
        Route("/api/projects/{id}/tasks", handle_create_task, methods=["POST"]),
        Route("/api/tasks/{id}", handle_update_task, methods=["PUT"]),
        Route("/api/tasks/{id}", handle_delete_task, methods=["DELETE"]),
        # Routines (Phase 6)
        Route("/api/routines", handle_list_routines, methods=["GET"]),
        Route("/api/routines", handle_create_routine, methods=["POST"]),
        Route("/api/routines/{id}", handle_delete_routine, methods=["DELETE"]),
        # Activity & Metrics (Phase 7)
        Route("/api/activity", handle_activity, methods=["GET"]),
        Route("/api/metrics", handle_metrics, methods=["GET"]),
        # Auth (Phase 8)
        Route("/api/auth/token", handle_token_exchange, methods=["POST"]),
        # Settings
        Route("/api/settings", handle_get_settings, methods=["GET"]),
        Route("/api/settings", handle_update_settings, methods=["PUT"]),
    ]

    # Mount static files if directory exists
    if STATIC_DIR.exists():
        routes.append(
            Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static")
        )

    return Router(routes=routes)
