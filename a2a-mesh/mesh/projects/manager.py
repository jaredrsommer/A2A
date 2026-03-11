"""Project manager — CRUD for projects and tasks, backed by SQLite."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from mesh.projects.models import Project, ProjectStatus, Task, TaskStatus, Routine

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages projects, tasks, and routines via SQLite."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def initialize(self) -> None:
        """Create project management tables."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                config TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'backlog',
                assigned_agent TEXT DEFAULT '',
                depends_on TEXT DEFAULT '[]',
                priority INTEGER DEFAULT 0,
                result TEXT DEFAULT '',
                parent_task_id TEXT DEFAULT '',
                comments TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                schedule TEXT NOT NULL,
                task_template TEXT DEFAULT '{}',
                project_id TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                last_run TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """)
        await self._db.commit()

    # ---- Projects ----

    async def create_project(self, name: str, description: str = "", config: dict | None = None) -> Project:
        project = Project(name=name, description=description, config=config or {})
        await self._db.execute(
            "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project.id, project.name, project.description, project.status.value,
             json.dumps(project.config), project.created_at.isoformat(), project.updated_at.isoformat()),
        )
        await self._db.commit()
        return project

    async def get_project(self, project_id: str) -> Project | None:
        async with self._db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Project(
                id=row[0], name=row[1], description=row[2],
                status=ProjectStatus(row[3]), config=json.loads(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]),
            )

    async def list_projects(self) -> list[Project]:
        async with self._db.execute("SELECT * FROM projects ORDER BY updated_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [
                Project(
                    id=r[0], name=r[1], description=r[2],
                    status=ProjectStatus(r[3]), config=json.loads(r[4]),
                    created_at=datetime.fromisoformat(r[5]),
                    updated_at=datetime.fromisoformat(r[6]),
                )
                for r in rows
            ]

    async def update_project(self, project_id: str, **kwargs) -> Project | None:
        project = await self.get_project(project_id)
        if not project:
            return None
        for key, value in kwargs.items():
            if hasattr(project, key):
                setattr(project, key, value)
        project.updated_at = datetime.now(timezone.utc)
        await self._db.execute(
            "UPDATE projects SET name=?, description=?, status=?, config=?, updated_at=? WHERE id=?",
            (project.name, project.description, project.status.value if isinstance(project.status, ProjectStatus) else project.status,
             json.dumps(project.config), project.updated_at.isoformat(), project_id),
        )
        await self._db.commit()
        return project

    async def delete_project(self, project_id: str) -> bool:
        await self._db.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
        cursor = await self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # ---- Tasks ----

    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str = "",
        depends_on: list[str] | None = None,
        priority: int = 0,
        parent_task_id: str = "",
    ) -> Task:
        task = Task(
            project_id=project_id, title=title, description=description,
            depends_on=depends_on or [], priority=priority,
            parent_task_id=parent_task_id,
        )
        await self._db.execute(
            """INSERT INTO tasks (id, project_id, title, description, status, assigned_agent,
               depends_on, priority, result, parent_task_id, comments, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.project_id, task.title, task.description,
             task.status.value, task.assigned_agent, json.dumps(task.depends_on),
             task.priority, task.result, task.parent_task_id,
             json.dumps(task.comments), task.created_at.isoformat(),
             task.updated_at.isoformat()),
        )
        await self._db.commit()
        return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_task(row) if row else None

    async def list_tasks(self, project_id: str) -> list[Task]:
        async with self._db.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY priority DESC, created_at",
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_task(r) for r in rows]

    async def update_task(self, task_id: str, **kwargs) -> Task | None:
        task = await self.get_task(task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)
        status_val = task.status.value if isinstance(task.status, TaskStatus) else task.status
        await self._db.execute(
            """UPDATE tasks SET title=?, description=?, status=?, assigned_agent=?,
               depends_on=?, priority=?, result=?, parent_task_id=?, comments=?, updated_at=?
               WHERE id=?""",
            (task.title, task.description, status_val, task.assigned_agent,
             json.dumps(task.depends_on), task.priority, task.result,
             task.parent_task_id, json.dumps(task.comments),
             task.updated_at.isoformat(), task_id),
        )
        await self._db.commit()
        return task

    async def delete_task(self, task_id: str) -> bool:
        cursor = await self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def add_task_comment(self, task_id: str, author: str, text: str) -> bool:
        task = await self.get_task(task_id)
        if not task:
            return False
        comment = {
            "author": author,
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        task.comments.append(comment)
        await self._db.execute(
            "UPDATE tasks SET comments = ?, updated_at = ? WHERE id = ?",
            (json.dumps(task.comments), datetime.now(timezone.utc).isoformat(), task_id),
        )
        await self._db.commit()
        return True

    async def get_ready_tasks(self, project_id: str) -> list[Task]:
        """Get tasks that are ready to execute (deps satisfied, status=todo)."""
        tasks = await self.list_tasks(project_id)
        done_ids = {t.id for t in tasks if t.status == TaskStatus.DONE}
        return [
            t for t in tasks
            if t.status == TaskStatus.TODO
            and all(dep in done_ids for dep in t.depends_on)
        ]

    # ---- Routines ----

    async def create_routine(
        self, name: str, schedule: str, task_template: dict,
        project_id: str = "", enabled: bool = True,
    ) -> Routine:
        routine = Routine(
            name=name, schedule=schedule, task_template=task_template,
            project_id=project_id, enabled=enabled,
        )
        await self._db.execute(
            "INSERT INTO routines (id, name, schedule, task_template, project_id, enabled, last_run, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (routine.id, routine.name, routine.schedule, json.dumps(routine.task_template),
             routine.project_id, int(routine.enabled), None, routine.created_at.isoformat()),
        )
        await self._db.commit()
        return routine

    async def list_routines(self) -> list[Routine]:
        async with self._db.execute("SELECT * FROM routines ORDER BY created_at") as cursor:
            rows = await cursor.fetchall()
            return [_row_to_routine(r) for r in rows]

    async def update_routine(self, routine_id: str, **kwargs) -> bool:
        sets = []
        vals = []
        for key, value in kwargs.items():
            if key == "task_template":
                value = json.dumps(value)
            if key == "enabled":
                value = int(value)
            if key == "last_run" and isinstance(value, datetime):
                value = value.isoformat()
            sets.append(f"{key} = ?")
            vals.append(value)
        if not sets:
            return False
        vals.append(routine_id)
        await self._db.execute(
            f"UPDATE routines SET {', '.join(sets)} WHERE id = ?", vals,
        )
        await self._db.commit()
        return True

    async def delete_routine(self, routine_id: str) -> bool:
        cursor = await self._db.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        await self._db.commit()
        return cursor.rowcount > 0


def _row_to_task(row: tuple) -> Task:
    return Task(
        id=row[0], project_id=row[1], title=row[2], description=row[3],
        status=TaskStatus(row[4]), assigned_agent=row[5],
        depends_on=json.loads(row[6]), priority=row[7], result=row[8],
        parent_task_id=row[9], comments=json.loads(row[10]),
        created_at=datetime.fromisoformat(row[11]),
        updated_at=datetime.fromisoformat(row[12]),
    )


def _row_to_routine(row: tuple) -> Routine:
    return Routine(
        id=row[0], name=row[1], schedule=row[2],
        task_template=json.loads(row[3]), project_id=row[4],
        enabled=bool(row[5]),
        last_run=datetime.fromisoformat(row[6]) if row[6] else None,
        created_at=datetime.fromisoformat(row[7]),
    )
