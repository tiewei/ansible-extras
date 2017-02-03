#! /usr/bin/env python

# This is a script that use CIMC CLI expect to setup disk
# on multiple servers. Config file example
# ---
# cimcs:
# - host: 10.254.22.28
#   tasks:
#     - name: make_unconfigured_good
#       args:
#         disks: [5, 6, 7, 8]
#     - name: create_virtual_disk
#       args:
#         disks: [5, 6, 7, 8]
#         raid: 0
#         name: ephemeral
import argparse
from os import environ
from pexpect import pxssh
import threading
import yaml


class CIMCDiskConf(threading.Thread):
    def __init__(self, username, password, configs):
        super(CIMCDiskConf, self).__init__()
        self.host = configs['host']
        self.username = configs.get('username', username)
        self.password = configs.get('password', password)
        self.tasks = configs.get('tasks', [])
        self.ssh = pxssh.pxssh()
        self.ssh.force_password = True
        self.ssh.PROMPT = "C2\d+-[A-Z0-9]+\s?[A-Z\/ 0-9a-z]+\#"

    def run(self):
        try:
            self.ssh.login(self.host,
                           self.username,
                           self.password,
                           auto_prompt_reset=False)
            for task in self.tasks:
                # import pdb;pdb.set_trace()
                getattr(self, task['name'])(task['args'])
                self._back_top()
        finally:
            self._back_top()
            try:
                self.ssh.logout()
            except Exception:
                pass
            print("Task completed for host %s" % self.host)

    def make_unconfigured_good(self, configs):
        self.ssh.PROMPT = "C2\d+-[A-Z0-9]+\s?[A-Z\/ 0-9a-z]+\#"
        for disk in configs["disks"]:
            self._scope(["chassis", "storageadapter SLOT-HBA",
                         "physical-drive %s" % disk])
            self.ssh.sendline("make-unconfigured-good")
            self.ssh.PROMPT = "Enter 'yes' to confirm"
            self.ssh.prompt()
            self.ssh.sendline("yes")
            self.ssh.PROMPT = "C2\d+-[A-Z0-9]+\s?[A-Z\/ 0-9a-z]+\#"
            self.ssh.prompt(30)
            self._back_top()

    def create_virtual_disk(self, configs):
        self._scope(["chassis", "storageadapter SLOT-HBA"])
        self.ssh.sendline("create-virtual-drive")
        self.ssh.PROMPT = "Please enter Virtual Drive name"
        self.ssh.prompt(timeout=3)
        vdev_name = configs.get("name", "raid%s-%s" % (
            configs['raid'], "".join(map(lambda x: str(x), configs['disks']))))
        self.ssh.sendline(vdev_name)
        self.ssh.PROMPT = "Please enter RAID level"
        self.ssh.prompt(timeout=3)
        self.ssh.sendline(str(configs['raid']))
        self.ssh.PROMPT = "Enter comma-separated PDs from above list"
        self.ssh.prompt(timeout=3)
        self.ssh.sendline(",".join(map(lambda x: str(x), configs['disks'])))
        # import pdb;pdb.set_trace()
        buff = self.ssh.try_read_prompt(60)
        max_size_line = filter(
            lambda output: "Max VD size for this configuration is" in output,
            buff.split("\r\n"))[0]
        _, _, max_size = max_size_line.strip().rpartition("is ")
        print max_size
        self.ssh.sendline(str(max_size))
        last_prompt = self._use_default()
        if "OK? (y or n)" in last_prompt:
            self.ssh.sendline("y")
            print self.ssh.try_read_prompt(60)

    def _scope(self, steps=[]):
        self.ssh.PROMPT = "C2\d+-[A-Z0-9]+\s?[A-Z\/ 0-9a-z]+\#"
        for step in steps:
            self.ssh.sendline("scope %s" % step)
            self.ssh.prompt(timeout=3)

    def _back_top(self):
        self.ssh.PROMPT = "C2\d+-[A-Z0-9]+\s?[A-Z\/ 0-9a-z]+\#"
        self.ssh.sendline("top")
        self.ssh.prompt(timeout=3)

    def _use_default(self):
        match = True
        while match is True:
            prompt = self.ssh.try_read_prompt(30)
            print prompt
            match = "hit return to pick default" in prompt
            if match:
                self.ssh.sendline()
        return prompt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Config CIMC disks using CLI")
    parser.add_argument("configfile",
                        help="path to the config file",
                        type=file)
    parser.add_argument("--username",
                        default="admin",
                        help="username for CIMC login, default 'admin',"
                             "can be override by CIMC_USERNAME environment "
                             "variable or config file if it's different for "
                             "each server")
    parser.add_argument("--password",
                        default=None,
                        help="password for CIMC login, can be override by "
                             "CIMC_USERNAME environment variable or config "
                             "file if different for each server")
    paramerts = parser.parse_args()
    configs = yaml.safe_load(paramerts.configfile)
    paramerts.configfile.close()

    username = paramerts.username or environ.get("CIMC_USERNAME", None)
    password = paramerts.password or environ.get("CIMC_PASSWORD", None)
    threads = []
    for cimc in configs['cimcs']:
        thread = CIMCDiskConf(username, password, cimc)
        threads.append(thread)
        thread.start()
    for t in threads:
        t.join()
