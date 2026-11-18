#!/usr/bin/python3
"""Authorization, ownership, injection and rollback tests; no host mutations."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('broker', Path(__file__).with_name('broker.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.state = {'sources': {}, 'grants': {}, 'mounts': {}, 'routes': {}, 'pending': None}
        self.patches = [patch.object(b, 'load', side_effect=lambda: copy.deepcopy(self.state)),
                        patch.object(b, 'save', side_effect=self.save),
                        patch.object(b, 'agents', return_value=['jarvis', 'clancy']),
                        patch.object(b, 'operator', side_effect=lambda uid: uid == 0),
                        patch.object(b.pwd, 'getpwuid', side_effect=lambda uid: type('Account', (), {'pw_name': {0:'root', 1001:'jarvis', 1002:'clancy', 1003:'stranger', 1004:'freq-alerts'}[uid]})()),
                        patch.object(b.pwd, 'getpwnam', side_effect=lambda who: type('Account', (), {'pw_uid': {'root':0,'jarvis':1001,'clancy':1002,'stranger':1003,'freq-alerts':1004}[who]})()),
                        patch.object(b, 'keys'), patch.object(b, 'public_key', side_effect=lambda value: value)]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def save(self, value):
        self.state = copy.deepcopy(value)

    def add(self, uid=1001, source='plex', key='public-plex'):
        return b.handle(uid, {'area':'alerts', 'action':'add', 'source':source, 'label':'PLEX-WATCHDOG', 'recipient':'jarvis', 'key':key})

    def test_only_operator_can_grant_and_revocation_is_immediate(self):
        request = {'area':'admin', 'action':'grant', 'agent':'jarvis', 'capabilities':['smb']}
        with self.assertRaisesRegex(ValueError, 'only the operator'):
            b.handle(1001, request)
        b.handle(0, request)
        with patch.object(b, 'smb', return_value='mounted') as mount:
            self.assertEqual(b.handle(1001, {'area':'host', 'action':'smb', 'verb':'show'}), 'mounted')
            b.handle(0, dict(request, action='revoke'))
            with self.assertRaisesRegex(ValueError, 'not granted'):
                b.handle(1001, {'area':'host', 'action':'smb', 'verb':'show'})
            self.assertEqual(mount.call_count, 1)

    def test_every_agent_can_create_but_not_change_peer_source(self):
        self.add()
        self.add(1002, 'caddy', 'public-caddy')
        for action in ('disable', 'remove', 'enable'):
            with self.assertRaisesRegex(ValueError, 'owned by another'):
                b.handle(1002, {'area':'alerts', 'action':action, 'source':'plex'})
        result = json.loads(b.handle(1002, {'area':'alerts', 'action':'show'}))
        self.assertEqual(list(result), ['caddy'])

    def test_unknown_users_cannot_register_or_manage(self):
        with self.assertRaisesRegex(ValueError, 'registered agent'):
            self.add(1003)

    def test_no_duplicate_keys_across_sources(self):
        self.add()
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            self.add(1002, 'other')

    def test_ssh_ingress_requires_correct_uid_and_bound_token(self):
        self.add()
        token = self.state['sources']['plex']['token']
        request = {'area':'ingress', 'token':token, 'body':'offline'}
        with patch.object(b, 'deliver', return_value='sent') as send:
            self.assertEqual(b.handle(1004, request), 'sent')
            self.assertEqual(send.call_args.args[0], 'plex')
            for uid in (0,1001,1002,1003):
                with self.assertRaises(ValueError):
                    b.handle(uid, request)
            with self.assertRaises(ValueError):
                b.handle(1004, dict(request, token='bogus'))

    def test_disable_and_key_rotation_invalidate_existing_ingress(self):
        self.add()
        old = self.state['sources']['plex']['token']
        b.handle(1001, {'area':'alerts','action':'key','source':'plex','key':'new'})
        with self.assertRaises(ValueError):
            b.handle(1004, {'area':'ingress','token':old,'body':'offline'})
        b.handle(1001, {'area':'alerts','action':'disable','source':'plex'})
        with self.assertRaisesRegex(ValueError, 'disabled'):
            b.handle(1001, {'area':'alerts','action':'send','source':'plex','body':'offline'})

    def test_extra_fields_cannot_select_arbitrary_command_or_file(self):
        for key in ('command', 'path', 'uid', 'owner'):
            with self.assertRaisesRegex(ValueError, 'fields'):
                b.handle(0, {'area':'admin','action':'show',key:'/home/clancy'})

    def test_reject_label_control_sequences_and_identity_spoofing(self):
        for value in ('SONNY-MSG','JARVIS-MSG','bad\nlabel','X\x1b[2J','$(id)','X:','a'*49):
            with self.assertRaises(ValueError):
                b.label(value, ['jarvis'])
        self.assertEqual(b.label('SSL-RENEWAL', []), 'SSL-RENEWAL')

    def test_mount_paths_and_options_are_closed(self):
        for value in ('../jarvis','/home/jarvis','x/y','x;id','c','wsl'):
            with self.assertRaises(ValueError):
                b.mount_name(value)
        for value in ('//server/share,exec','//server/../root','/home/jarvis','//server/share\nOptions=exec','//server/%h','//server/share;id'):
            with self.assertRaises(ValueError):
                b.share(value)
        self.assertEqual(b.share('//10.25.25.25/smb-share/Nexus'), '//10.25.25.25/smb-share/Nexus')
        self.assertEqual(b.mount_unit('team-share'), 'mnt-team\\x2dshare.mount')

    def test_unmanaged_mount_cannot_be_removed(self):
        with patch.object(b, 'mount_path', return_value=Path('/mnt/nexus')):
            with self.assertRaisesRegex(ValueError, 'only mounts created'):
                b.smb(self.state, {'area':'host','action':'smb','verb':'remove','name':'nexus'})

    def test_unapproved_services_and_private_paths_rejected(self):
        for value in ('ssh.service','freq-container@clancy.service','/home/clancy','../evil','x;id'):
            with self.assertRaises(ValueError):
                b.handle(0, {'area':'host','action':'services','verb':'restart','unit':value})

    def test_default_route_and_shell_injection_rejected(self):
        request = {'name':'lab','destination':'10.50.0.0/24','gateway':'10.25.255.1','interface':'ens18'}
        for field, value in (('destination','0.0.0.0/0'),('destination','10.50.0.1/24'),('gateway','1.1.1.1;id'),('interface','ens18;id')):
            with self.assertRaises(ValueError):
                b.route_values(dict(request, **{field:value}))
        self.assertEqual(b.route_values(request)['interface'], 'ens18')

    def test_existing_host_route_is_never_replaced(self):
        with patch.object(b, 'run', return_value='[{"dst":"10.50.0.0/24"}]') as run:
            with self.assertRaisesRegex(ValueError, 'already has'):
                b.network(self.state, {'area':'host','action':'network','verb':'route-add','name':'lab','destination':'10.50.0.0/24','gateway':'10.25.255.1','interface':'ens18'}, 'jarvis')
            self.assertEqual(run.call_count,1)

    def test_route_timer_precedes_mutation_and_confirmation_is_owner_bound(self):
        with patch.object(b, 'run', return_value='[]') as run:
            b.network(self.state, {'area':'host','action':'network','verb':'route-add','name':'lab','destination':'10.50.0.0/24','gateway':'10.25.255.1','interface':'ens18'}, 'jarvis')
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(calls[1][0], '/usr/bin/systemd-run')
            self.assertEqual(calls[2][3], 'add')
            token = self.state['pending']['token']
            with self.assertRaisesRegex(ValueError, 'owned by this caller'):
                b.network(self.state, {'area':'host','action':'network','verb':'confirm','token':token}, 'clancy')
            b.network(self.state, {'area':'host','action':'network','verb':'confirm','token':token}, 'jarvis')
            self.assertIn('lab', self.state['routes'])
            self.assertIsNone(self.state['pending'])

    def test_rollback_removes_only_its_exact_managed_route(self):
        entry = {'destination':'10.50.0.0/24','gateway':'10.25.255.1','interface':'ens18'}
        self.state['pending'] = {'token':'abc','verb':'route-add','entry':entry}
        rows = [{'dst':entry['destination'], 'gateway':entry['gateway'], 'dev':entry['interface'], 'metric':42700, 'protocol':186}]
        with patch.object(b, 'run', return_value=json.dumps(rows)) as run:
            b.rollback(self.state, 'wrong')
            run.assert_not_called()
            b.rollback(self.state, 'abc')
            self.assertEqual(run.call_args.args[0], b.route_command('del',entry))
            self.assertIsNone(self.state['pending'])


if __name__ == '__main__':
    unittest.main()
