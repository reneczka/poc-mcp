"""
OpenAI Agents SDK + MCP (Playwright + Airtable) POC

Single-command run: this script starts a Playwright MCP SSE server on a free
port and an Airtable MCP (stdio) server, connects via the Agents SDK, runs once,
and then shuts the servers down.

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
        from agents import Runner, ItemHelpers
        from agents.agent import Agent
        from agents.mcp import MCPServerSse
        try:
            # Stdio transport for Node-based MCP servers (e.g., Airtable)
            from agents.mcp import MCPServerStdio  # type: ignore
        except Exception as _:
            MCPServerStdio = None  # will validate below
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

    # Airtable MCP (Node stdio) config
    AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
    AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
    AIRTABLE_PACKAGE = os.getenv("AIRTABLE_MCP_PACKAGE", "@felores/airtable-mcp-server")
    AIRTABLE_USE_NPX = os.getenv("AIRTABLE_USE_NPX", "1") in ("1", "true", "True")

    # === AGENT/TASK INSTRUCTIONS (easy to tweak) ===
    # AGENT_INSTRUCTIONS = (
    #     "Open https://tenderradar.com. Return only the page title and the main heading (h1). "
    #     "Output exactly two lines: 'Title: <page title>' and 'H1: <main heading>'. "
    #     "Do not take screenshots and do not install/update browsers. Navigate with waitUntil='networkidle' and timeout=45000."
    # )
    if AIRTABLE_BASE_ID:
        AGENT_INSTRUCTIONS = (
            "You are connected to an Airtable MCP server. Create ONE new record in the 'oferty' table "
            "in base ID '" + AIRTABLE_BASE_ID + "'. Use the exact JSON shape below for the create_record tool.\n\n"
            "Call the MCP tool create_record with EXACTLY this JSON argument shape (note the 'fields' key):\n"
            "{\n"
            "  \"baseId\": \"" + AIRTABLE_BASE_ID + "\",\n"
            "  \"tableId\": \"tblVIbY84NJvk8LHI\",\n"
            "  \"fields\": {\n"
            "    \"Source\": \"Example source\",\n"
            "    \"Link\": \"https://example.com/job\",\n"
            "    \"Company\": \"Example Co\",\n"
            "    \"Position\": \"Engineer\",\n"
            "    \"CV sent\": false,\n"
            "    \"Salary\": \"100k-120k\",\n"
            "    \"Location\": \"Remote\",\n"
            "    \"Notes\": \"Added by agent\",\n"
            "    \"Date applied\": \"2025-08-27\",\n"
            "    \"Requirements\": \"Python, Playwright\",\n"
            "    \"About company\": \"Great team\",\n"
            "    \"Local/Rem/Hyb\": \"Remote\"\n"
            "  }\n"
            "}\n\n"
            "Important:\n"
            "- Include a top-level 'fields' key with the field map.\n"
            "- Use field names exactly: Source, Link, Company, Position, CV sent, Salary, Location, Notes, Date applied, Requirements, About company, Local/Rem/Hyb.\n"
            "- 'CV sent' is boolean. Others are strings.\n"
            "- Return the created record id and fields."
        )
    else:
        AGENT_INSTRUCTIONS = (
            "You are connected to an Airtable MCP server. Your task is to create ONE new record in the 'oferty' table "
            "in the base named 'WORK BITCH'. First, list bases to find the correct baseId, then proceed.\n\n"
            "1) Find baseId by name 'WORK BITCH'.\n"
            "2) Identify tableId for 'oferty' (likely tblVIbY84NJvk8LHI).\n"
            "3) Call create_record with JSON containing top-level 'fields': { ... } using exact field names."
        )
    
    # Always spawn a local Playwright MCP server by default (single-run simplicity)
    server_proc: Optional[subprocess.Popen] = None
    # Airtable server proc is managed by the SDK (stdio), so no manual Popen needed

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

        # Construct Playwright SSE MCP client
        playwright_server = MCPServerSse({"url": url, "timeout": MCP_SSE_TIMEOUT})

        # Construct Airtable stdio MCP client (spawn via npx)
        airtable_server = None
        if AIRTABLE_API_KEY:
            if MCPServerStdio is None:
                raise RuntimeError(
                    "Agents SDK missing MCPServerStdio. Update SDK: pip install -U git+https://github.com/openai/openai-agents-python"
                )
            airtable_cmd = "npx" if AIRTABLE_USE_NPX else "node"
            airtable_args = ["-y", AIRTABLE_PACKAGE] if AIRTABLE_USE_NPX else [AIRTABLE_PACKAGE]
            airtable_env = {**os.environ, "AIRTABLE_API_KEY": AIRTABLE_API_KEY}
            console.print(
                f"Starting Airtable MCP server via stdio: {airtable_cmd} {' '.join(airtable_args)}"
            )
            airtable_server = MCPServerStdio({
                "command": airtable_cmd,
                "args": airtable_args,
                "env": airtable_env,
                # Optional: working directory can be set via "cwd"
            })
        else:
            console.print(Panel(
                "Skipping Airtable MCP (no AIRTABLE_API_KEY set).\n"
                "Set AIRTABLE_API_KEY with Airtable Personal Access Token (scopes: schema.bases:read/write, data.records:read/write).",
                title="Airtable MCP Skipped",
                style="yellow",
            ))

        # Open both MCP connections
        cm_stack = []
        if airtable_server:
            cm_stack.append(airtable_server)
        cm_stack.append(playwright_server)

        # Nest async context managers dynamically (simple two-server case)
        if airtable_server:
            async with airtable_server:
                console.print("Connected to Airtable MCP server.")
                async with playwright_server:
                    console.print("Connected to Playwright MCP server.")

                    # Define the agent with both MCP servers attached
                    agent = Agent(
                        name="Web + Airtable Agent",
                        instructions=AGENT_INSTRUCTIONS,
                        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        mcp_servers=[airtable_server, playwright_server],
                    )

                    # Streamed run: print high-level agent reasoning/steps as events
                    streamed = Runner.run_streamed(
                        agent,
                        input="Do the task described in your instructions.",
                    )
                    async for event in streamed.stream_events():
                        if event.type == "raw_response_event":
                            continue
                        elif event.type == "agent_updated_stream_event":
                            console.print(f"[dim]Agent updated: {event.new_agent.name}[/]")
                        elif event.type == "run_item_stream_event":
                            if event.item.type == "tool_call_item":
                                tool = getattr(event.item, "tool_name", None) or "tool"
                                console.print(f"[bold cyan]→ Tool called[/]: {tool}")
                            elif event.item.type == "tool_call_output_item":
                                output = getattr(event.item, "output", "")
                                console.print(Panel(str(output), title="Tool output", style="cyan"))
                            elif event.item.type == "message_output_item":
                                text = ItemHelpers.text_message_output(event.item)
                                console.print(Panel(text, title="Agent message", style="green"))
                            else:
                                pass
                    # After streaming completes, capture final result
                    result = streamed

                    # Print final output and any intermediate events if available
                    final_output: Optional[str] = getattr(result, "final_output", None)
                    if final_output:
                        console.print(Panel(final_output, title="Agent Final Output"))
                    else:
                        console.print(Panel("No final output returned.", title="Agent Result", style="yellow"))
        else:
            # Fallback: only Playwright
            async with playwright_server:
                console.print("Connected to Playwright MCP server.")

                # Define the agent with MCP server attached
                agent = Agent(
                    name="Playwright Web Tester",
                    instructions=AGENT_INSTRUCTIONS,
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    mcp_servers=[playwright_server],
                )

                # Streamed run: print high-level agent reasoning/steps as events
                streamed = Runner.run_streamed(
                    agent,
                    input="Do the task described in your instructions.",
                )
                async for event in streamed.stream_events():
                    if event.type == "raw_response_event":
                        continue
                    elif event.type == "agent_updated_stream_event":
                        console.print(f"[dim]Agent updated: {event.new_agent.name}[/]")
                    elif event.type == "run_item_stream_event":
                        if event.item.type == "tool_call_item":
                            tool = getattr(event.item, "tool_name", None) or "tool"
                            console.print(f"[bold cyan]→ Tool called[/]: {tool}")
                        elif event.item.type == "tool_call_output_item":
                            output = getattr(event.item, "output", "")
                            console.print(Panel(str(output), title="Tool output", style="cyan"))
                        elif event.item.type == "message_output_item":
                            text = ItemHelpers.text_message_output(event.item)
                            console.print(Panel(text, title="Agent message", style="green"))
                        else:
                            pass
                # After streaming completes, capture final result
                result = streamed


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
                    server_proc.wait(timeout=60)
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
