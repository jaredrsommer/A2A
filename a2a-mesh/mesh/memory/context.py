"""Context builder — builds context prefix for agent prompts from memory."""

from __future__ import annotations

import logging

from mesh.memory.store import MemoryStore

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_BUDGET = 2000  # Approximate character budget


class ContextBuilder:
    """Builds context prefix from memory for agent prompts."""

    def __init__(self, memory_store: MemoryStore, token_budget: int = DEFAULT_TOKEN_BUDGET):
        self.memory = memory_store
        self.token_budget = token_budget

    async def build_context(
        self,
        agent_id: str,
        task_description: str,
        project_id: str = "",
    ) -> str:
        """Build context prefix from relevant past work.

        Returns a string to prepend to the system prompt.
        """
        sections = []
        budget_remaining = self.token_budget

        # 1. Search for similar past tasks
        similar = await self.memory.search_similar(task_description, limit=3)
        if similar:
            section = "## Previous Relevant Work\n"
            for item in similar:
                entry = f"- Task: {item['input'][:200]}\n  Result: {item['output'][:200]}\n  Agent: {item['agent_name']} ({item['created_at'][:10]})\n"
                if len(section) + len(entry) < budget_remaining:
                    section += entry
            if len(section) > 30:
                sections.append(section)
                budget_remaining -= len(section)

        # 2. Project context
        if project_id and budget_remaining > 200:
            project_history = await self.memory.get_project_context(project_id, limit=5)
            if project_history:
                section = "## Project Context\n"
                for item in project_history:
                    entry = f"- {item['agent_name']} completed: {item['input'][:150]}\n"
                    if len(section) + len(entry) < budget_remaining:
                        section += entry
                if len(section) > 20:
                    sections.append(section)
                    budget_remaining -= len(section)

        # 3. Agent's own history
        if budget_remaining > 200:
            history = await self.memory.get_agent_history(agent_id, limit=3)
            if history:
                section = "## Your Recent Work\n"
                for item in history:
                    entry = f"- {item['input'][:150]} → {item['output'][:100]}\n"
                    if len(section) + len(entry) < budget_remaining:
                        section += entry
                if len(section) > 20:
                    sections.append(section)

        if not sections:
            return ""

        return "\n---\n" + "\n".join(sections) + "\n---\n\n"
