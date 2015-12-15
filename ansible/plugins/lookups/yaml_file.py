# This is a lookup for yaml file
# e.g /path/to/yaml/file
# ---
# foo: foo_value
# users:
#   user_one: Jim
#   user_two: Tom
#
# With inline lookup, the value of the key has to be a string
# 1. var1: "{{lookup('yaml_file', '/path/to/yaml/file key=foo')"
# 2. var2: "{{lookup('yaml_file', '/path/to/yaml/file key=users/user_one')"
# 3. var3: "{{lookup('yaml_file', '/path/to/yaml/file key=bar default=""')"
# 4. with_yaml_file:
#      - "/path/to/yaml/file key=users"
#      - "/path/to/yaml/file key=foo"
#      - "/path/to/yaml/file key=/"

from ansible import utils, errors
import yaml
from copy import deepcopy


class LookupModule(object):

    def __init__(self, basedir=None, **kwargs):
        self.basedir = basedir

    def read_yaml(self, filename, key='/', default=None):

        try:
            with open(filename) as yaml_f:
                yaml_data = yaml.load(yaml_f.read())

            if not key:
                return None

            key_path = key.strip().split("/")
            value = deepcopy(yaml_data)
            for item in key_path:
                if not item:
                    return value
                elif value and item in value:
                    value = value[item]
                else:
                    return default

            return value
        except Exception, e:
            raise errors.AnsibleError("yaml: %s" % str(e))

        return default

    def run(self, terms, inject=None, **kwargs):

        terms = utils.listify_lookup_plugin_terms(terms, self.basedir, inject)

        ret = []

        if isinstance(terms, basestring):
            terms = [terms]

        for term in terms:

            params = term.split()
            yaml_file = params[0]

            paramvals = {
                'key': "/",
                'default': None,
            }

            try:
                for param in params[1:]:
                    name, value = param.split('=')
                    assert(name in paramvals)
                    paramvals[name] = value
            except (ValueError, AssertionError), e:
                raise errors.AnsibleError(e)

            path = utils.path_dwim(self.basedir, yaml_file)

            data = self.read_yaml(path, paramvals['key'], paramvals['default'])

            if data is not None:
                if type(data) is list:
                    for v in data:
                        ret.append(v)
                else:
                    ret.append(data)

        return ret
