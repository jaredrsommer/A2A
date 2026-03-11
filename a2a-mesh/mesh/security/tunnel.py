"""Tunnel manager — auto-detect and start cloudflared or ngrok."""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages WAN tunnels via cloudflared or ngrok."""

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._url: str = ""
        self._provider: str = ""

    @property
    def url(self) -> str:
        return self._url

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self, port: int) -> str | None:
        """Start a tunnel to the given local port. Returns public URL."""
        # Try cloudflared first
        if shutil.which("cloudflared"):
            url = await self._start_cloudflared(port)
            if url:
                return url

        # Try ngrok
        if shutil.which("ngrok"):
            url = await self._start_ngrok(port)
            if url:
                return url

        logger.warning("No tunnel provider found (install cloudflared or ngrok)")
        return None

    async def _start_cloudflared(self, port: int) -> str | None:
        """Start cloudflared quick tunnel."""
        try:
            self._process = await asyncio.create_subprocess_exec(
                "cloudflared", "tunnel", "--url", f"http://localhost:{port}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._provider = "cloudflared"

            # Read stderr for the URL (cloudflared outputs it there)
            for _ in range(30):
                if self._process.stderr:
                    try:
                        line = await asyncio.wait_for(
                            self._process.stderr.readline(), timeout=2
                        )
                        text = line.decode()
                        if "https://" in text and "trycloudflare.com" in text:
                            for word in text.split():
                                if word.startswith("https://") and "trycloudflare.com" in word:
                                    self._url = word.strip()
                                    logger.info(f"Cloudflared tunnel: {self._url}")
                                    return self._url
                    except asyncio.TimeoutError:
                        continue

            logger.warning("Could not get cloudflared URL")
            return None

        except Exception as e:
            logger.error(f"cloudflared failed: {e}")
            return None

    async def _start_ngrok(self, port: int) -> str | None:
        """Start ngrok tunnel."""
        try:
            self._process = await asyncio.create_subprocess_exec(
                "ngrok", "http", str(port), "--log=stdout",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._provider = "ngrok"

            # Give ngrok time to start
            await asyncio.sleep(2)

            # Get URL from ngrok API
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:4040/api/tunnels")
                data = resp.json()
                tunnels = data.get("tunnels", [])
                for t in tunnels:
                    if t.get("proto") == "https":
                        self._url = t["public_url"]
                        logger.info(f"ngrok tunnel: {self._url}")
                        return self._url

            return None

        except Exception as e:
            logger.error(f"ngrok failed: {e}")
            return None

    async def stop(self) -> None:
        """Stop the tunnel."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                if self._process:
                    self._process.kill()
            self._process = None
            self._url = ""
            logger.info("Tunnel stopped")
