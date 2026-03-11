"""CLI entry point for A2A Mesh."""

from __future__ import annotations

import asyncio
import logging
import sys
import time

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool):
    """A2A Mesh — Autonomous AI Workforce Platform."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
@click.option("--config", "-c", required=True, help="Path to YAML config file")
def start(config: str):
    """Start a mesh node (master or slave agent)."""
    from mesh.agent.config import AgentConfig

    cfg = AgentConfig.from_yaml(config)
    console.print(f"[bold green]Starting[/] {cfg.node.name} ({cfg.node.role})")
    console.print(f"  LLM: {cfg.llm.base_url} / {cfg.llm.model}")
    console.print(f"  Port: {cfg.node.port}")

    if cfg.node.role == "master":
        asyncio.run(_start_master(cfg))
    else:
        asyncio.run(_start_slave(cfg))


async def _start_master(config):
    """Start master node with orchestrator, registry, file share, and UI."""
    from mesh.server import create_master_server

    app = await create_master_server(config)

    import uvicorn

    uv_config = uvicorn.Config(
        app,
        host=config.node.host,
        port=config.node.port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    await server.serve()


async def _start_slave(config):
    """Start slave node with agent server."""
    from mesh.server import create_slave_server

    app = await create_slave_server(config)

    import uvicorn

    uv_config = uvicorn.Config(
        app,
        host=config.node.host,
        port=config.node.port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    await server.serve()


@main.command("join")
@click.option("--key", "-k", default="", help="API key for master authentication")
@click.option("--master", "-m", default=None, help="Master URL (auto-discover if not set)")
@click.option("--name", "-n", default=None, help="Worker name")
@click.option("--port", "-p", default=10001, type=int, help="Port to serve on")
def join(key: str, master: str | None, name: str | None, port: int):
    """Join the mesh as a worker. Zero-config: discovers master, reports hardware, waits for role assignment."""
    asyncio.run(_join_mesh(key, master, name, port))


async def _join_mesh(api_key: str, master_url: str | None, name: str | None, port: int):
    import httpx
    import platform
    from mesh.hardware import detect_hardware

    # Detect hardware
    console.print("[cyan]Detecting hardware...[/]")
    hw = detect_hardware()
    worker_name = name or f"worker-{hw.hostname}"

    console.print(f"  Hostname: {hw.hostname}")
    console.print(f"  OS: {hw.os}")
    console.print(f"  CPU: {hw.cpu_cores} cores")
    console.print(f"  RAM: {hw.ram_total_gb:.1f} GB total, {hw.ram_available_gb:.1f} GB available")
    if hw.gpus:
        for gpu in hw.gpus:
            console.print(f"  GPU: {gpu.name} ({gpu.vram_mb} MB VRAM)")
    else:
        console.print("  GPU: None detected")

    # Discover master
    if not master_url:
        console.print("[yellow]Discovering master via mDNS...[/]")
        from mesh.network.discovery import MeshDiscovery

        discovery = MeshDiscovery()
        master_info = await discovery.discover_master(timeout=10)
        if not master_info:
            console.print("[red]No master found. Use --master <url> to specify.[/]")
            return
        master_url = f"http://{master_info.host}:{master_info.port}"
        await discovery.stop()

    console.print(f"[green]Master:[/] {master_url}")

    # Register with master
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    registration = {
        "name": worker_name,
        "host": platform.node(),
        "port": port,
        "role": "slave",
        "hardware": hw.to_dict(),
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{master_url}/registry/agents",
                json=registration,
                headers=headers,
            )
            if resp.status_code == 401:
                console.print("[red]Authentication failed. Check your API key.[/]")
                return
            data = resp.json()
            agent_id = data.get("agent_id", "")
            console.print(f"[green]Registered as[/] {worker_name} [dim]({agent_id})[/]")
        except Exception as e:
            console.print(f"[red]Registration failed: {e}[/]")
            return

    # Poll for role assignment
    console.print("[yellow]Waiting for role assignment from dashboard...[/]")
    config_version = 0

    while True:
        try:
            async with httpx.AsyncClient() as client:
                # Heartbeat
                await client.post(
                    f"{master_url}/registry/agents/{agent_id}/heartbeat",
                    headers=headers,
                )

                # Check for config
                resp = await client.get(
                    f"{master_url}/registry/agents/{agent_id}/config",
                    headers=headers,
                )
                config_data = resp.json()
                new_version = config_data.get("config_version", 0)

                if new_version > config_version:
                    config_version = new_version
                    role_id = config_data.get("role_id", "")
                    llm_config = config_data.get("llm_config", {})

                    console.print(f"[bold green]Role assigned:[/] {role_id}")

                    # Build and start agent with pushed config
                    from mesh.agent.config import AgentConfig, LLMConfig, NodeConfig

                    system_prompt = llm_config.pop("system_prompt", "You are a helpful AI agent.")
                    skills = llm_config.pop("skills", [])
                    model = llm_config.pop("model", "llama3")

                    cfg = AgentConfig(
                        node=NodeConfig(role="slave", name=worker_name, port=port),
                        llm=LLMConfig(model=model),
                        system_prompt=system_prompt,
                    )

                    # Pull model if needed
                    try:
                        from mesh.runtime import OllamaAdapter
                        ollama = OllamaAdapter()
                        if await ollama.is_available():
                            if not await ollama.has_model(model):
                                console.print(f"[yellow]Pulling model {model}...[/]")
                                await ollama.pull_model(model)
                    except Exception as e:
                        console.print(f"[yellow]Model pull skipped: {e}[/]")

                    # Start serving
                    console.print(f"[bold green]Starting agent on port {port}...[/]")
                    await _start_slave(cfg)
                    return

        except Exception as e:
            pass  # Silently retry

        await asyncio.sleep(5)


@main.command("agents")
@click.option("--master", "-m", default=None, help="Master URL (auto-discover if not set)")
def list_agents(master: str | None):
    """List all agents in the mesh."""
    asyncio.run(_list_agents(master))


async def _list_agents(master_url: str | None):
    if not master_url:
        console.print("[yellow]Auto-discovering master...[/]")
        from mesh.network.discovery import MeshDiscovery

        discovery = MeshDiscovery()
        master_info = await discovery.discover_master(timeout=5)
        if not master_info:
            console.print("[red]No master node found on network.[/]")
            return
        master_url = f"http://{master_info.host}:{master_info.port}"
        await discovery.stop()

    import httpx

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{master_url}/registry/agents")
            agents = resp.json()
        except Exception as e:
            console.print(f"[red]Failed to reach master: {e}[/]")
            return

    table = Table(title="Mesh Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="green")
    table.add_column("Assigned Role", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("LLM", style="yellow")
    table.add_column("Hardware")
    table.add_column("URL")

    for agent in agents:
        status = "[green]● Online[/]" if agent.get("healthy") else "[red]● Offline[/]"
        hw = agent.get("hardware") or {}
        hw_str = ""
        if hw:
            gpus = hw.get("gpus", [])
            gpu_str = f", GPU: {gpus[0]['name']} ({gpus[0]['vram_mb']}MB)" if gpus else ""
            hw_str = f"{hw.get('cpu_cores', '?')} CPU, {hw.get('ram_total_gb', 0):.0f}GB RAM{gpu_str}"

        table.add_row(
            agent.get("name", "?"),
            agent.get("role", "?"),
            agent.get("assigned_role", "-"),
            status,
            agent.get("llm_model", "?"),
            hw_str,
            agent.get("url", "?"),
        )

    console.print(table)


@main.command()
@click.argument("agent_name")
@click.argument("message")
@click.option("--master", "-m", default=None, help="Master URL")
def send(agent_name: str, message: str, master: str | None):
    """Send a message to an agent."""
    asyncio.run(_send_message(agent_name, message, master))


async def _send_message(agent_name: str, message: str, master_url: str | None):
    console.print(f"[bold]Sending to {agent_name}:[/] {message}")
    # TODO: Implement via A2A client
    console.print("[yellow]Direct message sending not yet implemented. Use the web UI.[/]")


@main.command()
def status():
    """Show mesh cluster status."""
    asyncio.run(_show_status())


async def _show_status():
    console.print("[yellow]Status check not yet implemented. Use: mesh agents --master <url>[/]")


@main.command("tunnel")
@click.option("--port", "-p", default=10000, type=int, help="Local port to tunnel")
def tunnel(port: int):
    """Start a WAN tunnel to expose the mesh externally."""
    asyncio.run(_start_tunnel_cmd(port))


async def _start_tunnel_cmd(port: int):
    from mesh.security.tunnel import TunnelManager

    manager = TunnelManager()
    console.print(f"[cyan]Starting tunnel for port {port}...[/]")
    url = await manager.start(port)
    if url:
        console.print(f"[bold green]Tunnel active:[/] {url}")
        console.print("[dim]Press Ctrl+C to stop[/]")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await manager.stop()
            console.print("[yellow]Tunnel stopped.[/]")
    else:
        console.print("[red]Failed to start tunnel. Install cloudflared or ngrok.[/]")


if __name__ == "__main__":
    main()
