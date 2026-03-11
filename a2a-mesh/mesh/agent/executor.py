"""A2A AgentExecutor implementation backed by an OpenAI-compatible LLM."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
)

from mesh.agent.base import LLMClient
from mesh.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


class MeshAgentExecutor(AgentExecutor):
    """A2A executor backed by any OpenAI-compatible LLM.

    Bridges the A2A protocol with OpenAI chat completions.
    Maintains conversation history per context for multi-turn support.
    """

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        mcp_manager=None,
        memory_store=None,
        context_builder=None,
        agent_id: str = "",
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.tools = tools
        self.mcp_manager = mcp_manager
        self.memory_store = memory_store
        self.context_builder = context_builder
        self.agent_id = agent_id
        self._conversations: dict[str, list[dict]] = {}
        self._lateral_messages: dict[str, list[dict]] = {}

        # Merge MCP tools if available
        if self.mcp_manager and self.tools:
            mcp_tools = self.mcp_manager.get_all_tools()
            self.tools.merge(mcp_tools)

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Handle an incoming A2A message."""
        user_text = self._extract_text(context)
        context_id = self._get_context_id(context)
        task_id = self._get_task_id(context)

        logger.info(f"Executing task in context {context_id}: {user_text[:100]}")

        # Build system prompt with memory context
        effective_prompt = self.system_prompt
        if self.context_builder:
            try:
                memory_context = await self.context_builder.build_context(
                    agent_id=self.agent_id,
                    task_description=user_text,
                )
                if memory_context:
                    effective_prompt = self.system_prompt + "\n" + memory_context
            except Exception as e:
                logger.warning(f"Context building failed: {e}")

        # Build conversation history
        if context_id not in self._conversations:
            self._conversations[context_id] = [
                {"role": "system", "content": effective_prompt}
            ]

        # Inject lateral messages if any
        if context_id in self._lateral_messages:
            for msg in self._lateral_messages[context_id]:
                self._conversations[context_id].append(msg)
            self._lateral_messages[context_id].clear()

        self._conversations[context_id].append(
            {"role": "user", "content": user_text}
        )

        try:
            # If tools available and LLM supports them, use tool calling
            if self.tools and self.llm.supports_tools and len(self.tools) > 0:
                response_text = await self.llm.chat_with_tools(
                    messages=list(self._conversations[context_id]),
                    tools=self.tools.get_schemas(),
                    tool_executor=self.tools.execute,
                )
            else:
                # Stream the response
                response_text = ""
                async for chunk in self.llm.chat_stream(
                    self._conversations[context_id]
                ):
                    response_text += chunk

            # Store assistant response in history
            self._conversations[context_id].append(
                {"role": "assistant", "content": response_text}
            )

            # Save to memory
            if self.memory_store:
                try:
                    await self.memory_store.save_task_result(
                        task_id=task_id,
                        agent_id=self.agent_id,
                        input_text=user_text,
                        output_text=response_text,
                    )
                except Exception as e:
                    logger.warning(f"Memory save failed: {e}")

            # Send artifact with full response
            artifact = Artifact(
                artifactId=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text=response_text))],
                name="response",
            )
            event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    taskId=task_id,
                    contextId=context_id,
                    artifact=artifact,
                    lastChunk=True,
                )
            )

            # Send completed status
            event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    taskId=task_id,
                    contextId=context_id,
                    status=TaskStatus(state=TaskState.completed),
                    final=True,
                )
            )

        except Exception as e:
            logger.error(f"Execution failed: {e}", exc_info=True)
            event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    taskId=task_id,
                    contextId=context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            role=Role.agent,
                            messageId=str(uuid.uuid4()),
                            parts=[Part(root=TextPart(text=f"Error: {e}"))],
                        ),
                    ),
                    final=True,
                )
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Handle task cancellation."""
        context_id = self._get_context_id(context)
        event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=self._get_task_id(context),
                contextId=context_id,
                status=TaskStatus(state=TaskState.canceled),
                final=True,
            )
        )

    def receive_lateral_message(self, context_id: str, from_agent: str, content: str, message_type: str = "text") -> None:
        """Receive a lateral message from another agent (Phase 3)."""
        if context_id not in self._lateral_messages:
            self._lateral_messages[context_id] = []
        prefix = f"[{message_type.upper()} from {from_agent}]"
        self._lateral_messages[context_id].append({
            "role": "user",
            "content": f"{prefix} {content}",
        })

    def _extract_text(self, context: RequestContext) -> str:
        """Extract text content from A2A request message."""
        message = context.message
        if message and message.parts:
            texts = []
            for part in message.parts:
                if hasattr(part, "root") and hasattr(part.root, "text"):
                    texts.append(part.root.text)
                elif hasattr(part, "text"):
                    texts.append(part.text)
            return "\n".join(texts) if texts else ""
        return ""

    def _get_context_id(self, context: RequestContext) -> str:
        """Get or generate context ID."""
        if hasattr(context, "context_id") and context.context_id:
            return context.context_id
        if hasattr(context, "task") and context.task:
            return context.task.contextId or str(uuid.uuid4())
        return str(uuid.uuid4())

    def _get_task_id(self, context: RequestContext) -> str:
        """Get or generate task ID."""
        if hasattr(context, "task") and context.task:
            return context.task.id
        return str(uuid.uuid4())
