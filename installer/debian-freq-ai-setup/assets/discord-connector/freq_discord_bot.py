#!/usr/bin/env python3
"""One-bot Discord bridge for FREQ agent communications."""

from __future__ import annotations

import asyncio
import fcntl
import io
import logging
import os
import re
import sys
from freq_groups import load_groups
from datetime import datetime, timezone
from pathlib import Path

import discord

from freq_discord_core import (
    ConnectorConfig,
    ConnectorError,
    MAX_ATTACHMENT_BYTES,
    color_for,
    compose_agent_body,
    discover_roster,
    load_outbox_record,
    parse_inbound,
    stage_attachments,
    attachment_extension,
    MAX_ATTACHMENT_BATCH_BYTES,
)


LOG = logging.getLogger("freq-discord")
SUCCESS_REACTION = "✅"
FAILURE_REACTION = "🚫"
ERROR_COLOR = 0xD83C3E
MAX_REPLY_DESCRIPTION = 4096


class FreqDiscordClient(discord.Client):
    def __init__(self, config: ConnectorConfig):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.config = config
        self._outbox_task: asyncio.Task | None = None
        self._reported_invalid: dict[Path, int] = {}

    async def on_ready(self) -> None:
        LOG.info("connected as %s", self.user)
        if self._outbox_task is None or self._outbox_task.done():
            self._outbox_task = asyncio.create_task(self._outbox_loop())

    async def close(self) -> None:
        if self._outbox_task is not None:
            self._outbox_task.cancel()
            try:
                await self._outbox_task
            except asyncio.CancelledError:
                pass
        await super().close()

    def _is_authorized_message(self, message: discord.Message) -> bool:
        return bool(
            not message.author.bot
            and message.author.id == self.config.sonny_user_id
            and message.guild is not None
            and message.guild.id == self.config.guild_id
            and message.channel.id == self.config.channel_id
        )

    async def on_message(self, message: discord.Message) -> None:
        if not self._is_authorized_message(message):
            return
        try:
            await self._deliver_inbound(message)
        except ConnectorError as error:
            LOG.warning("inbound %s failed at %s: %s", message.id, error.stage, error.detail)
            await self._show_failure(message, error)
            return
        try:
            await message.add_reaction(SUCCESS_REACTION)
        except discord.HTTPException:
            LOG.exception("message %s delivered but success reaction failed", message.id)

    async def _deliver_inbound(self, message: discord.Message) -> None:
        roster = discover_roster(self.config.coms_root)
        try:
            groups = load_groups(self.config.groups_path)
        except (OSError, ValueError) as error:
            raise ConnectorError('groups', 'group registry is unavailable or invalid') from error
        parsed = parse_inbound(message.content, tuple(sorted(set(roster) | set(groups))), len(message.attachments))
        is_group = parsed.recipient in groups
        if is_group and parsed.recipient in roster:
            raise ConnectorError('groups', 'name belongs to both an agent and a group; operator must resolve the collision')
        recipients = tuple(groups[parsed.recipient]) if is_group else (parsed.recipient,)
        if not recipients:
            raise ConnectorError('groups', f'group {parsed.recipient} has no members')
        image_data = []
        filenames = []
        total_bytes = 0
        if message.attachments:
            for index, attachment in enumerate(message.attachments, start=1):
                size = getattr(attachment, "size", None)
                if isinstance(size, int) and size > MAX_ATTACHMENT_BYTES:
                    raise ConnectorError("attachments", f"file {index} exceeds the 10 MiB limit")
                try:
                    # The proxy is intended for cached images and rejects PDFs
                    # with HTTP 415. New uploads must use their original URL.
                    data = await asyncio.wait_for(attachment.read(use_cached=False), 30)
                except asyncio.TimeoutError as error:
                    raise ConnectorError('attachments', f'file {index} download timed out; no delivery was attempted') from error
                except discord.HTTPException as error:
                    raise ConnectorError(
                        "attachments", f"could not download file {index} (Discord HTTP {error.status})"
                    ) from error
                except OSError as error:
                    raise ConnectorError('attachments', f'could not download file {index} (network error)') from error
                filename = getattr(attachment, 'filename', '')
                attachment_extension(data, filename)
                total_bytes += len(data)
                if total_bytes > MAX_ATTACHMENT_BATCH_BYTES:
                    raise ConnectorError('attachments', 'attachment batch exceeds 50 MiB')
                image_data.append(data)
                filenames.append(filename)
        delivered, failed = [], []
        for recipient in recipients:
            try:
                if recipient not in roster:
                    raise ConnectorError('recipient', 'agent unavailable')
                image_paths = ()
                if image_data:
                    _, image_paths = stage_attachments(self.config.coms_root, recipient, message.id, image_data, tuple(filenames))
                body = compose_agent_body(parsed.text, image_paths)
                if is_group:
                    body = f'[Operator group message: {parsed.recipient}; addressed to: {", ".join(recipients)}]\n\n' + body
                await self._deliver_agent(recipient, body)
                delivered.append(recipient)
            except (ConnectorError, OSError) as error:
                if not is_group:
                    raise
                # A nonzero exit can follow a paste/Enter: never automatically
                # retry. Continue the original attempt for other members only.
                failed.append(recipient)
                LOG.warning('group delivery %s member %s failed: %s', message.id, recipient, type(error).__name__)
        if failed:
            raise ConnectorError('group delivery',
                f'Group {parsed.recipient}. Delivered to session: {", ".join(delivered) or "none"}. '
                f'Failed or uncertain: {", ".join(failed)}. '
                'Delivery is not acknowledgement. Do not resend the whole group message blindly.')

    async def _deliver_agent(self, recipient, body):
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.config.dev_msg),
                recipient,
                body,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
            except asyncio.TimeoutError as error:
                process.kill()
                await process.communicate()
                raise ConnectorError("agent delivery", "delivery timed out; outcome uncertain; do not resend blindly") from error
        except OSError as error:
            raise ConnectorError("agent delivery", f"cannot run dev-msg: {error}") from error
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip()
            if not detail:
                detail = stdout.decode("utf-8", "replace").strip()
            detail = detail or "dev-msg failed without output"
            boundary = re.search(
                r"\b(STORE FAILED|TARGET FAILED|LOAD FAILED|PASTE FAILED|ENTER FAILED)\b",
                detail,
            )
            raise ConnectorError(
                boundary.group(1) if boundary else "agent delivery",
                detail,
            )

    async def _show_failure(self, message: discord.Message, error: ConnectorError) -> None:
        try:
            await message.add_reaction(FAILURE_REACTION)
        except discord.HTTPException:
            LOG.exception("could not add failure reaction to message %s", message.id)
        detail = error.detail[:3500]
        embed = discord.Embed(
            title="DELIVERY FAILED",
            description=detail,
            colour=ERROR_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Failed stage", value=error.stage, inline=False)
        try:
            await message.reply(
                embed=embed,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            LOG.exception("could not post failure card for message %s", message.id)

    async def _configured_channel(self):
        channel = self.get_channel(self.config.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.config.channel_id)
            except discord.HTTPException as error:
                raise ConnectorError("Discord reply", f"cannot fetch configured channel: {error}") from error
        if getattr(channel, "guild", None) is None or channel.guild.id != self.config.guild_id:
            raise ConnectorError("Discord reply", "configured channel is not in the configured guild")
        return channel

    async def _outbox_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._drain_outbox_once()
            except Exception:
                LOG.exception("outbox pass failed")
            await asyncio.sleep(1)

    async def _drain_outbox_once(self) -> None:
        roster = discover_roster(self.config.coms_root)
        if self.config.outbox.is_symlink() or not self.config.outbox.is_dir():
            raise ConnectorError("agent reply", f"outbox is unavailable: {self.config.outbox}")
        channel = await self._configured_channel()
        candidates = sorted(
            path for path in self.config.outbox.iterdir() if path.name.endswith(".json")
        )
        for path in candidates:
            try:
                record = load_outbox_record(path, roster)
            except (ConnectorError, OSError) as error:
                try:
                    marker = path.lstat().st_mtime_ns
                except OSError:
                    continue
                if self._reported_invalid.get(path) != marker:
                    LOG.error("invalid outbox record retained: %s", error)
                    self._reported_invalid[path] = marker
                continue
            await self._post_agent_reply(channel, record.sender, record.title, record.message)
            path.unlink()
            self._reported_invalid.pop(path, None)

    async def _post_agent_reply(self, channel, sender: str, title: str, message: str) -> None:
        embed = discord.Embed(
            title=f"{sender.upper()}-MSG: [{title}]",
            colour=color_for(sender, self.config.agent_colors),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"{sender} · agent reply")
        kwargs = {
            "embed": embed,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if len(message) <= MAX_REPLY_DESCRIPTION:
            embed.description = message
        else:
            embed.description = "Full reply attached."
            safe_sender = re.sub(r"[^a-z0-9_-]", "-", sender)
            kwargs["file"] = discord.File(
                io.BytesIO(message.encode("utf-8")),
                filename=f"{safe_sender}-reply.md",
            )
        try:
            await channel.send(**kwargs)
        except discord.HTTPException as error:
            raise ConnectorError("Discord reply", f"could not post {sender} reply: {error}") from error


def read_token() -> str:
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    token_path = Path(credentials) / "discord-token" if credentials else Path("/etc/freq-agents/discord-token")
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ConnectorError("credentials", f"cannot read Discord token: {error}") from error
    if not token or any(character.isspace() for character in token):
        raise ConnectorError("credentials", "Discord token file is empty or malformed")
    return token


def singleton_lock() -> object:
    runtime = Path(os.environ.get("RUNTIME_DIRECTORY", "/run/freq-discord"))
    runtime.mkdir(mode=0o750, parents=True, exist_ok=True)
    descriptor = (runtime / "connector.lock").open("w")
    try:
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        descriptor.close()
        raise ConnectorError("startup", "another connector process is already running") from error
    return descriptor


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config_path = Path(os.environ.get("FREQ_DISCORD_CONFIG", "/etc/freq-agents/discord.json"))
        config = ConnectorConfig.load(config_path)
        token = read_token()
        lock = singleton_lock()
        client = FreqDiscordClient(config)
        client.run(token, log_handler=None)
        del lock
    except (ConnectorError, OSError) as error:
        LOG.error("STARTUP FAILED: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
