"""
OpenAI Agents SDK + Playwright MCP POC with optional Airtable syncing.

Run:
  python3 src/main.py
"""

import asyncio
import json
from rich.console import Console
from rich.panel import Panel

from config import DEFAULT_DELAY_BETWEEN_SOURCES

from environment_setup import validate_and_setup_environment
from server_manager import create_playwright_server
from agent_runner import create_playwright_agent, run_agent_with_task
from prompts import NARRATIVE_INSTRUCTIONS, generate_agent_instructions, FALLBACK_TASK_PROMPT
from airtable_client import AirtableClient, AirtableConfig

console = Console()


async def main() -> None:
    """Main application entry point - clean orchestration of all components"""
    try:
        # Step 1: Validate environment and setup
        validate_and_setup_environment()

        airtable_config = AirtableConfig.from_env()
        airtable_enabled = airtable_config.is_configured()

        if not airtable_enabled:
            console.print(Panel(
                "Airtable not configured. Cannot fetch sources.",
                title="Error",
                style="red",
            ))
            return

        # Step 2: Fetch sources from Airtable
        client = AirtableClient(airtable_config)
        sources_table_id = airtable_config.sources_table_id
        if not sources_table_id:
            console.print(Panel(
                "AIRTABLE_SOURCES_TABLE_ID not set in environment.",
                title="Error",
                style="red",
            ))
            return
        sources = client.get_all_records(sources_table_id)

        console.print(Panel(f"Fetched {len(sources)} sources from Airtable.", title="Sources", style="blue"))

        if not sources:
            console.print(Panel(
                "No sources found in Airtable.",
                title="Warning",
                style="yellow",
            ))
            return

        all_records = []

        # Step 3: For each source, scrape jobs
        async with create_playwright_server() as playwright_server:
            agent = create_playwright_agent(playwright_server)

            for source_record in sources:
                fields = source_record.get("fields", {})
                source_url = fields.get("Job Boards")  # Field is "Job Boards"

                if not source_url:
                    console.print(f"Skipping source {source_record.get('id')} due to missing URL.")
                    continue

                source_name = source_url  # Use URL as name for now

                # Build task prompt
                task_prompt = generate_agent_instructions(url=source_url, source_name=source_name)

                # Execute the task
                result = await run_agent_with_task(agent, task_prompt)

                # Parse and collect records
                final_output = getattr(result, "final_output", None)
                records = _parse_records(final_output) if final_output else None
                if records:
                    all_records.extend(records)
                else:
                    console.print(f"No valid records from {source_name}.")

                # Delay between sources to reduce rate limits
                await asyncio.sleep(DEFAULT_DELAY_BETWEEN_SOURCES)

        # Step 4: Sync all results to Airtable offers table
        if all_records:
            client.create_records(all_records)
        else:
            console.print(Panel(
                "No records to add to Airtable.",
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
