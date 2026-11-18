#!/usr/bin/env python3
import fcntl
import json
import os
import pwd
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_BOARD_ROOT = Path("/var/lib/freq-agents/board")
DEFAULT_COMS_ROOT = Path("/var/lib/freq-agents/coms")
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
PROJECT_ID_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
STATUSES = ("ready", "active", "blocked", "done", "archive")
BLOCKED_RE = re.compile(
    r"\n?<!-- FREQ_BOARD_BLOCKED_BEGIN -->\n"
    r"<!-- FREQ_BOARD_BLOCKED_REASON_JSON: (?P<json>\"[^\n]*\") -->\n"
    r"## Blocked reason\n\n.*?\n"
    r"<!-- FREQ_BOARD_BLOCKED_END -->\n?",
    re.S,
)
HISTORY_END = "<!-- FREQ_BOARD_HISTORY_END -->"


class BoardError(Exception):
    pass


def fail(message):
    raise BoardError(message)


def testing():
    return os.environ.get("FREQ_BOARD_TESTING") == "1"


def board_root():
    if testing():
        return Path(os.environ.get("FREQ_BOARD_ROOT", DEFAULT_BOARD_ROOT))
    return DEFAULT_BOARD_ROOT


def coms_root():
    if testing():
        return Path(os.environ.get("FREQ_COMS_ROOT", DEFAULT_COMS_ROOT))
    return DEFAULT_COMS_ROOT


def current_agent():
    if testing() and os.environ.get("FREQ_BOARD_AGENT"):
        agent = os.environ["FREQ_BOARD_AGENT"]
    else:
        try:
            agent = pwd.getpwuid(os.geteuid()).pw_name
        except KeyError:
            fail(f"cannot determine agent from Linux uid: {os.geteuid()}")
    if not AGENT_RE.fullmatch(agent):
        fail(f"Linux account name is not a valid agent name: {agent}")
    return agent


def validate_task_name(task_name):
    if not task_name or not task_name.strip():
        fail("task name is empty")
    if len(task_name) > 160:
        fail("task name exceeds 160 characters")
    if "\n" in task_name or "\r" in task_name:
        fail("task name must be one line")
    if "/" in task_name or task_name.startswith("."):
        fail("task name is not a valid exact task title")
    if len(f"{task_name}.md".encode()) > 255:
        fail("task name is too long for a filename")


def validate_project_id(project_id):
    if not PROJECT_ID_RE.fullmatch(project_id) or len(project_id) > 64:
        fail(f"invalid project ID: {project_id}")


def validate_project(project_id):
    validate_project_id(project_id)
    project = board_root() / "projects" / project_id
    if project.is_symlink() or not project.is_dir():
        fail(f"project does not exist: {project_id}")
    for status_name in STATUSES:
        status_path = project / status_name
        if status_path.is_symlink() or not status_path.is_dir():
            fail(f"project status directory is unavailable: {status_name}")
    return project


@contextmanager
def locked(project, recover=True, exclusive=True):
    if recover and not exclusive:
        fail("transaction recovery requires an exclusive project lock")
    descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            from freq_task_identity import pending as migration_pending
            migration_pending(project)
        except ValueError as error:
            fail(str(error))
        if recover:
            from freq_board_transaction import recover as recover_transactions
            try:
                recover_transactions(project)
            except ValueError as error:
                fail(str(error))
        yield
    finally:
        os.close(descriptor)


def task_location(project, path):
    parts = path.relative_to(project).parts
    status_name = parts[0]
    owner = None
    if status_name == "active":
        if len(parts) != 3:
            fail(f"active task path is invalid: {path}")
        owner = parts[1]
    elif len(parts) != 2:
        fail(f"task path is invalid: {path}")
    return {"status": status_name, "owner": owner, "path": path}


def build_index(project):
    index = {}
    for status_name in STATUSES:
        status_root = project / status_name
        for directory, dirnames, filenames in os.walk(status_root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not (Path(directory) / name).is_symlink()
            ]
            for filename in filenames:
                if filename.startswith(".") or not filename.endswith(".md"):
                    continue
                path = Path(directory) / filename
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                    fail(f"task path is not a regular file: {path}")
                index.setdefault(filename[:-3], []).append(
                    task_location(project, path)
                )
    return index


def locate(project, task_name):
    validate_task_name(task_name)
    matches = build_index(project).get(task_name, [])
    if not matches:
        fail(f"task does not exist: {task_name}")
    if len(matches) != 1:
        fail(f"task exists in multiple board locations: {task_name}")
    return matches[0]


def task_project_option(arguments):
    """Optional leading project selector; preserve existing positional syntax."""
    if arguments and arguments[0] == "--project":
        if len(arguments) < 2:
            fail("--project requires a project ID")
        validate_project_id(arguments[1])
        return arguments[1], arguments[2:]
    return None, arguments


def find_owned_project(agent, task_name, project_id=None):
    validate_task_name(task_name)
    if project_id is not None:
        return validate_project(project_id)
    root = board_root() / "projects"
    if root.is_symlink() or not root.is_dir():
        fail(f"board projects directory is unavailable: {root}")
    matches = []
    for project in root.iterdir():
        if project.name.startswith("."):
            continue
        if (
            project.is_symlink()
            or not project.is_dir()
            or not PROJECT_ID_RE.fullmatch(project.name)
        ):
            fail(f"invalid project path: {project}")
        with locked(project):
            pass
        candidate = project / "active" / agent / f"{task_name}.md"
        if candidate.exists() or candidate.is_symlink():
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                fail(f"task path is not a regular file: {candidate}")
            matches.append(project)
    if not matches:
        fail(f"no active task owned by {agent} has this name: {task_name}")
    if len(matches) != 1:
        project_ids = ", ".join(sorted(project.name for project in matches))
        fail(f"owned task name is ambiguous across projects: {project_ids}; "
             "add --project <project-id> before the task name")
    return validate_project(matches[0].name)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read task {path.name}: {error}")


def validate_reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        fail("blocked reason must be one non-empty line")
    if "\n" in reason or "\r" in reason:
        fail("blocked reason must be one non-empty line")
    if len(reason) > 500:
        fail("blocked reason exceeds 500 characters")


def validate_note(note, label):
    if not isinstance(note, str) or not note.strip():
        fail(f"{label} must contain non-whitespace text")
    if "\x00" in note:
        fail(f"{label} must not contain a NUL byte")
    if len(note) > 8000:
        fail(f"{label} exceeds 8000 characters")


def blocked_reason(path):
    match = BLOCKED_RE.search(read_text(path))
    if not match:
        fail(f"blocked task has no reason: {path.name[:-3]}")
    try:
        reason = json.loads(match.group("json"))
    except json.JSONDecodeError as error:
        fail(f"blocked reason is invalid in {path.name}: {error}")
    validate_reason(reason)
    return reason


def set_blocked_reason(content, reason=None):
    content = BLOCKED_RE.sub("\n", content).rstrip("\n")
    if reason is None:
        return content + "\n"
    encoded = json.dumps(reason, ensure_ascii=False)
    return (
        content
        + "\n\n<!-- FREQ_BOARD_BLOCKED_BEGIN -->\n"
        + f"<!-- FREQ_BOARD_BLOCKED_REASON_JSON: {encoded} -->\n"
        + "## Blocked reason\n\n"
        + reason
        + "\n<!-- FREQ_BOARD_BLOCKED_END -->\n"
    )


def history_entry(agent, action, detail=None):
    stamp = datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="seconds")
    entry = f"- `{stamp}` — `{agent}` — **{action}**"
    if detail:
        entry += f" — {detail}"
    return entry


def append_history(content, entry):
    content = content.rstrip("\n")
    if HISTORY_END in content:
        return content.replace(HISTORY_END, f"{entry}\n{HISTORY_END}", 1) + "\n"
    return (
        content
        + "\n\n<!-- FREQ_BOARD_HISTORY_BEGIN -->\n"
        + "## Board history\n\n"
        + entry
        + "\n"
        + HISTORY_END
        + "\n"
    )


def append_task_note(content, heading, agent, note, details=()):
    validate_note(note, heading.lower())
    stamp = datetime.now(ZoneInfo("America/Chicago")).isoformat(timespec="seconds")
    lines = [
        content.rstrip("\n"),
        "",
        f"## {heading}",
        "",
        f"- Recorded at: `{stamp}`",
        f"- Recorded by: `{agent}`",
    ]
    for label, value in details:
        lines.append(f"- {label}: `{value}`")
    lines.extend(("", note, ""))
    return "\n".join(lines)


def rewrite(path, content):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.board.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o660)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def move(project, location, status_name, owner=None):
    parent = project / status_name
    if status_name == "active":
        if not owner:
            fail("active status requires an agent")
        parent = parent / owner
        if parent.is_symlink() or not parent.is_dir():
            fail(f"agent is not assigned active to this project: {owner}")
    target = parent / location["path"].name
    if target.exists() or target.is_symlink():
        fail(f"destination task path already exists: {target}")
    os.replace(location["path"], target)
    return {"status": status_name, "owner": owner, "path": target}


def require_owner(location, agent):
    if location["status"] != "active":
        fail("task must be active for this action")
    if location["owner"] != agent:
        fail(f"task is owned by {location['owner']}, not {agent}")


def require_assignment(project, agent):
    assignment = project / "active" / agent
    if assignment.is_symlink() or not assignment.is_dir():
        fail(f"agent is not assigned active to this project: {agent}")


def require_team_agent(agent):
    if not AGENT_RE.fullmatch(agent):
        fail(f"invalid recipient agent: {agent}")
    base = coms_root() / agent
    required = (base, base / "inbox", base / "read")
    if any(path.is_symlink() or not path.is_dir() for path in required):
        fail(f"recipient is not a communications team agent: {agent}")


def ensure_assignment(project, agent):
    assignment = project / "active" / agent
    if assignment.is_symlink():
        fail(f"agent assignment path must not be a symlink: {agent}")
    if assignment.exists():
        if not assignment.is_dir():
            fail(f"agent assignment path is not a directory: {agent}")
        return False
    assignment.mkdir(mode=0o2770)
    assignment.chmod(0o2770)
    return True
