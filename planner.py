"""Schedule configuration, generation, and execution for each project command."""

from __future__ import annotations

from pathlib import Path

from models import Project
from task import COMMANDS
from task.auxiliary import generate_auxiliary
from task.configure import configure, configure_fpgas
from task.model import build_model, generate_model
from task.script import generate_script


class Planner:
    TASKS = {
        "model": ("configure", "model"),
        "auxiliary": ("configure", "model", "auxiliary generation"),
        "script": ("configure", "model", "auxiliary generation", "script generation"),
        "build": ("configure", "model", "auxiliary generation", "script generation", "script execution"),
        "simulate": ("configure", "model", "auxiliary generation", "script generation", "script execution"),
        "synthesis": ("configure", "model", "auxiliary generation", "script generation", "script execution"),
        "implementation": ("configure", "model", "auxiliary generation", "script generation", "script execution"),
        "bitstream": ("configure", "model", "auxiliary generation", "script generation", "script execution"),
        "clean": ("configure", "script generation", "script execution"),
        "cleandist": ("configure", "script generation", "script execution"),
        "program": ("configure", "script generation", "script execution"),
        "xpr": ("configure", "model", "xpr generation"),
    }

    def run(self, root: Path, command: str, target_id: str | None = None,
            task_args: tuple[str, ...] = ()) -> None:
        workflow = COMMANDS[command]
        project: Project | None = None
        temporary_script: Path | None = None
        for task in self.TASKS[command]:
            print(task, flush=True)
            if task == "configure":
                project = configure(root, command, target_id)
                if "model" not in self.TASKS[command] and hasattr(workflow, "validate"):
                    workflow.validate(project, target_id)
            elif task == "model":
                assert project is not None
                project = configure_fpgas(build_model(project))
                if hasattr(workflow, "validate"):
                    workflow.validate(project, target_id)
                generate_model(project)
            elif task == "auxiliary generation":
                assert project is not None
                generate_auxiliary(project)
            elif task == "script generation":
                assert project is not None
                if hasattr(workflow, "prepare_script"):
                    temporary_script = workflow.prepare_script(project, target_id)
                else:
                    generate_script(project)
            else:
                assert project is not None
                workflow.execute(project, target_id, task_args, temporary_script)
