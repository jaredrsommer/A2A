"""Data models for projects, tasks, and routines."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class Project:
    """A project grouping related tasks."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = ""
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "config": self.config,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Task:
    """A task within a project."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    project_id: str = ""
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.BACKLOG
    assigned_agent: str = ""
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0  # Higher = more important
    result: str = ""
    parent_task_id: str = ""
    comments: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "assigned_agent": self.assigned_agent,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "result": self.result,
            "parent_task_id": self.parent_task_id,
            "comments": self.comments,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Routine:
    """A scheduled routine that creates tasks on a cron schedule."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = ""
    schedule: str = ""  # Cron expression
    task_template: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    enabled: bool = True
    last_run: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "task_template": self.task_template,
            "project_id": self.project_id,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "created_at": self.created_at.isoformat(),
        }
