#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2017 Cisco Systems
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

import dmidecode

DOCUMENTATION = '''
---
module: dmidecode
short_description: adds dmidecode facts to ansible_facts
description:
    - Adds dmidecode facts to ansible facts
version_added: "1.0"
author: Wei Tie
notes: None
requirements:
    - dmidecode package must be installed
    - python-dmidecode must be installed
'''

EXAMPLES = '''
# Capture information about dmidecode to populate facts
- name: Capturing facts with dmidecode module
  dmidecode: gather_facts=yes

# Capture information about dmidecode for specified type
- name: Capture information about dmidecode for specified type
  dmidecode: gather_facts=no  type=system
'''


def readable(o):
    """
    Convert a combination of dict, list, str to a readable alternitive object.
    """
    if isinstance(o, list):
        return map(readable, o)
    if isinstance(o, dict):
        readable_d = {}
        for k, v in o.iteritems():
            key = k.lower().replace(" ", "_")
            value = readable(v)
            readable_d[key] = value
        return readable_d
    return str(o)


def flatten(l):
    """Make a list of dict with unique keys into one dict."""
    if not isinstance(l, list):
        return l
    flat = {}
    for d in l:
        flat.update(d)
    return flat


def module_exit(module, data):
    """Exit module with given data."""
    dmi_data = {"dmidecode": data}
    if module.params['gather_facts'] is True:
        module.exit_json(changed=False, ansible_facts=dmi_data)
    else:
        module.exit_json(changed=False, dmidecode_facts=dmi_data)


def main():
    dmi_types = ["bios", "system", "baseboard", "chassis", "processor",
                 "memory", "cache", "connector", "slot"]

    module = AnsibleModule(argument_spec=dict(
        type=dict(required=False, choices=dmi_types),
        gather_facts=dict(default=True, type='bool'),
        raw=dict(default=False, type='bool')),
                           supports_check_mode=True)

    if module.params['type'] is not None:
        type = module.params['type']
        raw_dmi_data = {type: getattr(dmidecode, type)()}
    else:
        raw_dmi_data = dict((type, getattr(dmidecode, type)())
                            for type in dmi_types)

    if module.params['raw'] is True:
        module_exit(module, raw_dmi_data)
    else:
        dmi_data = {}
        for type, raw_data in raw_dmi_data.iteritems():
            readable_data = []
            for raw in raw_data.itervalues():
                readable_data.append(readable(raw['data']))
            if type in ('baseboard', 'bios', 'system', 'chassis'):
                dmi_data[type] = flatten(readable_data)
            else:
                dmi_data[type] = readable_data

        module_exit(module, dmi_data)

# import module snippets
from ansible.module_utils.basic import *

if __name__ == '__main__':
    main()
