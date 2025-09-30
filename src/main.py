"""
OpenAI Agents SDK + Playwright MCP POC with optional Airtable syncing.

Run:
  python3 src/main.py
"""

import asyncio
import json
from rich.console import Console
from rich.panel import Panel

from environment_setup import validate_and_setup_environment
from server_manager import create_playwright_server
from agent_runner import create_playwright_agent, run_agent_with_task
from prompts import AGENT_INSTRUCTIONS_TEMPLATE, FALLBACK_TASK_PROMPT
from airtable_client import AirtableClient, AirtableConfig

console = Console()


async def main() -> None:
    """Main application entry point - clean orchestration of all components"""
    try:
        # Step 1: Validate environment and setup
        validate_and_setup_environment()

        airtable_config = AirtableConfig.from_env()
        airtable_enabled = airtable_config.is_configured()

        # Step 2: Build task prompt with Airtable IDs
        if airtable_enabled:
            task_prompt = AGENT_INSTRUCTIONS_TEMPLATE.substitute(
                base_id=airtable_config.base_id,
                table_id=airtable_config.table_id,
            )
        else:
            # Fallback task for Playwright-only mode
            task_prompt = FALLBACK_TASK_PROMPT

        # Step 3: Start Playwright MCP server and run agent
        async with create_playwright_server() as playwright_server:
            agent = create_playwright_agent(playwright_server)

            # Execute the task
            result = await run_agent_with_task(agent, task_prompt)

        # Step 4: Sync results to Airtable if configured
        if airtable_enabled:
            final_output = getattr(result, "final_output", None)
            records = _parse_records(final_output) if final_output else None

            if records:
                client = AirtableClient(airtable_config)
                client.create_records(records)
            else:
                console.print(Panel(
                    "Agent output did not contain valid JSON records.",
                    title="Airtable",
                    style="yellow",
                ))

    except Exception as e:
        console.print(f"Application error: {e}")
        raise


def _parse_records(output_text: str):
    if not output_text:
        return None

    stripped = output_text.strip()

    # Handle console panels where JSON is enclosed between lines and optional narration
    if stripped.startswith("[") and stripped.endswith("]"):
        candidate = stripped
    else:
        # Try to locate the first '[' and last ']' to extract a JSON array
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = stripped[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, list):
        return parsed
    return None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("Interrupted by user.")
    except Exception as e:
        console.print(Panel(str(e), title="Fatal Error", style="red"))
