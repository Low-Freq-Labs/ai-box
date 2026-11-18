#!/usr/bin/env python3
"""Pure validation and storage core for the FREQ Discord connector."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import secrets
from dataclasses import dataclass
from pathlib import Path
from freq_groups import GROUPS


AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
OUTBOX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{9}_\d+_([a-z][a-z0-9_-]*)\.json$"
)
DISCORD_ID_RE = re.compile(r"^[1-9][0-9]{16,20}$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = MAX_IMAGES
MAX_ATTACHMENT_BYTES = MAX_IMAGE_BYTES
DEFAULT_COMS_ROOT = Path("/var/lib/freq-agents/coms")
DEFAULT_OUTBOX = Path("/var/lib/freq-agents/discord/outbox")
DEFAULT_DEV_MSG = Path("/usr/local/bin/dev-msg")
DEFAULT_CONFIG = Path("/etc/freq-agents/discord.json")

DEFAULT_PALETTE = (
    0x4DA3FF,
    0xB56CFF,
    0x36C98F,
    0xFF7A45,
    0xF5C542,
    0xEA5B85,
    0x43C7D9,
    0x8BC34A,
)


class ConnectorError(Exception):
    """One named connector boundary failed."""

    def __init__(self, stage: str, detail: str):
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class ConnectorConfig:
    sonny_user_id: int
    guild_id: int
    channel_id: int
    agent_colors: dict[str, int]
    coms_root: Path = DEFAULT_COMS_ROOT
    outbox: Path = DEFAULT_OUTBOX
    dev_msg: Path = DEFAULT_DEV_MSG
    groups_path: Path = GROUPS

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG) -> "ConnectorConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ConnectorError("configuration", f"cannot read {path}: {error}") from error
        if not isinstance(raw, dict):
            raise ConnectorError("configuration", "configuration must be a JSON object")
        allowed = {
            "sonny_user_id",
            "guild_id",
            "channel_id",
            "agent_colors",
        }
        unexpected = sorted(set(raw) - allowed)
        if unexpected:
            raise ConnectorError(
                "configuration", "unexpected keys: " + ", ".join(unexpected)
            )

        identifiers = {}
        for name in ("sonny_user_id", "guild_id", "channel_id"):
            value = str(raw.get(name, ""))
            if not DISCORD_ID_RE.fullmatch(value):
                raise ConnectorError("configuration", f"{name} must be a Discord ID")
            identifiers[name] = int(value)

        raw_colors = raw.get("agent_colors", {})
        if not isinstance(raw_colors, dict):
            raise ConnectorError("configuration", "agent_colors must be an object")
        colors = {}
        for agent, value in raw_colors.items():
            if not isinstance(agent, str) or not AGENT_RE.fullmatch(agent):
                raise ConnectorError("configuration", f"invalid color agent: {agent!r}")
            if not isinstance(value, str) or not HEX_COLOR_RE.fullmatch(value):
                raise ConnectorError(
                    "configuration", f"color for {agent} must be #RRGGBB"
                )
            colors[agent] = int(value[1:], 16)

        return cls(agent_colors=colors, **identifiers)


@dataclass(frozen=True)
class InboundMessage:
    recipient: str
    text: str


@dataclass(frozen=True)
class OutboxRecord:
    path: Path
    sender: str
    title: str
    message: str


def discover_roster(coms_root: Path) -> tuple[str, ...]:
    if coms_root.is_symlink() or not coms_root.is_dir():
        raise ConnectorError("recipient", f"communications roster is unavailable: {coms_root}")
    agents = []
    for path in coms_root.iterdir():
        if path.name.startswith("."):
            continue
        if (
            AGENT_RE.fullmatch(path.name)
            and path.name not in ("sonny", "freq-discord")
            and not path.is_symlink()
            and path.is_dir()
            and (path / "inbox").is_dir()
            and not (path / "inbox").is_symlink()
        ):
            agents.append(path.name)
    return tuple(sorted(agents))


def parse_inbound(content: str, roster: tuple[str, ...], attachment_count: int) -> InboundMessage:
    if attachment_count < 0 or attachment_count > MAX_IMAGES:
        raise ConnectorError("attachments", f"send between 0 and {MAX_IMAGES} attachments")
    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*)(?:[:,])?(?:\s+(.*))?$", content, re.S)
    if not match:
        raise ConnectorError("recipient", "start the message with an agent name")
    recipient = match.group(1).lower()
    if recipient not in roster:
        available = ", ".join(roster) if roster else "none"
        raise ConnectorError(
            "recipient", f"unknown agent {recipient!r}; available agents: {available}"
        )
    text = (match.group(2) or "").strip()
    if not text and attachment_count == 0:
        raise ConnectorError("message", "include a message or at least one attachment")
    return InboundMessage(recipient=recipient, text=text)


def detect_image_extension(data: bytes) -> str:
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ConnectorError("images", "only PNG, JPEG, and WebP pictures are accepted")


TEXT_EXTENSIONS = frozenset(('.md', '.markdown', '.txt', '.log', '.csv', '.tsv',
    '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.xml',
    '.html', '.css', '.svg', '.js', '.jsx', '.ts', '.tsx', '.py', '.sh', '.ps1',
    '.sql', '.diff', '.patch', '.rst', '.srt', '.vtt', '.c', '.h', '.cpp', '.rs',
    '.go', '.java', '.cs'))
MAX_ATTACHMENT_BATCH_BYTES = 50 * 1024 * 1024


def attachment_extension(data: bytes, filename: str = '') -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ConnectorError('attachments', 'each attachment must contain 1 byte to 10 MiB')
    try:
        return detect_image_extension(data)
    except ConnectorError:
        pass
    extension = Path(filename or '').suffix.lower()
    if extension == '.pdf' and data.startswith(b'%PDF-'):
        return '.pdf'
    if extension in {'.zip', '.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp'} and data.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        return extension
    if extension in TEXT_EXTENSIONS:
        try:
            encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = data.decode(encoding)
        except UnicodeDecodeError as error:
            raise ConnectorError('attachments', 'text attachments must be UTF-8 or UTF-16 with a byte-order mark') from error
        if any(ord(c) < 32 and c not in '\t\r\n\f' or 127 <= ord(c) <= 159 for c in text):
            raise ConnectorError('attachments', 'text attachment contains binary/control bytes')
        return extension
    raise ConnectorError('attachments', 'unsupported file: send pictures, text/Markdown/source, PDF, ZIP or DOCX/XLSX/PPTX/ODT/ODS/ODP documents')


def attachment_name(index: int, filename: str, extension: str) -> str:
    # Preserve existing picture paths. Document names remain recognizable, while
    # path components/control characters cannot become part of the destination.
    if extension in {'.png', '.jpg', '.webp', '.gif'}:
        return f'{index:02d}{extension}'
    basename = (filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    stem = Path(basename).stem
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('._-')[:100] or 'attachment'
    return f'{index:02d}-{safe}{extension}'


def stage_attachments(
    coms_root: Path,
    recipient: str,
    discord_message_id: int,
    images: list[bytes],
    filenames: tuple[str, ...] | None = None,
) -> tuple[Path, tuple[Path, ...]]:
    filenames = filenames if filenames is not None else ('',) * len(images)
    if len(filenames) != len(images):
        raise ConnectorError('attachments', 'attachment metadata count mismatch')
    if sum(map(len, images)) > MAX_ATTACHMENT_BATCH_BYTES:
        raise ConnectorError('attachments', 'attachment batch exceeds 50 MiB')
    extensions = [attachment_extension(data, name) for data, name in zip(images, filenames)]
    if not AGENT_RE.fullmatch(recipient):
        raise ConnectorError("attachments", f"invalid recipient: {recipient}")
    if not images or len(images) > MAX_IMAGES:
        raise ConnectorError("attachments", f"send between 1 and {MAX_ATTACHMENTS} attachments")
    message_id = str(discord_message_id)
    if not message_id.isdigit():
        raise ConnectorError("attachments", "Discord message ID is invalid")
    media_root = coms_root / recipient / "media"
    if media_root.is_symlink() or not media_root.is_dir():
        raise ConnectorError("attachments", f"recipient attachment directory is unavailable: {media_root}")
    destination = media_root / message_id
    if destination.exists() or destination.is_symlink():
        raise ConnectorError("attachments", f"attachments already exist for Discord message {message_id}; inspect the original delivery before resending")

    # The installer supplies setgid and a default ACL on media/. Request only
    # ordinary permission bits; mkdir inherits the group/setgid from its parent.
    # Explicit chmod(2770) is forbidden by RestrictSUIDSGID in the service.
    temporary = media_root / f".incoming-{message_id}-{secrets.token_hex(12)}"
    os.mkdir(temporary, 0o770)
    paths = []
    records = []
    try:
        metadata = temporary.stat()
        if stat.S_IMODE(metadata.st_mode) != 0o2770 or metadata.st_gid != media_root.stat().st_gid:
            raise ConnectorError("attachments", "attachment permissions were not inherited; infrastructure repair is required")
        for index, data in enumerate(images, start=1):
            if not data:
                raise ConnectorError("attachments", f"file {index} is empty")
            if len(data) > MAX_IMAGE_BYTES:
                raise ConnectorError(
                    "attachments", f"file {index} exceeds the 10 MiB limit"
                )
            extension = extensions[index - 1]
            path = temporary / attachment_name(index, filenames[index - 1], extension)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), 0o660)
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            paths.append(destination / path.name)
            records.append({'index': index, 'filename': filenames[index - 1],
                            'stored_name': path.name, 'bytes': len(data),
                            'sha256': hashlib.sha256(data).hexdigest()})
        manifest = temporary / 'attachments.json'
        descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump({'schema': 1, 'recipient': recipient, 'discord_message_id': message_id,
                       'files': records}, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o660)
        marker = temporary / ".freq-discord-media"
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{recipient}:{message_id}\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o660)
        directory_fd = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(temporary, destination)
        directory_fd = os.open(media_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return destination, tuple(paths)


def stage_images(coms_root, recipient, discord_message_id, images):
    """Compatibility for existing image callers; same atomic staging and ACLs."""
    return stage_attachments(coms_root, recipient, discord_message_id, images)


def compose_agent_body(text: str, image_paths: tuple[Path, ...]) -> str:
    pieces = []
    if text:
        pieces.append(text)
    if image_paths:
        only_images = all(path.suffix in {'.png', '.jpg', '.webp'} for path in image_paths)
        lines = [f"{'Pictures' if only_images else 'Attachments'} ({len(image_paths)}):"]
        lines.extend(f"- {path}" for path in image_paths)
        if not only_images:
            lines.append('Read these files as supplied task material. GIF files retain their animation; inspect frames as needed. ZIP files are not automatically extracted and source files are not automatically executed.')
        pieces.append("\n".join(lines))
    body = "\n\n".join(pieces)
    if not body:
        raise ConnectorError("message", "message body is empty")
    return body


def color_for(agent: str, configured: dict[str, int]) -> int:
    if agent in configured:
        return configured[agent]
    digest = hashlib.sha256(agent.encode("utf-8")).digest()
    return DEFAULT_PALETTE[int.from_bytes(digest[:2], "big") % len(DEFAULT_PALETTE)]


def load_outbox_record(path: Path, roster: tuple[str, ...]) -> OutboxRecord:
    match = OUTBOX_RE.fullmatch(path.name)
    if not match:
        raise ConnectorError("agent reply", f"invalid outbox filename: {path.name}")
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode):
        raise ConnectorError("agent reply", f"outbox entry is not a regular file: {path.name}")
    if stat.S_IMODE(details.st_mode) != 0o660:
        raise ConnectorError("agent reply", f"outbox entry mode is not 0660: {path.name}")
    suffix_sender = match.group(1)
    if suffix_sender not in roster:
        raise ConnectorError("agent reply", f"sender is not in the roster: {suffix_sender}")
    try:
        owner = pwd.getpwuid(details.st_uid).pw_name
    except KeyError as error:
        raise ConnectorError("agent reply", f"outbox owner is unknown: {details.st_uid}") from error
    if owner != suffix_sender:
        raise ConnectorError(
            "agent reply", f"owner {owner} does not match filename sender {suffix_sender}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConnectorError("agent reply", f"cannot read {path.name}: {error}") from error
    if not isinstance(raw, dict) or set(raw) != {"schema", "sender", "title", "message"}:
        raise ConnectorError("agent reply", f"outbox schema is invalid: {path.name}")
    if raw["schema"] != 1:
        raise ConnectorError("agent reply", f"unsupported schema in {path.name}")
    for key in ("sender", "title", "message"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ConnectorError("agent reply", f"{key} is empty in {path.name}")
    if raw["sender"] != suffix_sender:
        raise ConnectorError("agent reply", f"payload sender does not match {path.name}")
    return OutboxRecord(
        path=path,
        sender=raw["sender"],
        title=raw["title"],
        message=raw["message"],
    )
