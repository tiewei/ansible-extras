#! /usr/bin/env python
DOCUMENTATION = '''
---
module: cimc_conf
short_description: Get and set base resource for CIMC
description: Get and set base resource for CIMC
version_added: "1.9"
options:
  host:
    description:
      - the host of the CIMC
    required: true
  user:
    description:
      - the user to authenticate with
    required: true
  password:
    description:
      - the password of user to authenticate with
    required: true
  timeout:
    description:
      - timeout for waiting task done
    required: false
    default: 30
  resource:
    description:
      - the type of resource to be 'get' or 'set'
    required: true
    choices:
      - power
      - boot_device
      - net_adaptors
      - vmedias
  task:
    description:
      - the task to given resource
      - set task is not supported for 'net_adaptors' resource
      - set task only support 'Legacy' mode for 'boot_device' resource
    required: false
    choices: ['get', 'set']
    default: get
  config:
    description:
      - the config of given resource when set
      - "power_state=['on', 'off', 'reboot']" when resource is 'power'
      - "device=['CDROM', 'FDD', 'PXE', 'EFI', 'HDD'], order=[1-5]" when
        resource is 'boot_device'
      - "name=,remote_file=,map=['www', 'nfs', 'cifs'],remote_share="
        when resource is 'vmedias'
      - "name=,map=unmap" when resource is 'vmedias'
    required: false
    type: dict

notes:
  - Requires ImcSdk-0.7.2 installed on host.
requirements: ["ImcSdk"]
e.g:
# Get network adaptor data
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'get'
    resource: 'net_adaptors'
  register: cimc_nic

# Get current power status
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'get'
    resource: 'power'
  register: cimc_power

# Reboot server
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'set'
    resource: 'power'
    config:
        power_state: reboot

# Get current boot devices
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'get'
    resource: 'boot_device'
  register: cimc_power_ops

# Set PXE as first boot device
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'set'
    resource: 'boot_device'
    config:
        device: PXE
        order: 1

# Get vmedias list
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'get'
    resource: 'vmedias'
  register: vmedias

# Mount vmedia
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'set'
    resource: 'vmedias'
    config:
        name: rhel
        remote_file: rhel-server-7.2-x86_64-boot.iso
        map: www
        remote_share: http://64.104.118.53:8080/
  register: vmedias

# Unmout vmedia
- cimc_conf:
    host: 'host'
    user: 'admin'
    password: 'password'
    task: 'set'
    resource: 'vmedias'
    config:
        name: rhel
        map: unmap
  register: vmedias

'''

from contextlib import contextmanager
from copy import deepcopy
from time import sleep

try:
    import ImcSdk as imcsdk
    # Force to use 0.7.2 sdk
    if imcsdk.__version__ == '0.7.2':
        HAS_IMC_SDK = True
    else:
        HAS_IMC_SDK = False
except ImportError:
    HAS_IMC_SDK = False


class CIMCBroker(object):
    """CIMC broker to query get/set CIMC configuration."""

    CIMC_POWER_OPTIONS = {
        "on": imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_UP,
        "off": imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_DOWN,
        "reboot": imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_HARD_RESET_IMMEDIATE
    }

    CIMC_BOOT_DEVICES_MAPPING = {
        "vm-read-only": "CDROM",
        "vm-read-write": "FDD",
        "lan-read-only": "PXE",
        "storage-read-write": "HDD",
        "efi-read-only": "EFI"
    }

    BOOT_DEVICES_CIMC_ATTRS = {
        "CDROM": dict(Dn='sys/rack-unit-1/boot-policy/vm-read-only',
                      Rn='vm-read-only',
                      Access='read-only',
                      class_id='LsbootVirtualMedia'),
        "FDD": dict(Dn='sys/rack-unit-1/boot-policy/vm-read-write',
                    Rn='vm-read-write',
                    Access='read-write',
                    class_id='LsbootVirtualMedia'),
        "PXE": dict(Dn='sys/rack-unit-1/boot-policy/lan-read-only',
                    Rn='lan-read-only',
                    Access='read-only',
                    class_id='LsbootLan'),
        "EFI": dict(Dn='sys/rack-unit-1/boot-policy/efi-read-only',
                    Rn='efi-read-only',
                    Access='read-only',
                    class_id='LsbootEfi'),
        "HDD": dict(Dn='sys/rack-unit-1/boot-policy/storage-read-write',
                    Rn='storage-read-write',
                    Access='read-write',
                    class_id='LsbootStorage'),
    }

    CIMC_VMEDIA_MAP_OPTIONS = {
        "www": "noauto",
        "nfs": "nolock",
        "cifs": "",
        # self-defined type for unmap the device
        "unmap": ""
    }

    def __init__(self, host, user, password, timeout=None):
        """Init CIMCBroker."""
        self.host = host
        self.username = user
        self.password = password
        self.changed = False
        self._interval = 3
        self._wait_retry = timeout / self._interval

    @contextmanager
    def _cimc_handle(self):
        """CIMC login handle."""
        handle = imcsdk.ImcHandle()
        try:
            handle.login(self.host, self.username, self.password)
            yield handle
        finally:
            handle.logout()

    def _wait_util(self, expect, func, *args, **kwargs):
        """Wait until function return expected value.

        :expect: expected value from function.
        :func: function to call every interval.
        """
        left = self._wait_retry
        while left > 0:
            if func(*args, **kwargs) == expect:
                return
            else:
                left = left - 1
                sleep(self._interval)

        raise Exception("Timeout waiting for state change to %s" % expect)

    def _get_power_state(self, handle):
        """Get CIMC power state.

        :params handle: ImcHandle, A logined IMC handle
        """
        rack_unit = handle.get_imc_managedobject(
            None, None, params={"Dn": "sys/rack-unit-1"})
        return rack_unit[0].get_attr("OperPower")

    def get_power(self):
        """Get CIMC power state."""
        current_power_state = None
        with self._cimc_handle() as handle:
            current_power_state = self._get_power_state(handle)

        return dict(power_state=current_power_state)

    def set_power(self, **config):
        """
        Set CIMC power state.

        If it's already in target state ['on','off'], it will skip operation,
        If it's set to 'reboot', a rebooting will be performed.
        """
        power_state = config.get('power_state', None)
        if power_state not in ("on", "off", "reboot"):
            raise Exception("power state has to be in ('on', 'off', 'reboot')")
        else:
            cimc_power_ops = self.CIMC_POWER_OPTIONS.get(power_state)
        with self._cimc_handle() as handle:
            current_power = self._get_power_state(handle)
            if current_power == power_state:
                return
            elif power_state == 'reboot' and current_power == 'off':
                cimc_power_ops = self.CIMC_POWER_OPTIONS.get('on')

            handle.set_imc_managedobject(
                None, class_id="ComputeRackUnit",
                params={
                    imcsdk.ComputeRackUnit.ADMIN_POWER: cimc_power_ops,
                    imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                })

            expect_state = power_state if power_state != 'reboot' else 'on'

            self._wait_util(expect_state, self._get_power_state, handle)
            self.changed = True
            return dict(power_state=expect_state)

    def _get_bios_mode(self, handle):
        """Get CIMC bios mode.

        :params handle: ImcHandle, A logined IMC handle
        """
        bios_mode = handle.get_imc_managedobject(
            None, None, params={"Dn": "sys/rack-unit-1/boot-precision"})[0]
        return bios_mode.ConfiguredBootMode

    def _get_boot_devices(self, handle):
        """Get CIMC boot devices.

        :params handle: ImcHandle, A logined IMC handle
        """
        bios_mode = self._get_bios_mode(handle)
        boot_device = []
        if bios_mode == 'Legacy':
            #
            # NOTE (wtie):
            # 1. Boot order configuration prior to 2.0(x) is referred as legacy
            # boot order. If your running version is 2.0(x), then you cannot
            # configure legacy boot order through web UI, but you can configure
            # through CLI and XML API. In the CLI, you can configure it by
            # using set boot-order HDD,PXE command. Even though, you can
            # configure legacy boot order through CLI or XML API, in the web UI
            # this configured boot order is not displayed.
            # 2. Legacy and precision boot order features are mutually
            # exclusive. You can configure either legacy or precision boot
            # order. If you configure legacy boot order, it disables all the
            # precision boot devices configured. If you configure precision
            # boot order, then it erases legacy boot order configuration
            #
            method = imcsdk.ImcCore.ExternalMethod("ConfigResolveClass")
            method.Cookie = handle.cookie
            method.InDn = "sys/rack-unit-1"
            method.InHierarchical = "true"
            method.ClassId = "lsbootDef"

            resp = handle.xml_query(method, imcsdk.WriteXmlOption.DIRTY)
            error = getattr(resp, 'error_code', 0)
            if error != 0:
                raise Exception(resp.error_descr)

            boot_devs = resp.OutConfigs.child[0].child

            for dev in boot_devs:
                try:
                    if (dev.Rn in self.CIMC_BOOT_DEVICES_MAPPING and
                            int(dev.Order)) > 0:
                        boot_device.append(dict(
                            order=int(dev.Order),
                            device=self.CIMC_BOOT_DEVICES_MAPPING.get(dev.Rn)))
                except (ValueError, AttributeError):
                    # ignore entries without vaild Order
                    pass
        else:
            bios = handle.get_imc_managedobject(
                None, None,
                params={"Dn": "sys/rack-unit-1/bios/bdgep"})
            boot_precision = handle.get_imc_managedobject(
                in_mo=bios,
                class_id=imcsdk.BiosBootDevPrecision.class_id())
            for cimc_dev in boot_precision:
                boot_device.append(dict(
                    slot=cimc_dev.Slot,
                    device=cimc_dev.Name,
                    type=cimc_dev.Type,
                    order=cimc_dev.Order,
                    description=cimc_dev.Descr))
        return boot_device

    def get_boot_device(self):
        """Get CIMC boot device."""
        boot_device = {'boot_device': []}
        with self._cimc_handle() as handle:
            boot_device['boot_device'] = self._get_boot_devices(handle)
        return boot_device

    def set_boot_device(self, **config):
        """Set CIMC boot device."""
        dev = config.get('device', None)
        order = config.get('order', None)
        if dev not in self.BOOT_DEVICES_CIMC_ATTRS:
            raise Exception("device name %s not in %s", dev,
                            self.BOOT_DEVICES_CIMC_ATTRS)
        else:
            boot_cimc_dev = deepcopy(self.BOOT_DEVICES_CIMC_ATTRS[dev])
        order_index = int(order)
        if order_index < 0 or order_index > 5:
            raise Exception("device order %d must be in [1-5]",
                            order_index)
        else:
            boot_cimc_dev['Order'] = order_index

        with self._cimc_handle() as handle:
            bios_mode = self._get_bios_mode(handle)
            if bios_mode != 'Legacy':
                raise Exception("Setting boot device only supports "
                                "bios legacy mode, get %s.", bios_mode)
            # Currently only works on "Legacy" mode
            current_boot_devices = self._get_boot_devices(handle)
            for current_dev in current_boot_devices:
                if (current_dev['device'] == dev and
                        current_dev['order'] == order_index):
                    return current_boot_devices
            boot_device = handle.get_imc_managedobject(
                None, None, params={"Dn": boot_cimc_dev['Dn']})
            class_id = boot_cimc_dev.pop("class_id")
            if boot_device:
                handle.set_imc_managedobject(
                    in_mo=boot_device,
                    class_id=None,
                    params=boot_cimc_dev)
            else:
                handle.add_imc_managedobject(
                    None,
                    class_id=class_id,
                    params=boot_cimc_dev)
            current_boot_devices = self._get_boot_devices(handle)
            self.changed = True
        return current_boot_devices

    def get_net_adaptors(self):
        """Get CIMC network adaptors."""
        net_adaptors = []
        with self._cimc_handle() as handle:
            # only one rack in a cimc
            rack_unit = handle.get_imc_managedobject(
                None,
                imcsdk.ComputeRackUnit.class_id())[0]
            network_adaptor_units = handle.get_imc_managedobject(
                in_mo=rack_unit, class_id=imcsdk.AdaptorUnit.class_id())
            for adaptor in network_adaptor_units:
                adaptor_data = dict(
                    dn=adaptor.Dn,
                    rn=adaptor.Rn,
                    vendor=adaptor.Vendor,
                    id=adaptor.Id,
                    pci_slot=adaptor.PciSlot,
                    pci_addr=adaptor.PciAddr,
                    serial=adaptor.Serial,
                    model=adaptor.Model,
                    presence=adaptor.Presence,
                    vnics=[]
                )
                vnic_list = handle.get_imc_managedobject(
                    in_mo=adaptor,
                    class_id=imcsdk.AdaptorHostEthIf.class_id())
                for vnic in vnic_list:
                    eth_profile = handle.get_imc_managedobject(
                        in_mo=vnic,
                        class_id=imcsdk.AdaptorEthGenProfile.class_id())[0]
                    vnic_data = dict(
                        dn=vnic.Dn,
                        rn=vnic.Rn,
                        if_type=vnic.IfType,
                        iscsi_boot=vnic.IscsiBoot,
                        mac=vnic.Mac,
                        name=vnic.Name,
                        mtu=vnic.Mtu,
                        pxe_boot=vnic.PxeBoot,
                        vlan_id=eth_profile.Vlan,
                        vlan_mode=eth_profile.VlanMode,
                    )
                    adaptor_data['vnics'].append(vnic_data)
                net_adaptors.append(adaptor_data)
        return dict(net_adaptors=net_adaptors)

    def set_net_adaptors(self, **config):
        """Set CIMC network adaptors."""
        raise Exception("Setting network adaptors is not supported.")

    def get_vmedias(self):
        """Get CIMC vmedia list."""
        vmedia_mappings = []
        vmedia_enabled = False
        with self._cimc_handle() as handle:
            vmedia, vmedia_enabled = self._is_vmedia_enabled(handle)
            if vmedia_enabled:
                vmedia_mappings = self._get_vmedia_mappings(handle, vmedia)
        return {"vmedias": dict(enabled=vmedia_enabled,
                                mappings=vmedia_mappings)}

    def _is_vmedia_enabled(self, handle):
        """Check CIMC enabled vmedia.

        :params handle: ImcHandle, A logined IMC handle
        :return (CommVMedia, Boolean)
        """
        vmedia = handle.get_imc_managedobject(
            None, None, params={"Dn": "sys/svc-ext/vmedia-svc"})[0]
        enabled = (vmedia.AdminState == 'enabled')
        return (vmedia, enabled)

    def _get_vmedia_mappings(self, handle, vmedia, raw=False):
        """Get CIMC vmedia list.

        :params handle: ImcHandle, A logined IMC handle
        :params vmedia: CommVMedia, CIMC CommVMedia object
        :params raw: Boolean, return raw CIMC CommVMediaMap or dict format list
        :return List
        """
        vmedia_mappings = []
        cimc_vmedias = handle.get_imc_managedobject(
            in_mo=vmedia, class_id=imcsdk.CommVMediaMap.class_id())
        for vmedia in cimc_vmedias:
            if raw:
                vmedia_mappings.append(vmedia)
            else:
                mount = dict(
                    name=vmedia.VolumeName,
                    remote_file=vmedia.RemoteFile,
                    remote_share=vmedia.RemoteShare,
                    password=vmedia.Password,
                    user=vmedia.Username,
                    status=vmedia.Status,
                    map=vmedia.Map,
                    map_status=vmedia.MappingStatus,
                    mount_options=vmedia.MountOptions,
                    drive_type=vmedia.DriveType)
                vmedia_mappings.append(mount)
        return vmedia_mappings

    def _delete_vmedia_mapping(self, handle, raw_mapping):
        """Delete a CIMC vmedia mapping.

        :params handle: ImcHandle, A logined IMC handle
        :params raw_mapping: CommVMediaMap, CIMC CommVMediaMap object
        :return
        """
        raw_mapping.Status = imcsdk.Status.REMOVED
        in_config = imcsdk.ConfigConfig()
        in_config.add_child(raw_mapping)
        method = imcsdk.ImcCore.ExternalMethod("configConfMo")
        method.Cookie = handle.cookie
        method.InDn = raw_mapping.Dn
        method.InHierarchical = "false"
        method.InConfig = in_config
        resp = handle.xml_query(method, imcsdk.WriteXmlOption.DIRTY)
        error = getattr(resp, 'error_code', 0)
        if error != 0:
            raise Exception(getattr(resp, "error_descr"))
        self.changed = True

    def _create_vmedia_mapping(self, handle, mapping):
        """Create a CIMC vmedia mapping.

        :params handle: ImcHandle, A logined IMC handle
        :params mapping: dict, vmedia mapping data
        :return
        """
        mount_opts = [mapping['MountOptions']]
        user = mapping.pop('Username')
        password = mapping.pop('Password')
        if user:
            mount_opts.append("username=%s" % user)
        if password:
            mount_opts.append("password=%s" % password)
        mapping['MountOptions'] = ",".join(mount_opts)
        handle.add_imc_managedobject(
            None, class_id=imcsdk.CommVMediaMap.class_id(), params=mapping)
        self.changed = True

    def _update_vmedia_mapping(self, handle, old_mapping, new_mapping):
        """Update a CIMC vmedia mapping.

        It compares 'RemoteFile', 'RemoteShare', 'Username', 'Password',
        'Map', 'MountOptions' between old_mapping and new_mapping, if found
        mismatching, will delete old_mapping and create new_mapping.

        :params handle: ImcHandle, A logined IMC handle
        :params mapping: dict, vmedia mapping data
        :return
        """
        need_update = False
        for field in ('RemoteFile', 'RemoteShare', 'Username', 'Password',
                      'Map', 'MountOptions'):
            if old_mapping.get_attr(field) != new_mapping[field]:
                need_update = True
                break
        if need_update:
            self._delete_vmedia_mapping(handle, old_mapping)
            self._create_vmedia_mapping(handle, new_mapping)
        return

    def set_vmedias(self, **config):
        """Create,Delete,Update CIMC vmedia."""
        name = config.get('name')
        remote_file = config.get('remote_file')
        remote_share = config.get('remote_share')
        map_type = config.get('map')
        if map_type not in self.CIMC_VMEDIA_MAP_OPTIONS:
            raise Exception("Set vmedias 'map' supports %s, got %s",
                            self.CIMC_VMEDIA_MAP_OPTIONS.keys(), map_type)
        elif map_type == 'unmap' and not name:
            raise Exception("Unmap vmedias requires 'name' , got %s", name)
        elif map_type != 'unmap' and not any((
                name, remote_file, remote_share, map_type)):
            raise Exception("%s are required for set vmedias",
                            ('remote_file', 'remote_share', 'map', 'name'))

        password = config.get('password', '')
        user = config.get('user', None)
        mount_options = config.get(
            'mount_options', self.CIMC_VMEDIA_MAP_OPTIONS[map_type])

        new_mapping = dict(VolumeName=name,
                           RemoteFile=remote_file,
                           RemoteShare=remote_share,
                           Map=map_type,
                           MountOptions=mount_options,
                           Username=user,
                           Password=password,
                           Dn="sys/svc-ext/vmedia-svc/vmmap-%s" % name,
                           Rn="vmmap-%s" % name)
        vmedia_mappings = []
        with self._cimc_handle() as handle:
            vmedia, vmedia_enabled = self._is_vmedia_enabled(handle)
            if not vmedia_enabled:
                handle.set_imc_managedobject(
                    None, class_id=imcsdk.CommVMedia.class_id(),
                    params={
                        imcsdk.CommVMedia.ADMIN_STATE: "enabled",
                        imcsdk.CommVMedia.DN: "sys/svc-ext/vmedia-svc"
                    })
                self.changed = True

            # Use raw data from cimc here
            vmedia_mappings = self._get_vmedia_mappings(handle, vmedia,
                                                        raw=True)
            old_mapping = None
            for mapping in vmedia_mappings:
                if mapping.VolumeName == new_mapping['VolumeName']:
                    old_mapping = mapping
                    break
            if map_type == 'unmap' and old_mapping is None:
                pass
            elif old_mapping and map_type == 'unmap':
                self._delete_vmedia_mapping(handle, old_mapping)
            elif old_mapping:
                self._update_vmedia_mapping(handle, old_mapping, new_mapping)
            else:
                self._create_vmedia_mapping(handle, new_mapping)

            vmedia_mappings = self._get_vmedia_mappings(handle, vmedia)

        return {"vmedias": dict(enabled=True,
                                mappings=vmedia_mappings)}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(required=True),
            user=dict(required=True),
            password=dict(required=True, no_log=True),
            timeout=dict(required=False, type='int', default=30),
            resource=dict(required=True, choices=['power', 'boot_device',
                                                  'net_adaptors', 'vmedias']),
            task=dict(required=False, choices=['set', 'get'],
                      default='get'),
            config=dict(type='dict', default={}, required=False),
        )
    )

    if not HAS_IMC_SDK:
        module.fail_json(msg='imcsdk == 0.7.2 required for this module')

    host = module.params['host']
    user = module.params['user']
    password = module.params['password']
    timeout = module.params['timeout']
    resource = module.params['resource']
    task = module.params['task']
    config = module.params['config']

    cimc = CIMCBroker(host, user, password, timeout)
    method = "%s_%s" % (task, resource)

    msg = getattr(cimc, method)(**config)
    module.exit_json(changed=cimc.changed, msg=msg)

# import module snippets
from ansible.module_utils.basic import *

if __name__ == '__main__':
    main()

