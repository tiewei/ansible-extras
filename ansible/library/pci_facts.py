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

from subprocess import PIPE
from subprocess import Popen

DOCUMENTATION = '''
---
module: pci_facts
short_description: adds lspci facts to ansible_facts
description:
    - Adds pci devices info to ansible facts
version_added: "1.0"
author: Wei Tie
notes: None
requirements:
    - pciutil package must be installed
'''

EXAMPLES = '''
# Capture information about pci_facts to populate facts
- name: Capturing facts with pci_facts module
  pci_facts: gather_facts=yes

# Capture information for specified device_id
- name: Capturing facts with pci_facts module
  pci_facts: gather_facts=no device_id="0e:00.1"
'''


def collect_pci_info():
    """Gather pci devices from lspci."""
    proc = Popen(['/usr/sbin/lspci', '-D', '-vmm'], stdout=PIPE)
    pci_devices = {}
    for line in proc.stdout:
        if len(line.strip()) == 0:
            continue
        k, v = map(lambda x: x.strip(), line.split(":", 1))
        if k == 'Slot':
            slot = v
            pci_devices[slot] = {"slot": slot}
        elif k in ('Class', 'Vendor', 'Device'):
            pci_devices[slot][k.lower()] = v
        else:
            continue
    return pci_devices


def pci_facts(module):
    """Collect pci facts from lspci command."""
    ansible_facts = {'pci_facts': {}}

    device_id = module.params['device_id']
    all_pci = collect_pci_info()

    if device_id is not None:
        if device_id in all_pci:
            ansible_facts['pci_facts'][device_id] = all_pci[device_id]
        elif ("0000:%s" % device_id) in all_pci:
            device_id = "0000:%s" % device_id
            ansible_facts['pci_facts'][device_id] = all_pci[device_id]
        else:
            module.fail_json(msg="Can't find PCI device %s" % device_id)
    else:
        ansible_facts['pci_facts'] = all_pci

    if module.params['gather_facts'] is True:
        module.exit_json(changed=False, ansible_facts=ansible_facts)
    else:
        module.exit_json(changed=False, pci_facts=ansible_facts)


def main():
    module = AnsibleModule(argument_spec=dict(device_id=dict(required=False,
                                                             type='str'),
                                              gather_facts=dict(required=False,
                                                                default=True,
                                                                type='bool')),
                           supports_check_mode=True)

    pci_facts(module)

# import module snippets
from ansible.module_utils.basic import *
main()
