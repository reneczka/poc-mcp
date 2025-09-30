"""
Agent Execution Module

Handles agent creation, configuration, and execution:
- Creating agents with MCP servers
- Managing streamed execution
- Handling agent output and events
"""

from typing import Optional, List, Any
from rich.console import Console
from rich.panel import Panel

from config import DEFAULT_OPENAI_MODEL, MCP_MAX_TURNS
from prompts import NARRATIVE_INSTRUCTIONS

console = Console()


class AgentRunner:
    """Manages agent creation and execution"""
    
    def __init__(self, model: str = DEFAULT_OPENAI_MODEL):
        self.model = model
        self.console = console
    
    def create_agent(self, name: str, instructions: str, mcp_servers: List[Any]) -> Any:
        """Create an agent with MCP servers"""
        try:
            from agents.agent import Agent
        except ImportError as e:
            raise RuntimeError(f"OpenAI Agents SDK not available: {e}")
        
        active_servers = [server for server in mcp_servers if server is not None]
        
        return Agent(
            name=name,
            instructions=instructions,
            model=self.model,
            mcp_servers=active_servers,
        )
    
    async def run_agent_streamed(self, agent: Any, input_text: str, max_turns: int = MCP_MAX_TURNS) -> Any:
        """Execute agent with streaming output"""
        try:
            from agents import Runner, ItemHelpers
        except ImportError as e:
            raise RuntimeError(f"OpenAI Agents SDK not available: {e}")
        
        streamed = Runner.run_streamed(agent, input=input_text, max_turns=max_turns)
        self.console.print(Panel(input_text, title="User", style="magenta"))
        
        async for event in streamed.stream_events():
            await self._handle_stream_event(event)
        
        return streamed
    
    async def _handle_stream_event(self, event: Any) -> None:
        """Handle stream events"""
        if event.type == "run_item_stream_event" and event.item.type == "message_output_item":
            try:
                from agents import ItemHelpers
                text = ItemHelpers.text_message_output(event.item)
                self.console.print(Panel(text, title="Agent", style="green"))
            except Exception:
                pass
    
    
    def display_final_result(self, result: Any) -> None:
        """Display final result"""
        final_output: Optional[str] = getattr(result, "final_output", None)
        if final_output:
            self.console.print(Panel(final_output, title="Final Output"))


def create_web_airtable_agent(playwright_server: Any, airtable_server: Optional[Any]) -> Any:
    """Create agent with available servers"""
    runner = AgentRunner()
    servers = [playwright_server]
    if airtable_server:
        servers.append(airtable_server)
    
    return runner.create_agent(
        name="MCP Agent",
        instructions=NARRATIVE_INSTRUCTIONS,
        mcp_servers=servers
    )


async def run_agent_with_task(agent: Any, task_prompt: str, max_turns: int = MCP_MAX_TURNS) -> Any:
    """Run agent with task"""
    runner = AgentRunner()
    result = await runner.run_agent_streamed(agent, task_prompt, max_turns)
    runner.display_final_result(result)
    return result
