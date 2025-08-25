"""
OpenAI Agents SDK + MCP (Playwright) POC

Single-command run: this script starts a Playwright MCP SSE server on a free
port, waits for readiness, connects via the Agents SDK, runs once, and then
shuts the server down.

Run:
  python src/agent_poc_agents_sdk.py
"""

import asyncio
import os
import signal
import socket
import subprocess
import time
import urllib.request
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

console = Console()


async def main() -> None:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY. Set it in .env or environment.")

    try:
        # Imports per OpenAI Agents SDK docs
        from agents import Runner
        from agents.agent import Agent
        from agents.mcp import MCPServerSse
    except Exception as e:
        console.print(Panel(
            "OpenAI Agents SDK is not installed.\n\n"
            "Install from GitHub and retry:\n"
            "  pip install git+https://github.com/openai/openai-agents-python\n\n"
            f"Import error: {e}",
            title="Agents SDK Missing",
            style="yellow",
        ))
        return

    # === MCP CONFIG (easy to tweak) ===
    # Browser engine: "chromium", "firefox", or "webkit" (env PLAYWRIGHT_BROWSER still works)
    MCP_BROWSER = os.getenv("PLAYWRIGHT_BROWSER", "chromium")
    # Headless browser mode
    MCP_HEADLESS = True
    # SSE transport timeout (seconds)
    MCP_SSE_TIMEOUT = 120
    # How long to wait for the MCP server to become ready (seconds)
    MCP_READY_WAIT_SECONDS = 30
    # If you already run MCP elsewhere, set PLAYWRIGHT_MCP_URL env to its SSE URL (e.g., http://localhost:5555/sse)
    MCP_EXTERNAL_SSE_URL = os.getenv("PLAYWRIGHT_MCP_URL") or None

    # === AGENT/TASK INSTRUCTIONS (easy to tweak) ===
    AGENT_INSTRUCTIONS = (
        "Open https://tenderradar.com. Return only the page title and the main heading (h1). "
        "Output exactly two lines: 'Title: <page title>' and 'H1: <main heading>'. "
        "Do not take screenshots and do not install/update browsers. Navigate with waitUntil='networkidle' and timeout=45000."
    )

    # Always spawn a local Playwright MCP server by default (single-run simplicity)
    server_proc: Optional[subprocess.Popen] = None

    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _wait_http_ok(url: str, deadline: float) -> bool:
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    # For SSE endpoints, just getting a response indicates readiness
                    if resp.status in (200, 204):
                        return True
                    # Some servers keep SSE open; status 200 is fine
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    try:
        # Use an external SSE URL if provided, otherwise spawn via npx on a free port
        if MCP_EXTERNAL_SSE_URL:
            url = MCP_EXTERNAL_SSE_URL
            console.print(f"Using external Playwright MCP SSE server at {url}")
        else:
            port = _find_free_port()
            url = f"http://127.0.0.1:{port}/sse"
            cmd = [
                "npx",
                "-y",
                "@playwright/mcp@latest",
                f"--browser={MCP_BROWSER}",
                f"--port={port}",
            ]
            if MCP_HEADLESS:
                cmd.append("--headless")
            console.print(f"Starting Playwright MCP server: {' '.join(cmd)}")
            server_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Wait for readiness
            if not _wait_http_ok(url, time.time() + MCP_READY_WAIT_SECONDS):
                raise RuntimeError(f"Playwright MCP server did not become ready at {url} within timeout.")

        server = MCPServerSse({"url": url, "timeout": MCP_SSE_TIMEOUT})

        async with server:
            console.print("Connected to Playwright MCP server.")

            # Define the agent with MCP server attached
            agent = Agent(
                name="Playwright Web Tester",
                instructions=AGENT_INSTRUCTIONS,
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                mcp_servers=[server],
            )

            # Single run (fail-fast)
            result = await Runner.run(agent, input="Do the task described in your instructions.")

            # Print final output and any intermediate events if available
            final_output: Optional[str] = getattr(result, "final_output", None)
            if final_output:
                console.print(Panel(final_output, title="Agent Final Output"))
            else:
                console.print(Panel("No final output returned.", title="Agent Result", style="yellow"))
    finally:
        console.print("Disconnected from Playwright MCP server.")
        if server_proc and server_proc.poll() is None:
            try:
                server_proc.send_signal(signal.SIGINT)
                try:
                    server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server_proc.terminate()
                    try:
                        server_proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        server_proc.kill()
            except Exception:
                try:
                    server_proc.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("Interrupted by user.")
    except Exception as e:
        console.print(Panel(str(e), title="Fatal Error", style="red"))
