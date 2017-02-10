# -*- coding: utf-8 -*-
# (c) 2014, Craig Tracey <craigtracey@gmail.com>
# (c) 2015, John Dewey <john@dewey.ws>
# (c) 2016, Wei Tie <nuaafe@gmail.com>

# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

import collections
import glob
import os
import yaml

from ansible.constants import DEFAULTS
from ansible.constants import get_config
from ansible.constants import load_config_file
from ansible.template import Templar


def deep_update_dict(d, u):
    for k, v in u.iteritems():
        if isinstance(v, collections.Mapping):
            r = deep_update_dict(d.get(k, {}), v)
            d[k] = r
        if isinstance(v, list):
            if d.get(k):
                d[k].extend(v)
        else:
            d[k] = u[k]
    return d


class VarsModule(object):
    """
    A vars plugin which loads a set of defaults variables from a directory.
    Ansible variables are deep-merged ontop of the defaults.
    """

    def __init__(self, inventory):
        self.inventory = inventory
        self.inventory_basedir = inventory.basedir()

        p, _ = load_config_file()
        self.pre_template_enabled = get_config(
            p, DEFAULTS, 'var_pre_template',
            'ANSIBLE_VAR_PRE_TEMPLATE', False, boolean=True)
        self.defaults_glob = get_config(
            p, DEFAULTS, 'var_defaults_glob',
            'ANSIBLE_VAR_DEFAULTS_GLOB', None)
        self._templar = None

    def _get_defaults(self):
        """
        Load the yaml files lexicographical order, and return a dict.
        """
        content = str()
        filenames = glob.glob(os.path.join(self.defaults_glob))
        for filename in filenames:
            with open(filename, 'r') as f:
                for line in f:
                    # skip yaml document headers
                    if "---" not in line:
                        content += line

        return yaml.load(content)

    def pre_template(self, variables):
        """
        Template inventory before run into playbooks
        """
        if self._templar is None:
            self._templar = Templar(self.inventory._loader,
                                    variables=variables)
        if isinstance(variables, collections.Mapping):
            return dict(map(
                lambda (k, v): (k, self.pre_template(v)),
                variables.iteritems()))
        if isinstance(variables, list):
            return map(self.pre_template, variables)
        return self._templar.template(variables, fail_on_undefined=False)

    def run(self, host, vault_password=None):
        default_vars = self._get_defaults()
        # This call to the variable_manager will get the variables of
        # a given host, with the variable precedence already sorted out.
        # This references some "private" like objects and may need to be
        # adjusted in the future if/when this all gets overhauled.
        # See also https://github.com/ansible/ansible/pull/17067
        inv_vars = self.inventory._variable_manager.get_vars(
            loader=self.inventory._loader, host=host)
        if default_vars:
            inv_vars = deep_update_dict(default_vars, inv_vars)
        if self.pre_template_enabled:
            inv_vars = self.pre_template(inv_vars)
        return inv_vars
