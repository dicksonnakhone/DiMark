from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDecision, AgentSession
from app.services.agents.llm_client import LLMClient
from app.services.agents.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class BaseAgent:
    """ReAct agent: Think -> Act -> Observe -> repeat.

    The loop processes LLM responses that may contain:
    - text blocks (reasoning / "think" phase)
    - tool_use blocks (agent wants to call a tool / "act" phase)

    After tool execution, the observation is fed back to the LLM.
    The loop terminates when:
    - The LLM returns no tool calls (final answer)
    - Max steps reached
    - A tool requires_approval and the agent pauses
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        registry: ToolRegistry,
        system_prompt: str,
        max_steps: int = 15,
    ):
        self.llm = llm
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    async def run(
        self,
        *,
        goal: str,
        session: AgentSession,
        db: AsyncSession,
        context: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Execute the ReAct loop for the given goal."""
        session.status = "running"
        await db.flush()

        messages: list[dict[str, Any]] = []

        # Build initial user message with goal and context
        user_content = f"Goal: {goal}"
        if context:
            user_content += f"\n\nContext:\n{_format_context(context)}"
        messages.append({"role": "user", "content": user_content})

        return await self._loop(session=session, db=db, messages=messages)

    async def resume_after_approval(
        self,
        *,
        session: AgentSession,
        db: AsyncSession,
        decision_id: uuid.UUID,
        approved: bool,
    ) -> AgentSession:
        """Resume agent after human approval/rejection."""
        from sqlalchemy import select

        result = await db.execute(
            select(AgentDecision).where(AgentDecision.id == decision_id)
        )
        decision = result.scalars().first()
        if decision is None:
            session.status = "failed"
            session.error_message = "Decision not found"
            await db.flush()
            return session

        decision.approval_status = "approved" if approved else "rejected"
        await db.flush()

        pending = session.context_json.get("_pending_tool_call", {})
        messages: list[dict[str, Any]] = session.context_json.get("_messages", [])

        tool_use_id = pending.get("tool_use_id")

        if not approved:
            # Feed rejection back as tool result
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "User rejected this action. Please suggest an alternative.",
                        "is_error": True,
                    }
                ],
            })
        else:
            # Execute the approved tool
            tool_name = pending.get("tool_name")
            tool_input = pending.get("tool_input", {})

            tool_result = await self.registry.execute(
                tool_name,
                {**tool_input, "_db_session": db},
                session_id=session.id,
                decision_id=decision.id,
                db=db,
            )

            decision.tool_output = (
                tool_result.output if tool_result.success else {"error": tool_result.error}
            )
            await db.flush()

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": _format_tool_output(tool_result),
                    }
                ],
            })

        # Clean up pending state and continue
        clean_ctx = {k: v for k, v in session.context_json.items() if not k.startswith("_")}
        session.context_json = clean_ctx
        session.status = "running"
        await db.flush()

        return await self._loop(session=session, db=db, messages=messages)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(
        self,
        *,
        session: AgentSession,
        db: AsyncSession,
        messages: list[dict[str, Any]],
    ) -> AgentSession:
        """Core ReAct loop shared by run() and resume_after_approval()."""
        tools_schema = self.registry.get_tool_schemas_for_anthropic()
        step = session.current_step
        reasoning: str | None = None

        while step < self.max_steps:
            step += 1
            session.current_step = step
            await db.flush()

            # THINK: Call LLM
            try:
                response = await self.llm.create_message(
                    system=self.system_prompt,
                    messages=messages,
                    tools=tools_schema if tools_schema else None,
                )
            except Exception as exc:
                logger.exception("LLM call failed at step %d", step)
                session.status = "failed"
                session.error_message = f"LLM error: {exc}"
                await db.flush()
                return session

            content_blocks = response.get("content", [])

            # Extract reasoning text
            text_parts = [b["text"] for b in content_blocks if b["type"] == "text"]
            reasoning = "\n".join(text_parts) if text_parts else None

            # Extract tool calls
            tool_calls = [b for b in content_blocks if b["type"] == "tool_use"]

            # Record thinking decision
            if reasoning:
                db.add(
                    AgentDecision(
                        session_id=session.id,
                        step_number=step,
                        phase="think",
                        reasoning=reasoning,
                    )
                )
                await db.flush()

            # If no tool calls, the agent is done
            if not tool_calls:
                session.status = "completed"
                session.result_json = {"final_answer": reasoning}
                await db.flush()
                return session

            # Add assistant message to conversation
            messages.append({"role": "assistant", "content": content_blocks})

            # ACT: Execute each tool call
            tool_results: list[dict[str, Any]] = []
            paused = False

            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_input = tool_call["input"]
                tool_use_id = tool_call["id"]

                spec = self.registry.get(tool_name)

                # Record act decision
                act_decision = AgentDecision(
                    session_id=session.id,
                    step_number=step,
                    phase="act",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    requires_approval=spec.requires_approval if spec else False,
                )
                db.add(act_decision)
                await db.flush()

                # Check if approval is required
                if spec and spec.requires_approval:
                    session.status = "awaiting_approval"
                    session.context_json = {
                        **{k: v for k, v in session.context_json.items() if not k.startswith("_")},
                        "_pending_tool_call": {
                            "tool_use_id": tool_use_id,
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "decision_id": str(act_decision.id),
                        },
                        "_messages": messages,
                    }
                    await db.flush()
                    paused = True
                    break

                # Execute tool
                result = await self.registry.execute(
                    tool_name,
                    {**tool_input, "_db_session": db},
                    session_id=session.id,
                    decision_id=act_decision.id,
                    db=db,
                )

                act_decision.tool_output = (
                    result.output if result.success else {"error": result.error}
                )
                await db.flush()

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": _format_tool_output(result),
                })

            if paused:
                return session

            # OBSERVE: Feed tool results back to LLM
            messages.append({"role": "user", "content": tool_results})

            db.add(
                AgentDecision(
                    session_id=session.id,
                    step_number=step,
                    phase="observe",
                    tool_output={"results_count": len(tool_results)},
                )
            )
            await db.flush()

        # Max steps reached
        session.status = "completed"
        session.result_json = {"final_answer": reasoning, "note": "max_steps_reached"}
        await db.flush()
        return session


def _format_context(context: dict[str, Any]) -> str:
    parts = []
    for key, value in context.items():
        parts.append(f"- {key}: {value}")
    return "\n".join(parts)


def _format_tool_output(result: Any) -> str:
    if result.success:
        return json.dumps(result.output)
    return f"Error: {result.error}"
