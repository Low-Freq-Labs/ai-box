#!/usr/bin/env python3
import fcntl
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_TMUX_DIR = Path("/run/freq-agents/tmux")
DEFAULT_TMUX_BIN = Path("/usr/bin/tmux")
DEFAULT_COMS_ROOT = Path("/var/lib/freq-agents/coms")
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
PANE_FORMAT = "#{pane_id}|#{session_name}|#{window_name}|#{pane_dead}|#{@freq_delivery_pane}"


class BoardAlertError(Exception):
    pass


def _testing():
    return os.environ.get("FREQ_BOARD_TESTING") == "1"


def _tmux_dir():
    if _testing():
        directory = os.environ.get("FREQ_BOARD_ALERT_TMUX_DIR")
        if not directory or Path(directory).resolve() == DEFAULT_TMUX_DIR.resolve():
            raise BoardAlertError("test mode requires an isolated tmux directory or test alert sink")
        return Path(directory)
    return DEFAULT_TMUX_DIR


def _tmux_bin():
    if _testing() and os.environ.get("FREQ_BOARD_ALERT_TMUX_BIN"):
        return Path(os.environ["FREQ_BOARD_ALERT_TMUX_BIN"])
    return DEFAULT_TMUX_BIN


def _coms_root():
    if _testing() and os.environ.get("FREQ_COMS_ROOT"):
        return Path(os.environ["FREQ_COMS_ROOT"])
    return DEFAULT_COMS_ROOT


def _validate_recipient(recipient):
    if not AGENT_RE.fullmatch(recipient):
        raise BoardAlertError(f"invalid recipient agent: {recipient}")


def store_handoff_note(recipient, sender, note):
    _validate_recipient(recipient)
    if not AGENT_RE.fullmatch(sender):
        raise BoardAlertError(f"invalid sender agent: {sender}")
    if not note or not note.strip():
        raise BoardAlertError("handoff note is empty")
    if "\x00" in note:
        raise BoardAlertError("handoff note contains a NUL byte")

    base = _coms_root() / recipient
    inbox = base / "inbox"
    read_dir = base / "read"
    if (
        base.is_symlink()
        or inbox.is_symlink()
        or read_dir.is_symlink()
        or not base.is_dir()
        or not inbox.is_dir()
        or not read_dir.is_dir()
    ):
        raise BoardAlertError(
            f"recipient is not a communications team agent: {recipient}"
        )

    now = datetime.now(ZoneInfo("America/Chicago"))
    nanoseconds = time.time_ns() % 1_000_000_000
    filename = (
        f"{now:%Y-%m-%d_%H%M%S}_{nanoseconds:09d}_{os.getpid()}_{sender}.md"
    )
    message = inbox / filename
    descriptor = None
    temporary = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".task-transfer.{filename}.", dir=inbox
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(note)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o660)
        os.link(temporary, message)
        temporary.unlink()
        return message
    except (OSError, UnicodeError) as error:
        raise BoardAlertError(f"cannot store handoff note: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _socket(recipient):
    _validate_recipient(recipient)
    return _tmux_dir() / f"agent-{recipient}"


def _run_tmux(socket, arguments, *, input_text=None):
    command = [str(_tmux_bin()), "-S", str(socket), *arguments]
    try:
        return subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise BoardAlertError(f"cannot run tmux: {error}") from error


def resolve_pane(recipient):
    socket = _socket(recipient)
    if not socket.is_socket():
        raise BoardAlertError(f"recipient socket is unavailable: {socket}")
    result = _run_tmux(socket, ["list-panes", "-a", "-F", PANE_FORMAT])
    if result.returncode != 0:
        raise BoardAlertError(f"cannot query recipient tmux socket: {socket}")

    matches = []
    for row in result.stdout.splitlines():
        fields = row.split("|")
        if len(fields) != 5:
            continue
        pane_id, session_name, window_name, pane_dead, marker = fields
        if (
            session_name == recipient
            and window_name == "agent"
            and pane_dead == "0"
            and marker == "1"
            and re.fullmatch(r"%[0-9]+", pane_id)
        ):
            matches.append(pane_id)
    if not matches:
        raise BoardAlertError(
            f"no live marked delivery pane for recipient: {recipient}"
        )
    if len(matches) != 1:
        raise BoardAlertError(
            f"multiple live marked delivery panes for recipient: {recipient}"
        )
    return socket, matches[0]


def capture_visible(recipient):
    if _testing() and os.environ.get("FREQ_BOARD_ALERT_TEST_CAPTURE_FILE"):
        path = Path(os.environ["FREQ_BOARD_ALERT_TEST_CAPTURE_FILE"])
        try:
            return "%1", path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise BoardAlertError(f"cannot capture recipient pane: {error}") from error

    socket, pane_id = resolve_pane(recipient)
    result = _run_tmux(socket, ["capture-pane", "-p", "-J", "-t", pane_id])
    if result.returncode != 0:
        raise BoardAlertError(f"cannot capture recipient pane: {pane_id}")
    return pane_id, result.stdout


def _test_send(recipient, payload):
    sink_name = os.environ.get("FREQ_BOARD_ALERT_TEST_SINK")
    if not (_testing() and sink_name):
        return None
    if os.environ.get("FREQ_BOARD_ALERT_TEST_FAIL") == "1":
        raise BoardAlertError("test alert delivery failed")
    sink = Path(sink_name)
    record = json.dumps(
        {"recipient": recipient, "payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        with sink.open("a", encoding="utf-8") as stream:
            stream.write(record + "\n")
    except OSError as error:
        raise BoardAlertError(f"cannot write test alert sink: {error}") from error
    return "%test"


def send_alert(recipient, payload):
    _validate_recipient(recipient)
    if not payload or not payload.strip():
        raise BoardAlertError("alert payload is empty")
    if "\x00" in payload:
        raise BoardAlertError("alert payload contains a NUL byte")
    test_result = _test_send(recipient, payload)
    if test_result is not None:
        return test_result

    tmux_dir = _tmux_dir()
    try:
        descriptor = os.open(
            tmux_dir / f".dev-msg-{recipient}.lock",
            os.O_WRONLY | os.O_CREAT,
            0o660,
        )
    except OSError as error:
        raise BoardAlertError(f"cannot open recipient delivery lock: {error}") from error

    socket = None
    buffer_id = f"freq-board-alert-{os.getpid()}-{secrets.token_hex(4)}"
    buffer_live = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        socket, pane_id = resolve_pane(recipient)
        loaded = _run_tmux(
            socket,
            ["load-buffer", "-b", buffer_id, "-"],
            input_text=payload,
        )
        if loaded.returncode != 0:
            raise BoardAlertError("tmux rejected the exact alert buffer")
        buffer_live = True
        pasted = _run_tmux(
            socket,
            ["paste-buffer", "-p", "-r", "-b", buffer_id, "-d", "-t", pane_id],
        )
        if pasted.returncode != 0:
            raise BoardAlertError(f"tmux rejected the alert paste into pane {pane_id}")
        buffer_live = False

        # Match dev-msg: let the UI consume bracketed paste before submitting.
        # The shared recipient lock remains held across the entire sequence.
        time.sleep(0.5)
        first = _run_tmux(socket, ["send-keys", "-t", pane_id, "Enter"])
        time.sleep(0.5)
        second = _run_tmux(socket, ["send-keys", "-t", pane_id, "Enter"])
        if first.returncode != 0 or second.returncode != 0:
            raise BoardAlertError(
                f"tmux rejected one or more Enter strokes for pane {pane_id}"
            )
        return pane_id
    finally:
        if buffer_live and socket is not None:
            _run_tmux(socket, ["delete-buffer", "-b", buffer_id])
        os.close(descriptor)
