"""Role system — templates, assignment, and model compatibility."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from mesh.hardware import HardwareInfo

logger = logging.getLogger(__name__)


@dataclass
class LLMRequirements:
    """LLM requirements for a role."""

    min_params_b: float = 0.0
    min_context: int = 4096
    requires_tools: bool = False
    suggested_models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "min_params_b": self.min_params_b,
            "min_context": self.min_context,
            "requires_tools": self.requires_tools,
            "suggested_models": self.suggested_models,
        }


@dataclass
class RoleTemplate:
    """A role template that defines an agent's behavior."""

    id: str
    display_name: str
    description: str
    system_prompt: str
    autonomy_level: int = 1
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    llm_requirements: LLMRequirements = field(default_factory=LLMRequirements)
    mcp_servers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "autonomy_level": self.autonomy_level,
            "skills": self.skills,
            "tools": self.tools,
            "llm_requirements": self.llm_requirements.to_dict(),
            "mcp_servers": self.mcp_servers,
        }


# ---- Built-in Roles ----

BUILTIN_ROLES: dict[str, RoleTemplate] = {
    "architect": RoleTemplate(
        id="architect",
        display_name="Architect",
        description="Designs system architecture, makes high-level technical decisions",
        system_prompt="You are a software architect. Design systems, define APIs, create architecture diagrams, and make high-level technical decisions. Focus on scalability, maintainability, and clean separation of concerns.",
        autonomy_level=2,
        skills=["architecture", "design", "planning", "api_design"],
        tools=["read_file", "write_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=30, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest", "codellama:34b"]),
    ),
    "engineer": RoleTemplate(
        id="engineer",
        display_name="Engineer",
        description="Writes production code, implements features and fixes bugs",
        system_prompt="You are a software engineer. Write clean, tested, production-quality code. Follow best practices, write comprehensive tests, and document your work. Ask for clarification on ambiguous requirements.",
        autonomy_level=1,
        skills=["code", "implement", "debug", "test", "python", "javascript"],
        tools=["read_file", "write_file", "search_files", "execute_command"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest", "codellama:13b"]),
    ),
    "handyman": RoleTemplate(
        id="handyman",
        display_name="Handyman",
        description="Handles miscellaneous tasks, quick fixes, and odd jobs",
        system_prompt="You are a versatile handyman agent. Handle any task thrown your way — small fixes, file operations, data transformations, quick scripts. Be practical and efficient.",
        autonomy_level=1,
        skills=["general", "fix", "script", "utility"],
        tools=["read_file", "write_file", "execute_command"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=8192, suggested_models=["llama3:8b", "mistral:7b", "qwen2.5:7b"]),
    ),
    "researcher": RoleTemplate(
        id="researcher",
        display_name="Researcher",
        description="Researches topics, gathers information, analyzes data",
        system_prompt="You are a research agent. Thoroughly research topics, gather information from available sources, synthesize findings, and produce well-structured reports. Cite sources when possible.",
        autonomy_level=2,
        skills=["research", "analysis", "summarize", "report"],
        tools=["read_file", "search_files", "web_search"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=32768, suggested_models=["llama3:8b", "mistral:7b", "qwen2.5:14b"]),
    ),
    "librarian": RoleTemplate(
        id="librarian",
        display_name="Librarian",
        description="Organizes knowledge, manages documentation, curates information",
        system_prompt="You are a knowledge librarian. Organize, categorize, and curate information. Maintain documentation, create indexes, and ensure knowledge is accessible and well-structured.",
        autonomy_level=2,
        skills=["documentation", "organize", "index", "knowledge"],
        tools=["read_file", "write_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=16384, suggested_models=["llama3:8b", "mistral:7b"]),
    ),
    "reviewer": RoleTemplate(
        id="reviewer",
        display_name="Reviewer",
        description="Reviews code, documents, and artifacts for quality",
        system_prompt="You are a code and document reviewer. Carefully review artifacts for quality, correctness, security, and adherence to standards. Provide constructive, specific feedback with suggested improvements.",
        autonomy_level=2,
        skills=["review", "code_review", "quality", "security_review"],
        tools=["read_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
    "tester": RoleTemplate(
        id="tester",
        display_name="Tester",
        description="Writes and runs tests, ensures quality assurance",
        system_prompt="You are a test engineer. Write comprehensive tests — unit, integration, and end-to-end. Identify edge cases, ensure good coverage, and validate that code meets requirements.",
        autonomy_level=1,
        skills=["test", "qa", "testing", "validation"],
        tools=["read_file", "write_file", "execute_command"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "codellama:13b"]),
    ),
    "scout": RoleTemplate(
        id="scout",
        display_name="Scout",
        description="Explores codebases, maps dependencies, reports structure",
        system_prompt="You are a codebase scout. Explore and map codebases — understand structure, trace dependencies, identify patterns, and report findings. Build mental models of how systems work.",
        autonomy_level=3,
        skills=["explore", "analyze", "map", "dependency_analysis"],
        tools=["read_file", "search_files", "list_files"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=16384, suggested_models=["llama3:8b", "qwen2.5:7b"]),
    ),
    "sentry": RoleTemplate(
        id="sentry",
        display_name="Sentry",
        description="Monitors systems, watches for issues, alerts on problems",
        system_prompt="You are a monitoring sentry. Watch for issues, analyze logs, detect anomalies, and alert when problems arise. Provide clear, actionable alerts with context.",
        autonomy_level=3,
        skills=["monitor", "alert", "log_analysis", "health_check"],
        tools=["read_file", "execute_command"],
        llm_requirements=LLMRequirements(min_params_b=3, min_context=8192, suggested_models=["llama3:8b", "phi3:mini"]),
    ),
    "diplomat": RoleTemplate(
        id="diplomat",
        display_name="Diplomat",
        description="Manages communication, translates between contexts, mediates",
        system_prompt="You are a communication diplomat. Translate technical concepts for different audiences, mediate between teams, summarize discussions, and ensure clear communication across boundaries.",
        autonomy_level=2,
        skills=["communicate", "translate", "summarize", "mediate"],
        tools=["read_file", "write_file"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=16384, suggested_models=["llama3:8b", "mistral:7b"]),
    ),
    "scribe": RoleTemplate(
        id="scribe",
        display_name="Scribe",
        description="Writes documentation, READMEs, guides, and reports",
        system_prompt="You are a technical writer. Write clear, comprehensive documentation — READMEs, guides, API docs, changelogs, and reports. Make complex topics accessible.",
        autonomy_level=2,
        skills=["documentation", "writing", "readme", "guide"],
        tools=["read_file", "write_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=16384, suggested_models=["llama3:8b", "mistral:7b"]),
    ),
    "operator": RoleTemplate(
        id="operator",
        display_name="Operator",
        description="Runs commands, manages deployments, handles DevOps tasks",
        system_prompt="You are a DevOps operator. Execute commands, manage deployments, handle infrastructure tasks. Always verify before destructive operations. Report results clearly.",
        autonomy_level=0,
        skills=["devops", "deploy", "command", "infrastructure"],
        tools=["execute_command", "read_file", "write_file"],
        llm_requirements=LLMRequirements(min_params_b=7, min_context=8192, requires_tools=True, suggested_models=["llama3:8b", "mistral:7b"]),
    ),
    "analyst": RoleTemplate(
        id="analyst",
        display_name="Analyst",
        description="Analyzes data, produces insights, creates visualizations",
        system_prompt="You are a data analyst. Analyze data, find patterns, produce insights, and create clear visualizations. Use statistical methods when appropriate and present findings clearly.",
        autonomy_level=2,
        skills=["analysis", "data", "statistics", "visualization"],
        tools=["read_file", "write_file", "execute_command"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, suggested_models=["qwen2.5:14b", "llama3:8b"]),
    ),
    "designer": RoleTemplate(
        id="designer",
        display_name="Designer",
        description="Designs UI/UX, creates mockups, defines design systems",
        system_prompt="You are a UI/UX designer. Create user interfaces, design systems, and user experiences. Focus on usability, accessibility, and visual consistency. Output HTML/CSS when needed.",
        autonomy_level=2,
        skills=["design", "ui", "ux", "css", "html"],
        tools=["read_file", "write_file"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
    "debugger": RoleTemplate(
        id="debugger",
        display_name="Debugger",
        description="Diagnoses and fixes bugs, traces issues, root cause analysis",
        system_prompt="You are a debugging specialist. Diagnose bugs systematically — reproduce, isolate, trace root causes, and fix issues. Document your findings and verify fixes.",
        autonomy_level=1,
        skills=["debug", "diagnose", "trace", "fix"],
        tools=["read_file", "write_file", "execute_command", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
    "foreman": RoleTemplate(
        id="foreman",
        display_name="Foreman",
        description="Manages sub-teams, coordinates multi-step work, tracks progress",
        system_prompt="You are a team foreman. Coordinate multi-step work, track progress, ensure dependencies are met, and report status. Escalate blockers and keep work moving.",
        autonomy_level=2,
        skills=["coordinate", "manage", "track", "plan"],
        tools=["read_file", "write_file"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5:14b", "llama3:8b"]),
    ),
    "intern": RoleTemplate(
        id="intern",
        display_name="Intern",
        description="Handles simple tasks, learning-oriented, asks questions",
        system_prompt="You are a helpful intern. Handle simple, well-defined tasks. Ask for clarification when unsure. Learn from feedback and improve over time. Focus on getting things done correctly.",
        autonomy_level=0,
        skills=["general", "simple", "helper"],
        tools=["read_file", "write_file"],
        llm_requirements=LLMRequirements(min_params_b=1, min_context=4096, suggested_models=["phi3:mini", "llama3:8b", "qwen2.5:3b"]),
    ),
    "strategist": RoleTemplate(
        id="strategist",
        display_name="Strategist",
        description="Plans long-term strategy, evaluates trade-offs, prioritizes work",
        system_prompt="You are a technical strategist. Evaluate trade-offs, plan long-term strategy, prioritize work, and make recommendations. Consider technical debt, team capacity, and business goals.",
        autonomy_level=2,
        skills=["strategy", "planning", "prioritize", "evaluate"],
        tools=["read_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=30, min_context=32768, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
    "guardian": RoleTemplate(
        id="guardian",
        display_name="Guardian",
        description="Security specialist — audits code, checks vulnerabilities",
        system_prompt="You are a security guardian. Audit code for vulnerabilities, review configurations for security issues, check for common attack vectors (injection, XSS, SSRF), and recommend hardening measures.",
        autonomy_level=2,
        skills=["security", "audit", "vulnerability", "hardening"],
        tools=["read_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
    "polyglot": RoleTemplate(
        id="polyglot",
        display_name="Polyglot",
        description="Multi-language expert — translates between programming languages",
        system_prompt="You are a polyglot programmer. Work fluently across multiple programming languages. Translate code between languages, adapt patterns to different ecosystems, and bridge technology stacks.",
        autonomy_level=1,
        skills=["multi_language", "translate_code", "python", "javascript", "rust", "go"],
        tools=["read_file", "write_file", "search_files"],
        llm_requirements=LLMRequirements(min_params_b=14, min_context=16384, requires_tools=True, suggested_models=["qwen2.5-coder:32b", "deepseek-coder-v2:latest"]),
    ),
}


class RoleManager:
    """Manages role templates — builtins + custom roles."""

    def __init__(self):
        self._roles: dict[str, RoleTemplate] = dict(BUILTIN_ROLES)
        self._custom_roles: dict[str, RoleTemplate] = {}

    def get_role(self, role_id: str) -> RoleTemplate | None:
        return self._roles.get(role_id) or self._custom_roles.get(role_id)

    def get_all_roles(self) -> list[RoleTemplate]:
        roles = list(self._roles.values()) + list(self._custom_roles.values())
        return sorted(roles, key=lambda r: r.display_name)

    def add_custom_role(self, role: RoleTemplate) -> None:
        self._custom_roles[role.id] = role
        logger.info(f"Added custom role: {role.id}")

    def remove_custom_role(self, role_id: str) -> bool:
        if role_id in self._custom_roles:
            del self._custom_roles[role_id]
            return True
        return False

    def is_builtin(self, role_id: str) -> bool:
        return role_id in self._roles


def get_compatible_models(role: RoleTemplate, hardware: HardwareInfo) -> list[str]:
    """Get models compatible with the given role and hardware.

    Filters suggested models by VRAM capacity. Rough heuristics:
    - 3B params ~= 2GB VRAM
    - 7B params ~= 4GB VRAM
    - 13B params ~= 8GB VRAM
    - 32B params ~= 20GB VRAM
    - 70B params ~= 40GB VRAM
    """
    max_vram = hardware.max_vram_mb
    if max_vram == 0:
        # No GPU — return CPU-friendly small models
        return [m for m in role.llm_requirements.suggested_models if _is_small_model(m)]

    compatible = []
    for model in role.llm_requirements.suggested_models:
        estimated_vram = _estimate_model_vram(model)
        if estimated_vram <= max_vram:
            compatible.append(model)

    return compatible or role.llm_requirements.suggested_models[:1]


def _estimate_model_vram(model: str) -> int:
    """Rough VRAM estimate in MB from model name."""
    model_lower = model.lower()
    if "70b" in model_lower:
        return 40000
    if "34b" in model_lower or "32b" in model_lower:
        return 20000
    if "14b" in model_lower or "13b" in model_lower:
        return 8000
    if "7b" in model_lower or "8b" in model_lower:
        return 4500
    if "3b" in model_lower:
        return 2000
    if "mini" in model_lower or "1b" in model_lower:
        return 1000
    return 8000  # Default assumption


def _is_small_model(model: str) -> bool:
    """Check if model is small enough for CPU inference."""
    return _estimate_model_vram(model) <= 4500
