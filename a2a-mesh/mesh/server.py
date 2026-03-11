"""Server factory — creates the ASGI app for master or slave nodes."""

from __future__ import annotations

import logging

from starlette.applications import Starlette
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
)

from mesh.agent.config import AgentConfig
from mesh.agent.base import LLMClient
from mesh.agent.executor import MeshAgentExecutor
from mesh.agent.tools import create_default_tools

logger = logging.getLogger(__name__)


def _build_agent_card(config: AgentConfig) -> AgentCard:
    """Build an A2A AgentCard from config."""
    skills = [
        AgentSkill(
            id=s.id,
            name=s.name,
            description=s.description,
            tags=s.tags,
            examples=s.examples or [],
            inputModes=s.input_modes,
            outputModes=s.output_modes,
        )
        for s in config.skills
    ]

    return AgentCard(
        name=config.node.name,
        description=config.system_prompt[:200],
        url=f"http://{config.node.host}:{config.node.port}",
        version=config.node.name,
        capabilities=AgentCapabilities(streaming=True),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=skills,
    )


def _build_executor(config: AgentConfig, **kwargs) -> MeshAgentExecutor:
    """Build the agent executor from config."""
    llm = LLMClient(config.llm)
    tools = create_default_tools() if config.llm.supports_tools else None
    return MeshAgentExecutor(
        llm=llm,
        system_prompt=config.system_prompt,
        tools=tools,
        **kwargs,
    )


async def create_slave_server(config: AgentConfig) -> Starlette:
    """Create a slave node ASGI application.

    Runs:
    - A2A agent server (handles tasks from master or other agents)
    - /comms/receive endpoint for lateral communication
    """
    agent_card = _build_agent_card(config)
    executor = _build_executor(config)

    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    base_app = a2a_app.build()

    # Add comms endpoint for lateral messaging
    async def handle_comms_receive(request):
        body = await request.json()
        channel_id = body.get("channel_id", "")
        content = body.get("content", "")
        from_agent = body.get("from_agent_name", body.get("from_agent", ""))
        message_type = body.get("message_type", "text")

        executor.receive_lateral_message(
            context_id=channel_id,
            from_agent=from_agent,
            content=content,
            message_type=message_type,
        )
        return JSONResponse({"status": "received"})

    base_app.routes.append(Route("/comms/receive", handle_comms_receive, methods=["POST"]))

    logger.info(f"Slave agent '{config.node.name}' ready on port {config.node.port}")
    return base_app


async def create_master_server(config: AgentConfig) -> Starlette:
    """Create a master node ASGI application.

    Runs:
    - A2A agent server (master can also be an agent)
    - Agent registry API (/registry/)
    - File share API (/files/) if enabled
    - UI API (/api/) and dashboard (/) if enabled
    - WebSocket (/ws) for real-time events
    - Auth middleware if API keys configured
    - Rate limiting and CORS
    """
    # Build the A2A agent part
    agent_card = _build_agent_card(config)

    # Initialize memory store (Phase 5)
    memory_store = None
    context_builder = None
    knowledge_base = None
    try:
        from mesh.memory.store import MemoryStore
        from mesh.memory.context import ContextBuilder
        from mesh.memory.knowledge import KnowledgeBase

        memory_store = MemoryStore()
        await memory_store.initialize()
        context_builder = ContextBuilder(memory_store)

        import aiosqlite
        db = await aiosqlite.connect("data/memory.db")
        knowledge_base = KnowledgeBase(db)
        await knowledge_base.initialize()
        logger.info("Memory store and knowledge base initialized")
    except Exception as e:
        logger.warning(f"Memory initialization failed: {e}")

    executor = _build_executor(
        config,
        memory_store=memory_store,
        context_builder=context_builder,
    )

    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    base_app = a2a_app.build()

    # Add registry routes
    from mesh.network.registry import create_registry_routes, get_registry

    registry = create_registry_routes()
    for route in registry.routes:
        base_app.routes.append(route)

    # Initialize role manager (Phase 2)
    role_manager = None
    try:
        from mesh.roles import RoleManager
        role_manager = RoleManager()
        logger.info(f"Role manager initialized with {len(role_manager.get_all_roles())} roles")
    except Exception as e:
        logger.warning(f"Role manager init failed: {e}")

    # Initialize channel manager (Phase 3)
    channel_manager = None
    try:
        from mesh.comms.channel import ChannelManager
        from mesh.ui.ws import event_bus
        channel_manager = ChannelManager()
        channel_manager.set_event_bus(event_bus)
        logger.info("Channel manager initialized")
    except Exception as e:
        logger.warning(f"Channel manager init failed: {e}")

    # Initialize MCP registry (Phase 4)
    mcp_registry = None
    try:
        from mesh.mcp.registry import MCPRegistry
        mcp_registry = MCPRegistry()
        logger.info(f"MCP registry initialized with {len(mcp_registry.get_all())} servers")
    except Exception as e:
        logger.warning(f"MCP registry init failed: {e}")

    # Initialize project manager (Phase 6)
    project_manager = None
    scheduler = None
    try:
        import aiosqlite
        from mesh.projects.manager import ProjectManager
        from mesh.projects.scheduler import TaskScheduler

        db = await aiosqlite.connect("data/memory.db")
        project_manager = ProjectManager(db)
        await project_manager.initialize()
        scheduler = TaskScheduler(project_manager)
        await scheduler.start()
        logger.info("Project manager and scheduler initialized")
    except Exception as e:
        logger.warning(f"Project manager init failed: {e}")

    # Initialize tunnel manager (Phase 8)
    tunnel_manager = None
    try:
        from mesh.security.tunnel import TunnelManager
        tunnel_manager = TunnelManager()
    except Exception as e:
        logger.warning(f"Tunnel manager init failed: {e}")

    # Set up orchestrator with all dependencies
    from mesh.orchestrator.master import MasterOrchestrator
    from mesh.orchestrator.intent import ApprovalPolicy

    llm = LLMClient(config.llm)
    orchestrator = MasterOrchestrator(
        llm=llm,
        registry=get_registry(),
        policy=ApprovalPolicy(),
        memory_store=memory_store,
        channel_manager=channel_manager,
        project_manager=project_manager,
    )

    # Set up UI API with all dependencies
    from mesh.ui.api import (
        create_ui_routes, set_orchestrator, set_role_manager,
        set_channel_manager, set_mcp_registry, set_memory_store,
        set_knowledge_base, set_project_manager, set_tunnel_manager,
    )

    set_orchestrator(orchestrator)
    set_role_manager(role_manager)
    set_channel_manager(channel_manager)
    set_mcp_registry(mcp_registry)
    set_memory_store(memory_store)
    set_knowledge_base(knowledge_base)
    set_project_manager(project_manager)
    set_tunnel_manager(tunnel_manager)

    ui_routes = create_ui_routes()
    for route in ui_routes.routes:
        base_app.routes.append(route)

    # Add WebSocket route
    from mesh.ui.ws import websocket_handler
    base_app.routes.append(WebSocketRoute("/ws", websocket_handler))

    # Add comms endpoint on master too
    async def handle_comms_receive(request):
        body = await request.json()
        return JSONResponse({"status": "received"})

    base_app.routes.append(Route("/comms/receive", handle_comms_receive, methods=["POST"]))

    # Apply auth middleware (Phase 1 + Phase 8)
    api_keys = config.auth.api_keys if hasattr(config, 'auth') else []
    if api_keys:
        from mesh.auth import AuthMiddleware
        base_app = AuthMiddleware(base_app, api_keys=api_keys)
        logger.info(f"Auth middleware enabled ({len(api_keys)} API keys)")

    # Apply security middleware (Phase 8)
    try:
        from mesh.security.middleware import RateLimitMiddleware, CORSMiddleware, RequestLoggingMiddleware, RateLimitConfig

        rate_limit = config.security.rate_limit if hasattr(config, 'security') else 60
        cors_origins = config.security.cors_origins if hasattr(config, 'security') else ["*"]

        base_app = CORSMiddleware(base_app, origins=cors_origins)
        base_app = RateLimitMiddleware(base_app, config=RateLimitConfig(requests_per_minute=rate_limit))
        base_app = RequestLoggingMiddleware(base_app)
    except Exception as e:
        logger.warning(f"Security middleware init failed: {e}")

    # Configure JWT if secret provided (Phase 8)
    if hasattr(config, 'security') and config.security.jwt_secret:
        try:
            from mesh.security.jwt_handler import configure
            configure(config.security.jwt_secret)
            logger.info("JWT authentication configured")
        except Exception as e:
            logger.warning(f"JWT config failed: {e}")

    # Start tunnel if configured (Phase 8)
    if hasattr(config, 'security') and config.security.tunnel and tunnel_manager:
        import asyncio
        asyncio.create_task(_start_tunnel(tunnel_manager, config.node.port))

    # Start health monitor
    await get_registry().start_health_monitor()

    logger.info(
        f"Master node '{config.node.name}' ready on port {config.node.port}"
    )
    return base_app


async def _start_tunnel(tunnel_manager, port: int):
    """Start tunnel in background."""
    url = await tunnel_manager.start(port)
    if url:
        logger.info(f"WAN tunnel active: {url}")
