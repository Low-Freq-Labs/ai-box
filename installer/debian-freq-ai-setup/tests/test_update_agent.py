"""Agent update planning and runtime migration without accounts or live sessions."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import pwd
import tempfile
import unittest
import io
import sys
import subprocess
from contextlib import ExitStack,redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

loader=importlib.machinery.SourceFileLoader('update_agent',str(Path(__file__).resolve().parents[1]/'assets/update-agent'))
spec=importlib.util.spec_from_loader(loader.name,loader)
u=importlib.util.module_from_spec(spec)
loader.exec_module(u)


class UpdateAgentTests(unittest.TestCase):
    def fixture(self, root):
        home=root/'home'/'sample';operator=root/'operator';base=root/'config';skills=root/'skills'
        for directory in (home,operator,base/'agents.d',base/'identities',root/'bin'):
            directory.mkdir(parents=True)
        (base/'site.conf').write_text("FREQ_MASTER_USER='root'\n")
        (base/'coms.conf').write_text("FREQ_COMS_TMUX_DIR='/run/freq-agents/tmux'\n")
        (base/'agents.d/sample.conf').write_text("AGENT='sample'\nRUNTIME='codex'\nCOLOR='blue'\n")
        (base/'identities/sample.conf').write_text("export FREQ_USER_TRUECOLOR='56;189;248'\nexport FREQ_USER_256='45'\nexport FREQ_AGENT_RUNTIME='codex'\n")
        (home/'.tmux.conf').write_text('set-option -g @fq_colour "#38BDF8"\n# keep custom\n')
        for runtime,contract,conf in (('codex','AGENTS.md','config.toml'),('claude','CLAUDE.md','settings.json')):
            folder=home/('.'+runtime);folder.mkdir()
            (folder/contract).write_text('current roles' if runtime=='codex' else 'older target roles')
            (folder/conf).write_text('model="keep"' if runtime=='codex' else '{"env":{"custom":"keep"}}')
            (folder/'auth.json').write_text('fixture auth')
            (root/'bin'/runtime).write_text('fixture runtime')
        tools=operator/'agents/sample';tools.mkdir(parents=True)
        for action in ('start','connect','stop'):(tools/f'sample-{action}').write_text("readonly runtime='codex'\n# custom\n")
        for skill in u.SKILLS:
            folder=skills/skill;folder.mkdir(parents=True);(folder/'SKILL.md').write_text('skill '+skill)
        (skills/'watch-once/scripts').mkdir()
        (skills/'watch-once/scripts/watch_once.py').write_text('# watcher fixture')
        lock=root/'maintenance';lock.touch()
        stack=ExitStack()
        for key,value in dict(BASE=base,HOME_ROOT=root/'home',BACKUPS=root/'backups',MAINTENANCE=lock,
                              BIN_ROOT=root/'bin',SKILL_ROOT=skills).items():
            stack.enter_context(patch.object(u,key,value))
        stack.enter_context(patch.object(u.pwd,'getpwnam',side_effect=lambda name:SimpleNamespace(
            pw_uid=os.getuid(),pw_gid=os.getgid(),pw_dir=str(operator if name=='root' else home))))
        stack.enter_context(patch.object(u,'tmux',return_value=subprocess.CompletedProcess([],1)))
        stack.enter_context(patch.object(u.subprocess,'run',return_value=subprocess.CompletedProcess([],1)))
        stack.enter_context(patch.object(u.sys.stdin,'isatty',return_value=True))
        return stack,home,base

    def test_interactive_changes_both_fields_and_preserves_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stack,home,base=self.fixture(root)
            with stack,patch.object(sys,'argv',['update-agent','sample']), \
                    patch('builtins.input',side_effect=['purple','claude','yes']) as prompts,redirect_stdout(io.StringIO()):
                u.main()
            self.assertEqual(prompts.call_count,3)
            self.assertIn("RUNTIME='claude'",(base/'agents.d/sample.conf').read_text())
            self.assertIn("COLOR='purple'",(base/'agents.d/sample.conf').read_text())
            self.assertEqual((home/'.claude/CLAUDE.md').read_text(),'current roles')
            self.assertEqual((home/'.claude/auth.json').read_text(),'fixture auth')
            self.assertEqual((home/'.codex/auth.json').read_text(),'fixture auth')
            self.assertTrue(list((root/'backups').glob('*/manifest.json')))

    def test_running_agent_cannot_be_updated_even_with_yes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stack,home,base=self.fixture(root)
            with stack,patch.object(sys,'argv',['update-agent','sample','--color','purple','--yes']), \
                    patch.object(u.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaisesRegex(ValueError,'fully stopped'):u.main()
            self.assertIn("COLOR='blue'",(base/'agents.d/sample.conf').read_text())
            self.assertFalse((root/'backups').exists())

    def test_interactive_cancel_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stack,home,base=self.fixture(root)
            with stack,patch.object(sys,'argv',['update-agent','sample']), \
                    patch('builtins.input',side_effect=['purple','','no']),redirect_stdout(io.StringIO()):
                u.main()
            self.assertIn("COLOR='blue'",(base/'agents.d/sample.conf').read_text())
            self.assertFalse((root/'backups').exists())

    def test_write_failure_restores_already_changed_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stack,home,base=self.fixture(root)
            before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            real=u.replace_file
            calls=[]
            def fail_second(*args):
                calls.append(args[0])
                if len(calls)==2:raise OSError('injected write failure')
                return real(*args)
            with stack,patch.object(sys,'argv',['update-agent','sample','--color','purple','--yes']), \
                    patch.object(u,'replace_file',side_effect=fail_second),redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError):u.main()
            self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file() and 'backups' not in p.parts})

    def test_color_names_and_custom_palette(self):
        self.assertEqual(u.colour('purple'),('#A855F7','168;85;247','141'))
        self.assertEqual(u.colour('toxic-green'),('#39FF14','57;255;20','82'))
        self.assertEqual(u.colour('#39ff14'),u.colour('toxic-green'))
        for bad in ('red;id','#000000;id','$(id)','../red','bad','12345'):
            with self.assertRaises(ValueError):u.colour(bad)

    def test_single_color_line_preserves_other_customizations(self):
        text='set-option -g @fq_colour "#112233"\n# Custom bindings\nbind x display-message safe\n'
        after=u.replace_one(text,r'^set-option -g @fq_colour .+$','set-option -g @fq_colour "#39FF14"')
        self.assertEqual(after.splitlines()[1:],text.splitlines()[1:])
        with self.assertRaises(ValueError):u.replace_one(text+text,r'^set-option -g @fq_colour .+$','x')

    def test_linked_files_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'target').write_text('test');(root/'link').symlink_to(root/'target')
            with self.assertRaises(OSError):u.read_owned(root/'link',os.getuid())
            os.link(root/'target',root/'hard')
            with self.assertRaises(ValueError):u.read_owned(root/'hard',os.getuid())

    def test_runtime_carries_current_roles_and_preserves_both_auth_configs(self):
        for old,new in (('codex','claude'),('claude','codex')):
            with self.subTest(direction=(old,new)),tempfile.TemporaryDirectory() as d:
                root=Path(d);home=root/'agent';operator=root/'operator';skills=root/'skills'
                for runtime,filename in (('codex','AGENTS.md'),('claude','CLAUDE.md')):
                    folder=home/('.'+runtime);folder.mkdir(parents=True)
                    (folder/filename).write_text(f'Role and team from {runtime}')
                    (folder/('config.toml' if runtime=='codex' else 'settings.json')).write_text('model="existing"' if runtime=='codex' else '{"env":{"custom":"keep"}}')
                    (folder/'auth.json').write_text('fixture auth sentinel')
                tools=operator/'agents/agent';tools.mkdir(parents=True)
                for action in ('start','connect','stop'):
                    (tools/f'agent-{action}').write_text(f"readonly runtime='{old}'\n# custom launcher\n")
                for skill in u.SKILLS:
                    folder=skills/skill;folder.mkdir(parents=True);(folder/'SKILL.md').write_text('shared '+skill)
                (skills/'watch-once/scripts').mkdir()
                (skills/'watch-once/scripts/watch_once.py').write_text('# watcher fixture')
                custom=home/('.'+new)/'skills/dev-msg';custom.mkdir(parents=True)
                (custom/'SKILL.md').write_text('custom target skill')
                before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with patch.object(u,'SKILL_ROOT',skills):
                    plan=u.runtime_files(home,operator,pwd.getpwuid(os.getuid()).pw_name,'agent',old,new,os.getuid(),os.getgid())
                self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
                contract='AGENTS.md' if new=='codex' else 'CLAUDE.md'
                planned={str(p):after for p,_,after,_ in plan}
                self.assertEqual(planned[str(home/('.'+new)/contract)],f'Role and team from {old}'.encode())
                self.assertNotIn(str(custom/'SKILL.md'),planned)
                self.assertFalse(any(p.endswith(('config.toml','settings.json','auth.json')) for p in planned))
                for action in ('start','connect','stop'):
                    self.assertEqual(planned[str(tools/f'agent-{action}')],f"readonly runtime='{new}'\n# custom launcher\n".encode())


if __name__=='__main__':unittest.main()
