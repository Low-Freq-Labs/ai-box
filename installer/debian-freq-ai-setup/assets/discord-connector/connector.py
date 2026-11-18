#!/usr/bin/env python3
"""One authenticated operator, one guild/channel, one connector process."""
import asyncio
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import socket

import aiohttp
import discord
from discord import app_commands
from datetime import datetime, timezone
from freq_discord_bot import FreqDiscordClient
from freq_discord_core import ConnectorConfig, ConnectorError, color_for

NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FILE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d+_\d+_([a-z][a-z0-9-]{0,31})\.json$")
LIMIT = 1024 * 1024


class SafeDiscordLog(logging.Handler):
    """Expose failure locations without logging message bodies or interaction tokens."""
    def emit(self, record):
        if record.exc_info and record.exc_info[0]:
            trace = record.exc_info[2]
            locations = []
            while trace:
                locations.append(f'{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}')
                trace = trace.tb_next
            print(f'DISCORD_ERROR type={record.exc_info[0].__name__} trace={",".join(locations)}', flush=True)
        else:
            print(f'DISCORD_LOG level={record.levelname} source={record.name}', flush=True)


def roster(root):
    return sorted(p.name for p in Path(root).iterdir()
                  if NAME.fullmatch(p.name) and p.name not in ('sonny', 'freq-discord')
                  and not p.is_symlink() and p.is_dir()
                  and (p / 'inbox').is_dir() and not (p / 'inbox').is_symlink())


def authorized(config, interaction):
    return (not interaction.user.bot
            and interaction.user.id == config['user_id']
            and interaction.guild_id == config['guild_id']
            and interaction.channel_id == config['channel_id'])


def read_record(path, agents):
    match = FILE.fullmatch(path.name)
    if not match:
        raise ValueError('invalid filename')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o660 or meta.st_size > LIMIT:
            raise ValueError('invalid record metadata')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('oversize record')
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != {'schema', 'sender', 'title', 'message'}:
        raise ValueError('invalid schema')
    if type(record['schema']) is not int or record['schema'] != 1:
        raise ValueError('invalid schema version')
    if any(not isinstance(record[k], str) or not record[k].strip() for k in ('sender', 'title', 'message')):
        raise ValueError('invalid fields')
    sender = record['sender']
    if sender not in agents or sender != match[1] or pwd.getpwuid(meta.st_uid).pw_name != sender:
        raise ValueError('sender ownership mismatch')
    return record, meta, hashlib.sha256(raw).hexdigest()


class Connector(FreqDiscordClient):
    def __init__(self, config, token, state):
        frontend = ConnectorConfig(
            sonny_user_id=config['user_id'], guild_id=config['guild_id'],
            channel_id=config['channel_id'], agent_colors={},
            coms_root=Path(config['coms_root']), outbox=Path(config['outbox']),
            dev_msg=Path(config.get('dev_msg', '/usr/local/bin/dev-msg')))
        super().__init__(frontend)
        self.site, self.token, self.state = config, token, state
        self.db = sqlite3.connect(state / 'deliveries.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS deliveries (name TEXT PRIMARY KEY, digest TEXT, status TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS delivery_receipts (name TEXT PRIMARY KEY, remote_id TEXT, boundary TEXT, updated_at TEXT)')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.commit()
        self.seen = set()
        self.rejected = set()
        self.delivery_lock = asyncio.Lock()
        self.worker = None
        self.tree = app_commands.CommandTree(self)
        self.control_cache = (0.0, {})

    async def control(self, action, agent=None):
        request = {'action': action}
        if agent is not None:
            request['agent'] = agent
        async def exchange():
            reader, writer = await asyncio.open_unix_connection('/run/freq-agent-control.sock', limit=131072)
            try:
                writer.write(json.dumps(request).encode() + b'\n')
                await writer.drain()
                return json.loads(await reader.readline())
            finally:
                writer.close()
                await writer.wait_closed()
        return await asyncio.wait_for(exchange(), 35)

    async def on_interaction(self, interaction):
        # CommandTree handles dispatch; this hook records no payload or token.
        print(f'DISCORD_INTERACTION type={interaction.type.value} authorized={authorized(self.site, interaction)}', flush=True)

    async def choices(self, interaction, current, state):
        if not authorized(self.site, interaction):
            return []
        now = asyncio.get_running_loop().time()
        try:
            if now - self.control_cache[0] > 2:
                result = await asyncio.wait_for(self.control('list'), 2)
                if not result.get('ok'):
                    return []
                self.control_cache = (now, result['agents'])
            return [app_commands.Choice(name=name, value=name)
                    for name, value in self.control_cache[1].items()
                    if name != 'team' and value == state and current.lower() in name][:25]
        except (OSError, ValueError, asyncio.TimeoutError):
            return []

    async def control_team(self, action):
        """Expand an explicitly typed target through the existing lifecycle bridge."""
        if action not in ('start', 'stop'):
            raise ValueError('Unsupported team action')
        listed = await self.control('list')
        if not isinstance(listed, dict):
            return {'ok': False, 'message': 'Cannot read the registered team. No lifecycle actions submitted.'}
        agents = listed.get('agents')
        if not listed.get('ok') or not isinstance(agents, dict):
            return {'ok': False, 'message': 'Cannot read the registered team. No lifecycle actions submitted.'}
        if any(not isinstance(name, str) or not NAME.fullmatch(name)
               or name in ('team', 'sonny', 'freq-discord') for name in agents):
            return {'ok': False, 'message': 'Invalid team roster. No lifecycle actions submitted.'}
        expected = 'stopped' if action == 'start' else 'running'
        target = 'running' if action == 'start' else 'stopped'
        completed = 'started' if action == 'start' else 'stopped'
        lines, ok = [], True
        for name, state in sorted(agents.items()):
            if state == target:
                lines.append(f'{name}: already {target}.')
                continue
            if state != expected:
                ok = False
                lines.append(f'{name}: unknown state; check /agents. No action submitted.')
                continue
            try:
                result = await self.control(action, name)
                if not isinstance(result, dict):
                    raise ValueError('Invalid lifecycle response')
                if result.get('ok'):
                    lines.append(f'{name}: {completed}.')
                else:
                    ok = False
                    detail = str(result.get('message', 'Lifecycle request failed.'))[:180]
                    lines.append(f'{name}: {detail}')
            except (OSError, ValueError, asyncio.TimeoutError):
                ok = False
                lines.append(f'{name}: outcome uncertain; check /agents before retrying.')
        return {'ok': ok, 'message': '\n'.join(lines) or 'No registered agents.'}

    async def management(self, interaction, action, agent=None):
        if not authorized(self.site, interaction):
            await interaction.response.send_message('Not authorized here.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            if agent == 'team' and action in ('start', 'stop'):
                result = await self.control_team(action)
            else:
                result = await self.control(action, agent)
            self.control_cache = (0.0, {})
            if action == 'list' and result.get('ok'):
                lines = [f"{'✅' if state == 'running' else '🚫' if state == 'stopped' else '⚠️'} **{name}** — {state}"
                         for name, state in result['agents'].items()]
                pages, page = [], ''
                for line in lines:
                    if len(page) + len(line) > 3800:
                        pages.append(page)
                        page = ''
                    page += line + '\n'
                pages.append(page or 'No registered agents.')
                for page in pages:
                    await interaction.followup.send(embed=discord.Embed(title='Agents', description=page, colour=0xA855F7), ephemeral=True)
                return
            output = result.get('message', 'Lifecycle request failed.')[:3500]
            embed = discord.Embed(title=('Success' if result.get('ok') else 'Unable to complete'),
                                  description=output, colour=0x36C98F if result.get('ok') else 0xD83C3E)
        except (OSError, ValueError, asyncio.TimeoutError):
            embed = discord.Embed(title='Control unavailable', colour=0xD83C3E,
                                  description='Check /agents before retrying; the previous action may have completed.')
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    def define_commands(self):
        guild = discord.Object(id=self.site['guild_id'])
        @self.tree.command(name='agents', description='Show registered agents and their running state', guild=guild)
        async def agents(interaction: discord.Interaction):
            await self.management(interaction, 'list')
        @self.tree.command(name='start', description='Start a stopped agent', guild=guild)
        async def start(interaction: discord.Interaction, agent: str):
            await self.management(interaction, 'start', agent)
        @start.autocomplete('agent')
        async def start_choices(interaction: discord.Interaction, current: str):
            return await self.choices(interaction, current, 'stopped')
        @self.tree.command(name='stop', description='Stop a running agent', guild=guild)
        async def stop(interaction: discord.Interaction, agent: str):
            await self.management(interaction, 'stop', agent)
        @stop.autocomplete('agent')
        async def stop_choices(interaction: discord.Interaction, current: str):
            return await self.choices(interaction, current, 'running')
        return guild, (agents, start, stop)

    async def setup_hook(self):
        # Preserve the existing service/config/state, but use the new ordinary
        # message UI. Upsert only our lifecycle commands, preserving unrelated commands.
        guild, commands = self.define_commands()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://discord.com/api/v10/channels/{self.site['channel_id']}",
                headers={'Authorization': f'Bot {self.token}'}) as response:
                if response.status != 200:
                    raise RuntimeError(f'channel access HTTP {response.status}')
                channel = await response.json()
                if str(channel.get('guild_id')) != str(self.site['guild_id']):
                    raise RuntimeError('Configured channel does not belong to the configured server')
            url = f'https://discord.com/api/v10/applications/{self.application_id}/guilds/{guild.id}/commands'
            headers = {'Authorization': f'Bot {self.token}'}
            for command in commands:
                async with session.post(url, headers=headers, json=command.to_dict(self.tree)) as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f'command registration HTTP {response.status}')
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError('Cannot inspect previous commands')
                previous = await response.json()
            for command in previous:
                if (command.get('name') == 'msg'
                    and command.get('description') == 'Send a message to a development agent'
                    and [o.get('name') for o in command.get('options', [])] == ['agent', 'message']):
                    async with session.delete(url + '/' + command['id'], headers=headers) as response:
                        if response.status != 204:
                            raise RuntimeError('Cannot retire previous /msg command')
        self.worker = asyncio.create_task(self.pump())

    async def on_message(self, message):
        if not self._is_authorized_message(message):
            return
        async with self.delivery_lock:
            if message.id in self.seen:
                return
            self.seen.add(message.id)
            if len(self.seen) > 10000:
                self.seen = {message.id}
            try:
                await super().on_message(message)
            except OSError:
                await self._show_failure(message, ConnectorError(
                    'local storage', 'Local storage failed; delivery may be incomplete. Do not resend blindly.'))

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        await super().close()

    async def on_ready(self):
        address = os.environ.get('NOTIFY_SOCKET')
        if address:
            if address.startswith('@'):
                address = '\0' + address[1:]
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
                notify.connect(address)
                notify.sendall(b'READY=1\nSTATUS=Discord connected')
        print('DISCORD_CONNECTED', flush=True)

    async def post_record(self, record):
        sender = record['sender']
        # Identity files are root-owned; read the color on each post so newly
        # created agents need no connector restart or copied color registry.
        colors = {}
        identity = Path('/etc/freq-ai-setup/identities') / f'{sender}.conf'
        try:
            match = re.search(r"FREQ_USER_TRUECOLOR='([0-9]+);([0-9]+);([0-9]+)'",
                              identity.read_text())
            if match:
                rgb = tuple(map(int, match.groups()))
                if all(0 <= part <= 255 for part in rgb):
                    colors[sender] = rgb[0] << 16 | rgb[1] << 8 | rgb[2]
        except FileNotFoundError:
            pass
        embed = discord.Embed(title=f"{sender.upper()}-MSG: [{record['title']}]"[:256],
                              colour=color_for(sender, colors),
                              timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f'{sender} · agent reply')
        embed.description = record['message'] if len(record['message']) <= 4096 else 'Full reply attached.'
        payload = {'embeds': [embed.to_dict()], 'allowed_mentions': {'parse': [], 'replied_user': False}}
        kwargs = {'json': payload}
        if len(record['message']) > 4096:
            form = aiohttp.FormData()
            form.add_field('payload_json', json.dumps(payload))
            form.add_field('files[0]', record['message'].encode(),
                           filename=f'{sender}-reply.md', content_type='text/markdown')
            kwargs = {'data': form}
        # One HTTP attempt. Persist failure/uncertainty instead of blindly reposting.
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post(
                f"https://discord.com/api/v10/channels/{self.site['channel_id']}/messages",
                headers={'Authorization': f'Bot {self.token}'}, **kwargs) as response:
                if response.status != 200:
                    raise RuntimeError(f'Discord HTTP {response.status}')
                receipt = await response.json()
                if not receipt.get('id'):
                    raise RuntimeError('Discord omitted the message receipt')
                return str(receipt['id'])

    async def deliver(self, path):
        record, meta, digest = read_record(path, roster(self.site['coms_root']))
        previous = self.db.execute('SELECT digest,status FROM deliveries WHERE name=?', (path.name,)).fetchone()
        if previous:
            if previous != (digest, 'posted'):
                return
        else:
            self.db.execute('INSERT INTO deliveries VALUES (?,?,?)', (path.name, digest, 'attempted'))
            self.db.commit()
            # 'attempted' stays held after ambiguous HTTP/ACK failure, including
            # a successful remote post followed by local disk exhaustion.
            self.db.execute('INSERT OR REPLACE INTO delivery_receipts VALUES (?,?,?,?)',
                            (path.name, None, 'BEFORE_REMOTE_POST', datetime.now(timezone.utc).isoformat()))
            self.db.commit()
            remote_id = await self.post_record(record)
            self.db.execute('UPDATE deliveries SET status=? WHERE name=?', ('posted', path.name))
            self.db.execute('INSERT OR REPLACE INTO delivery_receipts VALUES (?,?,?,?)',
                            (path.name, remote_id, 'REMOTE_ID_RECORDED', datetime.now(timezone.utc).isoformat()))
            self.db.commit()
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (meta.st_dev, meta.st_ino, meta.st_mtime_ns, meta.st_size):
            raise ValueError('outbox record changed during delivery')
        # Retain the original envelope. The delivery ledger suppresses reposting.
        # An operator may later archive by identity; successful delivery is not
        # permission to delete unread/history or diagnostic evidence.

    async def pump(self):
        await self.wait_until_ready()
        while not self.is_closed():
            for path in sorted(Path(self.site['outbox']).glob('*.json')):
                if path.name in self.rejected:
                    continue
                if self.db.execute("SELECT 1 FROM deliveries WHERE name=? AND status='posted'",(path.name,)).fetchone():
                    continue
                try:
                    await self.deliver(path)
                except Exception as error:
                    self.rejected.add(path.name)
                    # Never log tokens, interaction payloads, or message contents.
                    print(f'OUTBOX_HELD file={path.name} boundary={type(error).__name__}', flush=True)
            await asyncio.sleep(2)


def main():
    config = json.loads(Path('/etc/freq-ai-setup/discord/config.json').read_text())
    credentials = Path(os.environ['CREDENTIALS_DIRECTORY'])
    token = (credentials / 'bot-token').read_text().strip()
    state = Path('/var/lib/freq-discord')
    lock = (state / 'connector.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    client = Connector(config, token, state)
    client.run(token, log_handler=SafeDiscordLog(), log_level=logging.WARNING)


if __name__ == '__main__':
    main()
