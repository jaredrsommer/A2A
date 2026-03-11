"""Task scheduler — runs routines on cron schedules."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from mesh.projects.manager import ProjectManager

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Background scheduler that creates tasks from due routines."""

    def __init__(self, project_manager: ProjectManager, check_interval: int = 60):
        self._pm = project_manager
        self._check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the scheduler background loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TaskScheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._check_routines()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_routines(self) -> None:
        """Check all routines and create tasks for due ones."""
        try:
            from croniter import croniter
        except ImportError:
            logger.debug("croniter not installed, scheduler disabled")
            return

        routines = await self._pm.list_routines()
        now = datetime.now(timezone.utc)

        for routine in routines:
            if not routine.enabled or not routine.schedule:
                continue

            try:
                cron = croniter(routine.schedule, routine.last_run or routine.created_at)
                next_run = cron.get_next(datetime)

                # Make timezone-aware if needed
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)

                if next_run <= now:
                    # Create task from template
                    template = routine.task_template
                    project_id = routine.project_id or template.get("project_id", "")

                    if project_id:
                        task = await self._pm.create_task(
                            project_id=project_id,
                            title=template.get("title", routine.name),
                            description=template.get("description", f"Routine: {routine.name}"),
                            priority=template.get("priority", 0),
                        )
                        # Auto-set to TODO so it gets picked up
                        await self._pm.update_task(task.id, status="todo")
                        logger.info(f"Scheduler created task '{task.title}' from routine '{routine.name}'")

                    # Update last_run
                    await self._pm.update_routine(routine.id, last_run=now)

            except Exception as e:
                logger.error(f"Routine '{routine.name}' error: {e}")
