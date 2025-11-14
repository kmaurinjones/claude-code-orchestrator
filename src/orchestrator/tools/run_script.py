"""CLI helper to execute long-running scripts with logging and experiment tracking."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.experiments import ExperimentLogger


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a shell command, capture output, and log experiment metadata."
    )
    parser.add_argument(
        "--cmd",
        required=True,
        help="Command to execute. Wrap in quotes if it contains spaces.",
    )
    parser.add_argument(
        "--workdir",
        default=".",
        help="Working directory for the command (default: current directory).",
    )
    parser.add_argument(
        "--run-name",
        default="script-run",
        help="Name recorded in experiments.jsonl (default: script-run).",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Optional orchestrator task identifier for linkage.",
    )
    parser.add_argument(
        "--mode",
        choices=["blocking", "enqueue"],
        default="blocking",
        help="Blocking runs command immediately; enqueue hands off to orchestrator for background execution.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Optional timeout (seconds).",
    )
    parser.add_argument(
        "--metrics-file",
        default=None,
        help="Optional path to JSON file containing metrics produced by the command.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional explicit log file path. Defaults to .agentic/history/logs/<timestamp>_<run-name>.log",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional free-form notes to attach to the experiment record.",
    )
    return parser.parse_args(argv)


def ensure_log_file(provided: Optional[str], workspace: Path, run_name: str) -> Path:
    history_dir = (workspace / "history").resolve()
    logs_dir = history_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if provided:
        path = Path(provided).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
    safe_name = run_name.replace(" ", "_")
    return logs_dir / f"{timestamp}_{safe_name}.log"


def load_metrics(metrics_file: Optional[str]) -> Optional[dict]:
    if not metrics_file:
        return None
    metrics_path = Path(metrics_file)
    if not metrics_path.exists():
        raise FileNotFoundError(f"Metrics file not found: {metrics_file}")
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def run_command(
    command: str,
    workdir: Path,
    timeout: Optional[int],
    log_file: Path,
) -> int:
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    shell_cmd = command if isinstance(command, str) else shlex.join(command)
    with log_file.open("w", encoding="utf-8") as log:
        log.write(f"$ {shell_cmd}\n\n")
        log.flush()
        result = subprocess.run(
            shell_cmd,
            cwd=str(workdir),
            shell=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    return result.returncode


def _enqueue_job(
    args: argparse.Namespace,
    workspace: Path,
    log_path: Path,
) -> int:
    jobs_dir = (workspace / "history" / "jobs" / "queue").resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)

    job_id = f"{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}_{args.run_name.replace(' ', '_')}"
    job_path = jobs_dir / f"{job_id}.json"
    payload = {
        "job_id": job_id,
        "run_name": args.run_name,
        "command": args.cmd,
        "workdir": str(Path(args.workdir).resolve()),
        "timeout": args.timeout,
        "metrics_file": args.metrics_file,
        "log_file": str(log_path),
        "notes": args.notes,
        "task_id": args.task_id,
        "mode": "enqueue",
        "created_at": datetime.now().isoformat(),
    }
    job_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Enqueued long-running job: {job_id}\nLog: {log_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    workspace = Path(".agentic")
    experiment_logger = ExperimentLogger(workspace)

    started = datetime.now()
    log_path = ensure_log_file(args.log_file, workspace, args.run_name)

    if args.mode == "enqueue":
        return _enqueue_job(args, workspace, log_path)

    try:
        return_code = run_command(args.cmd, Path(args.workdir), args.timeout, log_path)
    except subprocess.TimeoutExpired:
        finished = datetime.now()
        record = experiment_logger.create_record(
            run_name=args.run_name,
            command=args.cmd,
            return_code=124,
            started=started,
            finished=finished,
            log_path=log_path,
            metrics=None,
            notes=args.notes or "Command timed out.",
        )
        experiment_logger.append(record)
        print(f"Command timed out after {args.timeout}s. Log saved to {log_path}")
        return 124
    except Exception as exc:  # pylint: disable=broad-except
        finished = datetime.now()
        record = experiment_logger.create_record(
            run_name=args.run_name,
            command=args.cmd,
            return_code=1,
            started=started,
            finished=finished,
            log_path=log_path,
            metrics=None,
            notes=f"Command raised exception: {exc}",
        )
        experiment_logger.append(record)
        print(f"Command raised exception: {exc}", file=sys.stderr)
        print(f"Log saved to {log_path}")
        return 1

    finished = datetime.now()
    metrics = None
    try:
        metrics = load_metrics(args.metrics_file)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Warning: failed to load metrics file: {exc}", file=sys.stderr)

    record = experiment_logger.create_record(
        run_name=args.run_name,
        command=args.cmd,
        return_code=return_code,
        started=started,
        finished=finished,
        log_path=log_path,
        metrics=metrics,
        artifacts={"log": str(log_path)},
        notes=args.notes,
    )
    experiment_logger.append(record)
    print(f"Command completed with exit code {return_code}. Log saved to {log_path}")
    if metrics:
        print(f"Recorded metrics: {json.dumps(metrics, indent=2)}")
    return return_code


if __name__ == "__main__":
    sys.exit(main())
