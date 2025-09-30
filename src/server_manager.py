"""
Playwright MCP Server Management Module

Handles the lifecycle of the Playwright MCP server:
- Starting and stopping the server
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
from mcp_utils import find_free_port
from config import (
    MCP_DEFAULT_SSE_TIMEOUT,
    MCP_DEFAULT_TOOL_TIMEOUT_SECONDS,
    MCP_PLAYWRIGHT_TIMEOUT_SECONDS,
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


@asynccontextmanager
async def create_playwright_server():
    """Context manager that yields a ready Playwright MCP server"""
    try:
        from agents.mcp import MCPServerStreamableHttp
    except ImportError as e:
        raise RuntimeError(f"OpenAI Agents SDK not available: {e}")

    playwright_manager = PlaywrightServerManager()
    server = None

    try:
        playwright_url = await playwright_manager.start_server()
        server = MCPServerStreamableHttp(
            {
                "url": playwright_url,
                "timeout": MCP_DEFAULT_SSE_TIMEOUT,
            },
            client_session_timeout_seconds=MCP_DEFAULT_TOOL_TIMEOUT_SECONDS,
        )

        async with server:
            yield server

    finally:
        playwright_manager.stop_server()
