"""
MCP Server Management Module

Handles the lifecycle of MCP servers (Playwright and Airtable):
- Starting and stopping servers
- Managing server processes
- Handling server connections
"""

import asyncio
import os
import signal
import subprocess
import time
from typing import Optional
from contextlib import asynccontextmanager

from rich.console import Console
from rich.panel import Panel

from mcp_utils import find_free_port, wait_http_ok
from config import (
    MCP_DEFAULT_BROWSER,
    MCP_DEFAULT_HEADLESS,
    MCP_DEFAULT_SSE_TIMEOUT,
    MCP_DEFAULT_READY_WAIT_SECONDS,
    MCP_DEFAULT_TOOL_TIMEOUT_SECONDS,
    MCP_PLAYWRIGHT_TIMEOUT_SECONDS,
    DEFAULT_AIRTABLE_MCP_PACKAGE,
)

console = Console()


class PlaywrightServerManager:
    """Manages Playwright MCP server lifecycle"""
    
    def __init__(self, external_url: Optional[str] = None):
        self.external_url = external_url
        self.server_process: Optional[subprocess.Popen] = None
        self.server_url: Optional[str] = None
    
    async def start_server(self) -> str:
        """Start Playwright MCP server and return SSE URL"""
        if self.external_url:
            self.server_url = self.external_url
            return self.server_url
        
        port = find_free_port()
        self.server_url = f"http://127.0.0.1:{port}/sse"
        
        cmd = [
            "npx", "-y", "@playwright/mcp@latest",
            f"--browser={MCP_DEFAULT_BROWSER}",
            f"--port={port}",
            f"--timeout-action={MCP_PLAYWRIGHT_TIMEOUT_SECONDS * 1000}",
            f"--timeout-navigation={MCP_PLAYWRIGHT_TIMEOUT_SECONDS * 1000}",
        ]
        
        if MCP_DEFAULT_HEADLESS:
            cmd.append("--headless")
        
        self.server_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        # Give the process a moment to start
        await asyncio.sleep(2)
        
        # Check if process is still running
        if self.server_process.poll() is not None:
            stdout, stderr = self.server_process.communicate()
            raise RuntimeError(f"Playwright MCP server process exited with code {self.server_process.returncode}. STDERR: {stderr.decode()}")
        
        if not wait_http_ok(self.server_url, time.time() + MCP_DEFAULT_READY_WAIT_SECONDS):
            raise RuntimeError(f"Playwright MCP server did not become ready at {self.server_url}")
        
        return self.server_url
    
    
    def stop_server(self):
        """Stop the Playwright MCP server process"""
        if not self.server_process or self.server_process.poll() is not None:
            return
        
        try:
            self.server_process.send_signal(signal.SIGINT)
            try:
                self.server_process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.server_process.kill()
        except Exception:
            try:
                self.server_process.kill()
            except Exception:
                pass


class AirtableServerConfig:
    """Configuration for Airtable MCP server"""
    
    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID") 
        self.table_id = os.getenv("AIRTABLE_TABLE_ID")
        self.package = DEFAULT_AIRTABLE_MCP_PACKAGE
        self.timeout = MCP_DEFAULT_TOOL_TIMEOUT_SECONDS
    
    def is_complete(self) -> bool:
        """Check if all required Airtable configuration is present"""
        return all([self.api_key, self.base_id, self.table_id])
    
    def setup_environment(self):
        """Set environment variables for the subprocess"""
        if self.api_key:
            os.environ["AIRTABLE_API_KEY"] = self.api_key
        if self.base_id:
            os.environ["AIRTABLE_BASE_ID"] = self.base_id
        if self.table_id:
            os.environ["AIRTABLE_TABLE_ID"] = self.table_id


@asynccontextmanager
async def create_mcp_servers(airtable_config: AirtableServerConfig):
    """
    Context manager that creates and manages both MCP servers
    
    Returns:
        Tuple of (playwright_server, airtable_server)
        airtable_server may be None if not configured
    """
    # Import here to avoid circular imports and handle missing SDK gracefully
    try:
        from agents.mcp import MCPServerSse, MCPServerStdio
    except ImportError as e:
        raise RuntimeError(f"OpenAI Agents SDK not available: {e}")
    
    playwright_manager = PlaywrightServerManager()
    playwright_server = None
    airtable_server = None
    
    try:
        # Start Playwright server
        playwright_url = await playwright_manager.start_server()
        playwright_server = MCPServerSse({
            "url": playwright_url, 
            "timeout": MCP_DEFAULT_SSE_TIMEOUT
        })
        
        # Setup Airtable server if configured
        if airtable_config.is_complete():
            airtable_config.setup_environment()
            
            airtable_server = MCPServerStdio({
                "command": "npx",
                "args": ["-y", airtable_config.package],
                "env": os.environ.copy(),
                "timeout": airtable_config.timeout,
            })
        
        # Open connections
        async with playwright_server:
            if airtable_server:
                async with airtable_server:
                    yield playwright_server, airtable_server
            else:
                yield playwright_server, None
    
    finally:
        playwright_manager.stop_server()
