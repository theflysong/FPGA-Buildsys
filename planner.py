"""Schedule configuration, generation, and execution for each project command."""

from __future__ import annotations

from pathlib import Path

from models import Project
from task import COMMANDS
from task.aux import generate_aux
from task.configure import configure
from task.script import generate_script


class Planner:
    TASKS = {
        "aux": ("configure", "aux generation"),
        "script": ("configure", "aux generation", "script generation"),
        "build": ("configure", "aux generation", "script generation", "script execution"),
        "simulate": ("configure", "aux generation", "script generation", "script execution"),
        "synthesis": ("configure", "aux generation", "script generation", "script execution"),
        "implementation": ("configure", "aux generation", "script generation", "script execution"),
        "bitstream": ("configure", "aux generation", "script generation", "script execution"),
        "clean": ("configure", "script generation", "script execution"),
        "cleandist": ("configure", "script generation", "script execution"),
        "program": ("configure", "script generation", "script execution"),
    }

    def run(self, root: Path, command: str, target_id: str | None = None,
            task_args: tuple[str, ...] = ()) -> None:
        workflow = COMMANDS[command]
        project: Project | None = None
        temporary_script: Path | None = None
        for task in self.TASKS[command]:
            print(task, flush=True)
            if task == "configure":
                project = configure(root)
                if hasattr(workflow, "validate"):
                    workflow.validate(project, target_id)
            elif task == "aux generation":
                assert project is not None
                generate_aux(project)
            elif task == "script generation":
                assert project is not None
                if hasattr(workflow, "prepare_script"):
                    temporary_script = workflow.prepare_script(project, target_id)
                else:
                    generate_script(project)
            else:
                assert project is not None
                workflow.execute(project, target_id, task_args, temporary_script)
