"""Agent prompts and instructions."""

from string import Template

# Fallback task prompt when Airtable is not configured
FALLBACK_TASK_PROMPT = "Say hello to me bro!"

# Agent narrative instructions for clear communication
NARRATIVE_INSTRUCTIONS = """
Use these prefixes in your responses:
🎤 Agent (speaking): before explaining what you're doing
🔧 when mentioning tool usage
✅ when reporting completion

Be conversational and explain each step ultra briefly as you work. Include these prefixes in all messages, including your final answer.

- Keep outputs ultra brief and focused on the user's request and avoid unrelated details.
"""

AGENT_INSTRUCTIONS_TEMPLATE = Template("""
Scrape 2 junior Python jobs from https://theprotocol.it/filtry/python;t/trainee,assistant,junior;p?sort=date

For each job, extract:
- Company name
- Position title
- Salary (or "Not specified")
- Location
- Job link
- Key requirements/skills
- Company description (or "Not available")

Create separate Airtable records with this JSON structure:

{
  "baseId": "$base_id",
  "tableId": "$table_id",
  "fields": {
    "Source": "JustJoin.it",
    "Link": "[job URL]",
    "Company": "[company name]",
    "Position": "[position title]",
    "Salary": "[salary or 'Not specified']",
    "Location": "[location]",
    "Notes": "Junior Python developer position",
    "Requirements": "[key skills]",
    "About company": "[description or 'Not available']"
  }
}
""")
