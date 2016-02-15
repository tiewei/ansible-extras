# Copyright (c) 2016 Cisco Systems
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

from ansible import errors
from ansible import utils
from collections import deque
import yaml

try:
    basestring
except NameError:
    basestring = str


class LookupModule(object):
    '''
    Look up values in a YAML file by the key.

    This lookup module allows you get a value from YAML file without loading it
    into context (vs. include_vars).

    NOTE: With inline lookup, the value of the key has to be a string, unless
    set wantlist=True since 1.9.
    Also See:
    https://github.com/ansible/ansible/blob/stable-1.9/lib/ansible/utils/template.py#L106

        e.g /path/to/yaml/file
        ---
        foo: foo_value
        users:
          user_one: Jim
          user_two: Tom

        With inline lookup, the value of the key has to be a string

        1. lookup('yaml_file', '/path/to/yaml/file key=/foo')
           returns foo_value

        2. lookup('yaml_file', '/path/to/yaml/file key=/users/user_one')
           returns Jim

        3. lookup('yaml_file', '/path/to/yaml/file key=/bar default=bar_value')
           returns bar_value

        4. lookup('yaml_file', '/path/to/yaml/file key=/users' wantlist=True)
           returns [{"user_one": "Jim"}, {'user_two': "Tom"}]

        5. with_yaml_file:
             - "/path/to/yaml/file key=users"

           returns [{"user_one": "Jim"}, {'user_two': "Tom"}]
    '''

    def __init__(self, basedir=None, **kwargs):
        self.basedir = basedir

    def read_yaml(self, filename, key=None, default=None):
        """
        Find key's value from a yaml file, if not found, return default value
        key describled as in pseudo abs file path format.
        """

        if key is None or key.strip() == '':
            # return None if no key given
            return None

        try:
            with open(filename) as yaml_f:
                yaml_data = yaml.safe_load(yaml_f.read())
        except IOError as e:
            raise errors.AnsibleError("yaml_file: %s" % e)

        if key.strip() == '/':
            # return all data if key == '/'
            return yaml_data
        else:
            # build key_path queue, ensure no space in the path
            key_path = deque([path.strip() for path in key.strip().split("/")
                             if path.strip() != ''])
            value = self._find_value(key_path, yaml_data, default)
            return value

    def _find_value(self, key_path, value_dict, default):
        """
        Recursively walk through the key_path to find value from value_dict.

        :param key_path: A deque of path parts
        :param value_dict: Dict generated from reading the yaml data
        :param default: default return value if path is not found
        """
        # If no key left, return current value_dict
        if len(key_path) == 0:
            return value_dict
        key = key_path.popleft()
        if not isinstance(value_dict, dict) or key not in value_dict:
            # If value_dict is plain or key not found in value_dict,
            # return default
            return default
        else:
            # else go deeper
            return self._find_value(key_path, value_dict[key], default)

    def _build_params(self, passed_in):
        """
        Build vaild paramerters for finding value from yaml file
        """
        allowed_params = ['key', 'default']
        paramvals = {}
        for param in passed_in:
            name, value = param.split('=')
            if name in allowed_params:
                paramvals[name] = value
        return paramvals

    def run(self, terms, inject=None, **kwargs):
        """
        Implements LookupModule run method.
        """
        # flatten the terms if it's passed from with_yaml_file syntax
        terms = utils.listify_lookup_plugin_terms(terms, self.basedir, inject)
        ret = []
        # Check if it's basestring as ansible 1.9 supports badly on unicode
        if isinstance(terms, basestring):
            terms = [terms]

        for term in terms:
            params = term.split()
            yaml_file = params[0]
            paramvals = self._build_params(params[1:])

            # make relative paths to absoluate path
            path = utils.path_dwim(self.basedir, yaml_file)
            data = self.read_yaml(path, **paramvals)

            if data is not None:
                if isinstance(data, list):
                    ret.extend(data)
                else:
                    ret.append(data)

        return ret
