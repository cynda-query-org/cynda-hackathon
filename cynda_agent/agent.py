"""Root orchestrator for the Cynda multi-agent system.

Architecture
------------
root_agent  (this file)
  ├── tools:  flag_not_a_question
  └── sub_agents:
        sql_agent — schema fetch, SQL generation, execution, summarisation, iframe

To add a new capability (e.g. a chart agent), create cynda_agent/<new_agent>.py,
import it here, and append it to the sub_agents list.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from google.adk.agents import Agent

from .sql_agent import sql_agent
from .tools import flag_not_a_question

_INSTRUCTION = """You are Cynda, a data analytics assistant.

The user message may include a "Business context:" section describing the company's industry,
terminology, and priorities. Use this context to interpret questions and frame answers appropriately.

When the user asks a business data question:
- Transfer the request to sql_agent. It will fetch the schema, write SQL,
  execute it, and summarise the results.

When the input is NOT a business data question (greeting, chit-chat, off-topic):
- Call flag_not_a_question first, then answer naturally and helpfully.
"""

root_agent = Agent(
    model="gemini-2.5-flash",
    name="cynda_agent",
    description="Cynda — routes business questions to specialised sub-agents.",
    instruction=_INSTRUCTION,
    tools=[flag_not_a_question],
    sub_agents=[sql_agent],
)
