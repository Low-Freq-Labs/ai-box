#!/usr/bin/python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('network_file', Path(__file__).with_name('network_file.py'))
n = importlib.util.module_from_spec(spec); spec.loader.exec_module(n)
BASE = '''source /etc/network/interfaces.d/*
auto lo
iface lo inet loopback
allow-hotplug ens18
iface ens18 inet static
    address 10.25.255.2/24
    mtu 9000
    up ip route replace 10.25.0.0/16 via 10.25.255.1
'''


class NetworkFileTests(unittest.TestCase):
    def test_current_style_and_normal_network_settings(self):
        result = n.validate(BASE + '    gateway 10.25.255.1\n    dns-nameservers 1.1.1.1 8.8.8.8\n    dns-search example.test\n')
        self.assertIn(('ens18','inet'), result)

    def test_shell_hooks_and_substitution_rejected(self):
        for command in ('up touch /home/clancy/owned', 'up /bin/bash -c id',
                        'up ip route replace default via 1.1.1.1; id',
                        'up ip route replace default via $(id)',
                        'pre-up cp /etc/shadow /mnt/nexus/leak',
                        'address 1.1.1.1`id`', 'dns-search x;id',
                        'up ip route replace default via 1.1.1.1 & id'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                n.validate(BASE + '    ' + command + '\n')

    def test_arbitrary_includes_and_mapping_not_accepted(self):
        for line in ('source /home/jarvis/network/*', 'source /mnt/nexus/net',
                     'source-directory /tmp', 'mapping ens18', 'script /home/jarvis/up'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                n.validate(BASE + line + '\n')

    def test_bad_addresses_and_interfaces_rejected(self):
        for line in ('address not-an-address','gateway 1.1.1.999','mtu 1','bridge_ports /home/clancy',
                     'dns-nameservers 1.1.1.1 extra','hwaddress ether aa:bb', 'up ip route add default via 1.1.1.1 table /tmp/x'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                n.validate(BASE + '    ' + line + '\n')

    def test_duplicate_stanzas_and_loopback_changes_rejected(self):
        with self.assertRaises(ValueError):
            n.validate(BASE + 'iface ens18 inet dhcp\n')
        with self.assertRaises(ValueError):
            n.validate(BASE.replace('iface lo inet loopback','iface lo inet static'))

    def test_ipv6_vlan_bridge_and_route_settings(self):
        n.validate(BASE + '''iface ens18 inet6 static
    address fd00::2/64
    gateway fd00::1
iface ens18.20 inet manual
    vlan-raw-device ens18
    vlan-id 20
iface br0 inet static
    address 10.50.0.1/24
    bridge_ports ens18.20
    bridge_stp off
    bridge_fd 0
    post-up ip -6 route replace fd10::/64 via fd00::1 dev ens18 metric 100
''')

    def test_oversize_and_control_characters_rejected(self):
        for content in (BASE + '# ' + 'x'*32768, BASE + '\x1b[2J', ''):
            with self.assertRaises(ValueError):
                n.validate(content)


if __name__ == '__main__':
    unittest.main()
