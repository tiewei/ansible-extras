#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2015 Cisco Systems
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import glob
import os

DOCUMENTATION = '''
---
module: network_facts
short_description: Collect extra network facts on Linux
description: Collect extra network facts on Linux
version_added: "1.9"
options:
  resource:
    description:
      - Network extra facts target
    choices: ['all', 'interfaces']
    required: False
  as_fact:
    description:
      - Add to ansible facts if it's True
      - Or it will return in "network_facts"
    required: False

'''

EXAMPLES = '''
# Use this module to add to Ansible facts

- name: Collect network interfaces facts and add to facts
  network_facts: resource=interfaces

- name: Collect network interfaces details in return message
  network_facts: resource=interfaces as_fact=False

'''


class NetworkExtraFacts(object):
    """NetworkExtraFacts is a collector of extra network facts."""

    SUPPORTED_RESOURCES = ['interfaces']
    LINUX_VIRTUAL_DEV = "/sys/devices/virtual/net/%s"

    def _get_file_content(self, path, default=None, strip=True):
        data = default
        if os.path.exists(path) and os.access(path, os.R_OK):
            try:
                datafile = open(path)
                data = datafile.read()
                if strip:
                    data = data.strip()
                if len(data) == 0:
                    data = default
            except IOError:
                # if it's readable and existed, but still throws io error
                # it could because system doesn't support it
                # e.g. speed for para-virtualized device
                pass
            finally:
                datafile.close()
        return data

    def _get_macaddress(self, interface, path):
        if os.path.exists(os.path.join(path, 'address')):
            macaddress = self._get_file_content(
                os.path.join(path, 'address'),
                default='')
            if macaddress and macaddress != '00:00:00:00:00:00':
                interface['macaddress'] = macaddress
            if 'hwaddr' not in interface:
                interface['hwaddr'] = macaddress

    def _get_mtu(self, interface, path):
        if os.path.exists(os.path.join(path, 'mtu')):
            interface['mtu'] = int(self._get_file_content(os.path.join(path,
                                                                       'mtu')))

    def _get_operstate(self, interface, path):
        if os.path.exists(os.path.join(path, 'operstate')):
            interface['active'] = self._get_file_content(os.path.join(
                path, 'operstate')) != 'down'

    def _get_module(self, interface, path):
        if os.path.exists(os.path.join(path, 'device', 'driver', 'module')):
            interface['module'] = os.path.basename(os.path.realpath(
                os.path.join(path, 'device', 'driver', 'module')))

    def _get_type(self, interface, path):
        if os.path.exists(os.path.join(path, 'type')):
            _type = self._get_file_content(os.path.join(path, 'type'))
            if _type == '1':
                interface['type'] = 'ether'
            elif _type == '512':
                interface['type'] = 'ppp'
            elif _type == '772':
                interface['type'] = 'loopback'
            else:
                interface['type'] = _type
            interface['type_raw'] = _type
        if os.path.exists(os.path.join(path, 'bonding')):
            interface['type'] = 'bonding'
        if os.path.exists(os.path.join(path, 'bridge')):
            interface['type'] = 'bridge'

    def _get_bridge_facts(self, interface, path):
        if os.path.exists(os.path.join(path, 'bridge')):
            interface['interfaces'] = [
                os.path.basename(b)
                for b in glob.glob(os.path.join(path, 'brif', '*'))
            ]
            if os.path.exists(os.path.join(path, 'bridge', 'bridge_id')):
                interface['id'] = self._get_file_content(
                    os.path.join(path, 'bridge', 'bridge_id'),
                    default='')
            if os.path.exists(os.path.join(path, 'bridge', 'stp_state')):
                interface['stp'] = self._get_file_content(os.path.join(
                    path, 'bridge', 'stp_state')) == '1'

    def _get_bonding_facts(self, interface, path):
        if os.path.exists(os.path.join(path, 'bonding')):
            interface['slaves'] = self._get_file_content(
                os.path.join(path, 'bonding', 'slaves'),
                default='').split()
            interface['mode'] = self._get_file_content(
                os.path.join(path, 'bonding', 'mode'),
                default='').split()[0]
            interface['miimon'] = self._get_file_content(
                os.path.join(path, 'bonding', 'miimon'),
                default='').split()[0]
            interface['lacp_rate'] = self._get_file_content(
                os.path.join(path, 'bonding', 'lacp_rate'),
                default='').split()[0]
            primary = self._get_file_content(os.path.join(path, 'bonding',
                                                          'primary'))
            if primary:
                interface['primary'] = primary
                slaves = os.path.join(path, 'bonding', 'all_slaves_active')
                if os.path.exists(slaves):
                    interface['all_slaves_active'] = (
                        self._get_file_content(slaves) == '1')

    def _get_is_promisc_mode(self, interface, path):
        # Check whether an interface is in promiscuous mode
        if os.path.exists(os.path.join(path, 'flags')):
            promisc_mode = False
            # The 9th lsb bit (of a 2 byte field) indicates whether the
            # interface is in promiscuous mode, see
            # /include/uapi/linux/if.h
            # 1 = promisc
            # 0 = no promisc
            data = int(self._get_file_content(os.path.join(path, 'flags')), 16)
            promisc_mode = (data & 0x0100 > 0)
            interface['promisc'] = promisc_mode

    def _get_is_virtual_device(self, interface, path):
        device = os.path.basename(path)
        real_path = os.path.realpath(path)
        interface['virtual'] = real_path == self.LINUX_VIRTUAL_DEV % device

    def _get_speed(self, interface, path):
        if os.path.exists(os.path.join(path, 'speed')):
            interface['speed'] = self._get_file_content(
                os.path.join(path, 'speed'),
                default=-1)

    def _get_dev_id(self, interface, path):
        if os.path.exists(os.path.join(path, 'dev_id')):
            interface['dev_id'] = self._get_file_content(os.path.join(
                path, 'dev_id'))

    def _get_bonding_slave_facts(self, interface, path):
        if os.path.exists(os.path.join(path, 'bonding_slave')):
            interface['hwaddr'] = self._get_file_content(os.path.join(
                path, 'bonding_slave', 'perm_hwaddr'))
            interface['bonding_state'] = self._get_file_content(os.path.join(
                path, 'bonding_slave', 'state'))

    def _get_udev_name(self, interface, path):
        if os.path.exists(os.path.join(path, 'device')):
            device_path = os.path.join(path, 'device')
            interface['udev_name'] = os.path.basename(os.path.realpath(
                device_path))

    def collect_interfaces_facts(self):
        """Collect facts for interfaces."""
        interface_facts = []
        for path in glob.glob('/sys/class/net/*'):
            if not os.path.isdir(path):
                continue
            interface = {}
            device = os.path.basename(path)
            interface['name'] = device
            self._get_macaddress(interface, path)
            self._get_mtu(interface, path)
            self._get_operstate(interface, path)
            self._get_module(interface, path)
            self._get_type(interface, path)
            if interface['type'] == 'bridge':
                self._get_bridge_facts(interface, path)
            if interface['type'] == 'bonding':
                self._get_bonding_facts(interface, path)
            self._get_is_promisc_mode(interface, path)
            self._get_is_virtual_device(interface, path)
            self._get_speed(interface, path)
            self._get_dev_id(interface, path)
            self._get_bonding_slave_facts(interface, path)
            self._get_udev_name(interface, path)

            interface_facts.append(interface)

        return interface_facts


def collect_fact(module):
    """Collect extra network facts."""
    resource = module.params['resource']
    if resource == 'all':
        to_collect = NetworkExtraFacts.SUPPORTED_RESOURCES
    else:
        to_collect = [resource]
    facts = {}
    net_facts = NetworkExtraFacts()
    for target in to_collect:
        facts[target] = getattr(net_facts, "collect_%s_facts" % target)()
    return facts


def main():
    module = AnsibleModule(argument_spec=dict(resource=dict(
        required=False,
        default='all',
        choices=NetworkExtraFacts.SUPPORTED_RESOURCES + ['all']),
                                              as_fact=dict(required=False,
                                                           type='bool',
                                                           default=True)))

    network_facts = {"network_facts": collect_fact(module)}

    exit_json = {"changed": False}
    if module.params['as_fact']:
        exit_json['ansible_facts'] = network_facts
    else:
        exit_json.update(network_facts)

    module.exit_json(**exit_json)

# import module snippets
from ansible.module_utils.basic import *
if __name__ == '__main__':
    main()
