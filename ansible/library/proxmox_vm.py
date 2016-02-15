#!/usr/bin/python

DOCUMENTATION = '''
---
module: proxmox
short_description: management of qemu instances in Proxmox VE cluster
description:
  - allows you to create/delete/stop kvm instances in Proxmox VE cluster
version_added: "1.9"
options:
  api_host:
    description:
      - the host of the Proxmox VE cluster
    required: true
  api_user:
    description:
      - the user to authenticate with
    required: true
  api_password:
    description:
      - the password to authenticate with
      - you can use PROXMOX_PASSWORD environment variable
      - required only for backend=https
    default: null
    required: false
  api_backend:
    description:
      - proxmoxer backend options
    default: https
    choices: ["https", "openssh", "openssh_sudo"]
  api_port:
    description:
      - proxmoxer backend port
    default:
        - 8006, when use 'https' backend
        - 22, when use 'openssh_sudo' or 'openssh' backend
  validate_certs:
    description:
      - enable / disable https certificate verification
    default: false
    required: false
    type: boolean
  name:
    description:
      - the instance id / name
    default: null
    required: true
  node:
    description:
      - proxmox VE node, when new VM will be created
      - required only for C(state=clone)
      - for another task will be autodiscovered
    default: null
    required: false
  snapname:
    description:
      - snapshot name for snapshot and restore instance
      - required for C(task=snapshot) and C(task=restore)
      - allowed character: 'a-z','A-Z','0-9','_'
    default: null
    required: false
  template:
    description:
      - the template for VM creating
      - required only for C(state=clone)
    default: null
    required: false
  timeout:
    description:
      - timeout for operations
    default: 30
    required: false
    type: integer
  force:
    description:
      - forcing operations
      - can be used only with task C(stop), C(delete)
      - with task C(stop), force option will stop instead of shutdown instances
      - with task C(delete), force option will stop then delete instance
    default: false
    required: false
    type: boolean
  task:
    description:
     - indicate desired task of the instance
    choices:
      - info
      - clone
      - start
      - stop
      - delete
      - snapshot
      - restore
    default: info
notes:
  - Requires proxmoxer and requests modules on host.
requirements: [ "proxmoxer", "requests", "openssh_wrapper" ]
e.g:
    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'root'
        api_password: 'password'
        api_backend: 'https'
        name: test
        node: 'node1'
        task: clone
        template: "template"
    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'root'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: start
    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'user'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: info
    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'user'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: snapshot
        snapname: "snapname"

    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'user'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: restore
        snapname: "snapname"

    - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'user'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: stop

     - proxmox_vm:
        api_host: '10.0.1.1'
        api_user: 'user'
        api_backend: 'openssh_sudo'
        name: test
        node: 'node1'
        task: delete
        force: yes
'''

import os
import time
import re

try:
    from proxmoxer import ProxmoxAPI
    HAS_PROXMOXER = True
except ImportError:
    HAS_PROXMOXER = False


class ProxmoxBroker(object):

    def __init__(self, backend, host, user, **kwargs):
        """A wrapper object for ProxmoxAPI.

        :param backend: the backend of proxmoxer
        :param host: the host of proxmox server
        :param user: the api user name of proxmox server (default 'root')
        :param kwargs: other args ProxmoxAPI accepted
        :returns: ProxmoxBroker -- ProxmoxBroker object for module usage.
        """

        # here timeout is task timeout, not connection timeout
        self.timeout = kwargs.pop('timeout', 30)
        self.backend = backend
        self.proxmox = ProxmoxAPI(host, backend=backend, user=user, **kwargs)

    def _proxmox_node(self, node):
        """Get ProxmoxResource object for given node.

        :param node: the node name
        :returns: ProxmoxResource -- ProxmoxResource object for given node.
        """
        return self.proxmox.nodes(node)

    def _is_int(self, string):
        """Verify if given string could be convert to integer.

        :param string: the given string
        :returns: bool -- if given string could be convert to integer.
        """
        try:
            int(string)
            return True
        except ValueError:
            return False

    def _is_node_valid(self, node):
        """Verify if given node could be found in proxmox cluster.

        :param string: the node name
        :returns: bool -- if given node could be found in proxmox cluster.
        """
        for nd in self.proxmox.nodes.get():
            if nd['node'] == node:
                return True
        return False

    def _get_snapshot(self, node, vmid, snapname):
        """Get snapshot resource of given instance.

        :param node: the node name of instance
        :param vmid: the vmid of instance
        :param snapname: the snapshot name
        :returns: ProxmoxResource -- snampshot resource of the instance.
        """
        for snap in self._proxmox_node(node).qemu(vmid).snapshot.get():
            if snap.get('name') == snapname:
                return snap
        return None

    def _wait_until_timeout(self, node, taskid, vmstatus={}):
        """Wait until a task completed and meet expected vm status.

        :param node: the node name of the task
        :param taskid: the taskid
        :param vmstatus: expected vm status,
                         e.g. {"vmid": "foo", "status": "bar"}
        :returns: (bool, string): task result, message
        """
        if self.backend is not 'https':
            taskid = [data for data in taskid.split('\n') if 'UPID' in data][0]

        proxmox_node = self._proxmox_node(node)
        timeout = self.timeout
        while timeout >= 0:
            task_status = proxmox_node.tasks(taskid).status.get()
            if (task_status['status'] == 'stopped' and
                    task_status['exitstatus'] == 'OK'):

                if not vmstatus:
                    return True, "OK"
                else:
                    if vmstatus['status'] in ('absent', 'present'):
                        vms = [vm for vm in proxmox_node.qemu().get()
                               if vm['vmid'] == vmstatus['vmid']]
                        if vmstatus['status'] == 'absent' and len(vms) == 0:
                            return True, "OK"
                        elif vmstatus['status'] == 'present' and len(vms) == 1:
                            return True, vms[0]
                    else:
                        vm = proxmox_node.qemu(vmstatus['vmid']
                                               ).status.current.get()
                        if vm['status'] == vmstatus['status']:
                            return True, vm

            timeout = timeout - 1
            if timeout == 0:
                msg = proxmox_node.tasks(taskid).log.get()[:1]
                return False, msg
            time.sleep(1)
        return False, msg

    def get_instance(self, vmid_or_name, node=None):
        """Get info of an instance.

        :param vmid_or_name: the instance name or vmid
        :param node: node name of the instance (default None)
        :returns: (bool, string) -- (result of the task, vm info if success
                                     or error message if fail)
        """
        if self._is_int(vmid_or_name):
            field = 'vmid'
            vmid_or_name = int(vmid_or_name)
        else:
            field = 'name'
            vmid_or_name = str(vmid_or_name)
        vms = []
        for vm in self.proxmox.cluster.resources.get(type='vm'):
            if vm.get(field) == vmid_or_name and (not node or
                                                  vm.get('node') == node):
                vms.append(vm)

        if len(vms) == 1:
            return True, vms[0]
        elif len(vms) == 0:
            return False, "No instance with name or id %s found" % vmid_or_name
        else:
            return (False, "More than one instance with name or id %s found" %
                    vmid_or_name)

    def clone_instance(self, name, template, node):
        """Create new instance based on a template.

        Create a new instance based on given template, it will use the max_id+1
        as vmid, and will wait until the task done and the vm is present on the
        node.

        :param name: the new instance name
        :param template: the template name or vmid
        :param node: node name for the new instance
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        existed, _ = self.get_instance(name, node)
        if existed:
            return False, False, "VM with name = %s already exists" % name
        if not self._is_node_valid(node):
            return False, False, "node '%s' not exists in cluster" % node
        template_existed, t_vm = self.get_instance(template, node=node)
        if not template_existed:
            return False, False, "%s is not existed" % template
        elif template_existed and t_vm['template'] == 0:
            return False, False, "%s is not a valid template" % template
        else:
            proxmox_node = self._proxmox_node(node)
            next_id = max([vm['vmid'] for vm in proxmox_node.qemu.get()]) + 1
            taskid = proxmox_node.qemu(t_vm['vmid']).clone.post(newid=next_id,
                                                                name=name)
            expected_status = {"vmid": next_id, "status": 'present'}
            result, log = self._wait_until_timeout(node, taskid,
                                                   expected_status)

            if not result:
                return (False, True, "Reached timeout while waiting for clone "
                        "VM, last line in task before timeout %s" % log)
            else:
                return True, True, "cloned"

    def start_instance(self, name, node=None):
        """Start an instance.

        Start an instance with given name or id, it will wait until the task
        done and vm in 'running' status.

        :param name: the instance name or id
        :param node: node name for the instance, (default None)
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        rc, msg = self.get_instance(name, node)
        if not rc:
            return (rc, False, msg)
        elif msg['status'] == 'running':
            msg = "VM %s is already running" % name
            return True, False, msg
        else:
            vm = msg
            proxmox_node = self._proxmox_node(vm['node'])
            taskid = proxmox_node.qemu(vm['vmid']).status.start.post()

            expected_status = {"vmid": vm['vmid'], "status": 'running'}
            success, log = self._wait_until_timeout(vm['node'], taskid,
                                                    expected_status)

            if not success:
                return (False, True, "Reached timeout while waiting for "
                                     "starting VM, last line in task before "
                                     "timeout %s" % log)
            else:
                return True, True, "started"

    def stop_instance(self, name, node=None, force=False):
        """Stop an instance.

        Stop an instance with given name or id, it will wait until the task
        done and vm in 'stopped' status. if force=True, it will call stop for
        the instance, otherwise will call (ACPI) shutdown.

        :param name: the instance name or id
        :param node: node name for the instance, (default None)
        :param force: stop (True) or shutdown (False), (default False)
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        rc, msg = self.get_instance(name, node)
        if not rc:
            return rc, False, msg
        elif msg['status'] == 'stopped':
            msg = "VM %s is already stopped" % name
            return True, False, msg
        else:
            vm = msg
            proxmox_node = self._proxmox_node(vm['node'])
            if force:
                taskid = proxmox_node.qemu(vm['vmid']).status.stop.post()
            else:
                taskid = proxmox_node.qemu(vm['vmid']).status.shutdown.post()

            expected_status = {"vmid": vm['vmid'], "status": 'stopped'}
            success, log = self._wait_until_timeout(vm['node'], taskid,
                                                    expected_status)

            if not success:
                return (False, True, "Reached timeout while waiting for "
                                     "stopping VM, last line in task before "
                                     "timeout %s" % log)
            else:
                return True, True, "stopped"

    def delete_instance(self, name, node=None, force=False):
        """Delete an instance.

        Stop an instance with given name or id, it will wait until the task
        done and vm in absent on node. if force=True, it will stop the instance
        first if it's still in 'running' status, otherwise the task will fail.

        :param name: the instance name or id
        :param node: node name for the instance, (default None)
        :param force: force delete or not, (default False)
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        rc, msg = self.get_instance(name, node)
        if not rc:
            msg = "VM %s is already absent" % name
            return True, False, msg
        elif msg['status'] != 'stopped' and not force:
            msg = "VM %s is not stopped" % name
            return False, False, msg
        else:
            vm = msg
            proxmox_node = self._proxmox_node(vm['node'])
            if msg['status'] != 'stopped' and force:
                self.stop_instance(name, node, force=True)
            taskid = proxmox_node.qemu(vm['vmid']).delete()

            expected_status = {"vmid": vm['vmid'], "status": 'absent'}
            success, log = self._wait_until_timeout(vm['node'], taskid,
                                                    expected_status)
            if not success:
                return (False, True, "Reached timeout while waiting for "
                                     "deleting VM, last line in task before "
                                     "timeout %s" % log)
            else:
                return True, True, "deleted"

    def snapshot_instance(self, name, snapname, node=None):
        """Take a snapshot for an instance.

        :param name: the instance name or id
        :param snapname: the name of the snapshot
        :param node: node name for the instance, (default None)
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        rc, msg = self.get_instance(name, node)
        if not rc:
            return rc, False, msg
        else:
            vm = msg
            snap = self._get_snapshot(vm['node'], vm['vmid'], snapname)
            if snap:
                return True, False, "Snapshot %s exists" % snapname
            proxmox_node = self._proxmox_node(vm['node'])
            taskid = proxmox_node.qemu(vm['vmid']).snapshot().post(
                snapname=snapname, vmstate="1")

            success, log = self._wait_until_timeout(vm['node'], taskid)

            if not success:
                return (False, True, "Reached timeout while waiting for "
                                     "snapshot VM, last line in task before "
                                     "timeout %s" % log)
            else:
                return True, True, "snapshotted"

    def restore_instance(self, name, snapname, node=None):
        """Restore an instance from a snapshot.

        :param name: the instance name or id
        :param snapname: the name of the snapshot to restore from
        :param node: node name for the instance, (default None)
        :returns: (bool, bool,string) -- (result of the task, changed or not on
                                          proxmox, message for user)
        """
        rc, msg = self.get_instance(name, node)
        if not rc:
            return rc, False, msg
        else:
            vm = msg
            snap = self._get_snapshot(vm['node'], vm['vmid'], snapname)
            if not snap:
                return False, False, "Snapshot %s not found" % snapname
            proxmox_node = self._proxmox_node(vm['node'])
            taskid = proxmox_node.qemu(vm['vmid']).snapshot(
                snapname).rollback.post()

            success, log = self._wait_until_timeout(vm['node'], taskid)

            if not success:
                return (False, True, "Reached timeout while waiting for "
                                     "restore VM, last line in task before "
                                     "timeout %s" % log)
            else:
                return True, True, "restored"


def main():
    module = AnsibleModule(
        argument_spec=dict(
            api_host=dict(required=True),
            api_user=dict(required=True),
            api_backend=dict(required=False, default='https',
                             choices=['https', 'openssh', 'openssh_sudo']),
            api_password=dict(required=False, no_log=True),
            api_port=dict(required=False, type='int'),
            name=dict(required=True),
            validate_certs=dict(type='bool', choices=BOOLEANS, default='no'),
            node=dict(),
            template=dict(),
            snapname=dict(),
            timeout=dict(type='int', default=30),
            force=dict(type='bool', choices=BOOLEANS, default='no'),
            task=dict(default='info', choices=['info', 'clone', 'start',
                                               'stop', 'delete', 'snapshot',
                                               'restore']),
        )
    )

    if not HAS_PROXMOXER:
        module.fail_json(msg='proxmoxer required for this module')

    proxmoxer_extra = {}
    api_host = module.params['api_host']
    api_user = module.params['api_user']
    api_backend = module.params['api_backend']

    if api_backend in ('openssh', 'openssh_sudo'):
        require_module = 'openssh_wrapper'
        if api_backend == 'openssh_sudo':
            proxmoxer_extra['sudo'] = True
            api_backend = 'openssh'
    else:
        require_module = 'requests'
        api_backend = 'https'
    try:
        __import__(require_module)
    except ImportError:
        module.fail_json(msg="'%s' module is required for '%s' backend" % (
                         require_module, api_backend))

    api_password = (module.params['api_password'] or
                    os.environ.get('PROXMOX_PASSWORD', None))
    # https backend requires api_password
    if api_backend == 'https':
        if not api_password:
            module.fail_json(msg="'https' api backend requires api_password "
                             "param or PROXMOX_PASSWORD environment variable")
        else:
            proxmoxer_extra['password'] = api_password

    api_port = module.params['api_port']
    # Set default api port
    if not api_port:
        if api_backend == 'https':
            api_port = 8006
        else:
            api_port = 22
    proxmoxer_extra['port'] = api_port

    task = module.params['task']
    name = module.params['name']
    if api_backend == 'https':
        proxmoxer_extra['verify_ssl'] = module.params['validate_certs']
    node = module.params['node']
    template = module.params['template']
    proxmoxer_extra['timeout'] = module.params['timeout']
    force = module.params['force']
    snapname = module.params['snapname']
    if snapname and not re.match('^\w+$', snapname):
        module.fail_json(msg="snapname allowed character: "
                             "'a-z','A-Z','0-9','_'")

    try:
        proxmox = ProxmoxBroker(api_backend, api_host, api_user,
                                **proxmoxer_extra)
    except Exception as e:
        module.fail_json(msg="authorization on proxmox cluster failed with "
                             "exception: %s" % e)
    if task == 'info':
        rc, msg = proxmox.get_instance(name, node)
        changed = False
    elif task == 'clone':
        rc, changed, msg = proxmox.clone_instance(name, template, node)
    elif task == 'start':
        rc, changed, msg = proxmox.start_instance(name, node)
    elif task == 'stop':
        rc, changed, msg = proxmox.stop_instance(name, node, force)
    elif task == 'delete':
        rc, changed, msg = proxmox.delete_instance(name, node, force)
    elif task == 'snapshot':
        rc, changed, msg = proxmox.snapshot_instance(name, snapname, node)
    elif task == 'restore':
        rc, changed, msg = proxmox.restore_instance(name, snapname, node)
    else:
        rc, changed, msg = (False, False, "No task matches")

    if not rc:
        module.fail_json(changed=changed, rc=1, msg=msg)
    else:
        module.exit_json(changed=changed, rc=0, msg=msg)


# import module snippets
from ansible.module_utils.basic import *

if __name__ == '__main__':
    main()
