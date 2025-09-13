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

Important style rules:
- Do NOT dump raw tool outputs (like full page HTML/DOM or large JSON). Instead, summarize the tool outcome in 1-2 concise sentences.
- When you call a tool, first announce it with the 🔧 prefix (what you are doing and why). After it finishes, report success with ✅ and a short result summary.
- Keep outputs ultra brief and focused on the user's request and avoid unrelated details.
"""

# AGENT_INSTRUCTIONS_TEMPLATE = Template("""
# 1. go to https://justjoin.it/job-offers/all-locations/python?experience-level=junior&orderBy=DESC&sortBy=newest
# 2. return urls of 3 first job offers with their names
# """)

AGENT_INSTRUCTIONS_TEMPLATE = Template("""
1. go to https://tvn24.pl
2. return title of the page
3. put it in airtable create_record tool basing on below data:
```json
{
"baseId": "$base_id",
"tableId": "$table_id",
"fields": {
    "Notes": "Title of the page",
    "Link": "https://tvn24.pl"
}
}
```
""")

# AGENT_INSTRUCTIONS_TEMPLATE = Template("""
# 1. 
# Open https://tenderradar.com. Return only the page title and the main heading (h1).

# 2.
# Your task is to create ONE new record using the create_record tool basing on below data:

# ```json
# {
#   "baseId": "$base_id",
#   "tableId": "$table_id",
#   "fields": {
#     "Source": "Example source",
#     "Link": "https://example.com/job",
#     "Company": "Example Co",
#     "Position": "Engineer",
#     "Salary": "100k-120k",
#     "Location": "Remote",
#     "Notes": "Added by agent",
#     "Requirements": "Python, Playwright",
#     "About company": "Great team"
#   }
# }
# ```
# """)

# AGENT_INSTRUCTIONS_TEMPLATE = Template("""
# You are a Playwright quick tester.

# Open https://tenderradar.com. Return only the page title and the main heading (h1).
# """)

# AGENT_INSTRUCTIONS_TEMPLATE = Template(
# """
# You are an expert Airtable agent.

# Your task is to create ONE new record using the create_record tool basing on below data:

# ```json
# {
#   "baseId": "$base_id",
#   "tableId": "$table_id",
#   "fields": {
#     "Source": "Example source",
#     "Link": "https://example.com/job",
#     "Company": "Example Co",
#     "Position": "Engineer",
#     "Salary": "100k-120k",
#     "Location": "Remote",
#     "Notes": "Added by agent",
#     "Requirements": "Python, Playwright",
#     "About company": "Great team"
#   }
# }
# ```
# """
# )
