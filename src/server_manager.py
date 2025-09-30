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
from typing import Optional
from contextlib import asynccontextmanager
import glob

from rich.console import Console
from rich.panel import Panel

from mcp_utils import find_free_port
from config import (
    MCP_DEFAULT_BROWSER,
    MCP_DEFAULT_HEADLESS,
    MCP_DEFAULT_SSE_TIMEOUT,
    MCP_DEFAULT_READY_WAIT_SECONDS,
    MCP_DEFAULT_TOOL_TIMEOUT_SECONDS,
    MCP_PLAYWRIGHT_TIMEOUT_SECONDS,
    DEFAULT_AIRTABLE_MCP_PACKAGE,
    AIRTABLE_TOOL_TIMEOUT,
)

console = Console()


class PlaywrightServerManager:
    """Manages Playwright MCP server lifecycle"""
    
    def __init__(self, external_url: Optional[str] = None):
        self.external_url = external_url
        self.server_process: Optional[subprocess.Popen] = None
        self.server_url: Optional[str] = None
    
    def _detect_playwright_chromium(self) -> Optional[str]:
        """Find Playwright-managed Chromium executable on macOS.
        Returns absolute path if found, otherwise None.
        """
        try:
            cache_dir = os.path.expanduser("~/Library/Caches/ms-playwright")
            pattern = os.path.join(
                cache_dir,
                "chromium-*",
                "chrome-mac",
                "Chromium.app",
                "Contents",
                "MacOS",
                "Chromium",
            )
            candidates = glob.glob(pattern)
            if not candidates:
                return None
            # Pick the most recently modified candidate
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return candidates[0]
        except Exception:
            return None
    
    async def start_server(self) -> str:
        """Start Playwright MCP server and return HTTP URL
        
        Raises:
            RuntimeError: If server fails to start or become ready
        """
        if self.external_url:
            self.server_url = self.external_url
            console.log(f"[green]Using external Playwright MCP server at {self.server_url}")
            return self.server_url
        
        port = find_free_port()
        # Use the documented endpoint for HTTP transport
        self.base_url = f"http://127.0.0.1:{port}"
        self.server_url = f"{self.base_url}/mcp"  # HTTP transport endpoint per docs
        
        # Create output directory for logs
        import tempfile
        log_dir = tempfile.mkdtemp(prefix="playwright-mcp-")
        
        cmd = [
            "npx", "-y", "@playwright/mcp@latest",
            f"--port={port}",
            "--host=127.0.0.1",
            f"--output-dir={log_dir}",
            "--timeout-action", str(MCP_PLAYWRIGHT_TIMEOUT_SECONDS * 1000),
            "--timeout-navigation", str(MCP_PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
        ]
        
        try:
            # Create a temporary file to store the output
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.log') as log_file:
                log_path = log_file.name
            
            # Start the process with output redirected to the log file
            self.server_process = subprocess.Popen(
                cmd,
                stdout=open(log_path, 'w'),
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Wait a bit for the process to start
            console.log(f"[yellow]Waiting for server to start (PID: {self.server_process.pid})...")
            await asyncio.sleep(5)  # Increased wait time
            
            # Check if the process is still running after initial wait
            if self.server_process.poll() is not None:
                # Process has already exited, read the log file
                with open(log_path, 'r') as f:
                    log_output = f.read()
                
                # Try to get any error output from the log
                error_msg = f"Process exited with code {self.server_process.returncode}.\n"
                if log_output:
                    error_msg += f"Log output:\n{log_output}"
                else:
                    error_msg += "No output was captured in the log file."
                
                console.log(f"[red]{error_msg}")
                raise RuntimeError("Failed to start Playwright MCP server")
            
            # Assume server is ready at the documented endpoint
            console.log(f"[green]Playwright MCP server is ready at {self.server_url}")
            return self.server_url
            
        except Exception as e:
            self.stop_server()
            console.log(f"[red]Error starting Playwright MCP server: {str(e)}")
            raise
    
    
    def stop_server(self):
        """Stop the Playwright MCP server process and clean up related processes"""
        if self.server_process:
            try:
                # Try graceful shutdown first
                self.server_process.send_signal(signal.SIGINT)
                try:
                    self.server_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force terminate if not responding
                    self.server_process.terminate()
                    try:
                        self.server_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # Last resort - force kill
                        self.server_process.kill()
            except Exception as e:
                console.log(f"[yellow]Warning: Error stopping server process: {e}")
            finally:
                self.server_process = None
        
        # Additional cleanup for any remaining Node.js/Playwright processes
        try:
            # Kill any remaining Playwright MCP processes
            subprocess.run(["pkill", "-f", "playwright/mcp"], 
                         stderr=subprocess.DEVNULL, 
                         stdout=subprocess.DEVNULL)
            
            # Kill any Node.js processes that might be related to Playwright
            subprocess.run(["pkill", "-f", "node.*playwright"], 
                         stderr=subprocess.DEVNULL, 
                         stdout=subprocess.DEVNULL)
        except Exception as e:
            console.log(f"[yellow]Warning during process cleanup: {e}")


class AirtableServerConfig:
    """Configuration for Airtable MCP server"""
    
    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID") 
        self.table_id = os.getenv("AIRTABLE_TABLE_ID")
        self.package = DEFAULT_AIRTABLE_MCP_PACKAGE
        self.timeout = AIRTABLE_TOOL_TIMEOUT
    
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
        from agents.mcp import MCPServerStreamableHttp, MCPServerStdio
    except ImportError as e:
        raise RuntimeError(f"OpenAI Agents SDK not available: {e}")
    
    playwright_manager = PlaywrightServerManager()
    playwright_server = None
    airtable_server = None
    
    try:
        # Start Playwright server
        playwright_url = await playwright_manager.start_server()
        playwright_server = MCPServerStreamableHttp(
            {
                "url": playwright_url,
                "timeout": MCP_DEFAULT_SSE_TIMEOUT,
            },
            client_session_timeout_seconds=MCP_DEFAULT_TOOL_TIMEOUT_SECONDS,
        )
        
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
