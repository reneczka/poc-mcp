"""
OpenAI Agents SDK + MCP (Playwright + Airtable) POC

Single-command run: this script starts a Playwright MCP SSE server on a free
port and an Airtable MCP (stdio) server, connects via the Agents SDK, runs once,
and then shuts the servers down.

Run:
  python3 src/main.py
"""

import asyncio
from rich.console import Console
from rich.panel import Panel

from environment_setup import validate_and_setup_environment
from server_manager import AirtableServerConfig, create_mcp_servers
from agent_runner import create_web_airtable_agent, run_agent_with_task
from prompts import AGENT_INSTRUCTIONS_TEMPLATE, FALLBACK_TASK_PROMPT

console = Console()


async def main() -> None:
    """Main application entry point - clean orchestration of all components"""
    try:
        # Step 1: Validate environment and setup
        env_validator = validate_and_setup_environment()
        
        # Step 2: Create Airtable configuration
        airtable_config = AirtableServerConfig()
        
        # Step 3: Build task prompt with Airtable IDs
        if airtable_config.is_complete():
            task_prompt = AGENT_INSTRUCTIONS_TEMPLATE.substitute(
                base_id=airtable_config.base_id,
                table_id=airtable_config.table_id,
            )
        else:
            # Fallback task for Playwright-only mode
            task_prompt = FALLBACK_TASK_PROMPT
        
        # Step 4: Start MCP servers and run agent
        async with create_mcp_servers(airtable_config) as (playwright_server, airtable_server):
            # Create agent with available servers
            agent = create_web_airtable_agent(playwright_server, airtable_server)
            
            # Execute the task
            await run_agent_with_task(agent, task_prompt)
            
    except Exception as e:
        console.print(f"Application error: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("Interrupted by user.")
    except Exception as e:
        console.print(Panel(str(e), title="Fatal Error", style="red"))
