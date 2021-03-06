# Authors:
#   Petr Vobornik <pvoborni@redhat.com>
#
# Copyright (C) 2013  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
SELinux user map tests
"""

from ipatests.test_webui.ui_driver import UI_driver
from ipatests.test_webui.ui_driver import screenshot
import ipatests.test_webui.data_user as user
import ipatests.test_webui.data_group as group
import ipatests.test_webui.data_hostgroup as hostgroup
from ipatests.test_webui.test_host import host_tasks, ENTITY as HOST_ENTITY

ENTITY = 'selinuxusermap'
PKEY = 'itest-selinuxusermap'
DATA = {
    'pkey': PKEY,
    'add': [
        ('textbox', 'cn', PKEY),
        ('textbox', 'ipaselinuxuser', 'user_u:s0'),
    ],
    'mod': [
        ('textarea', 'description', 'itest-selinuxusermap desc'),
    ],
}


class test_selinuxusermap(UI_driver):

    @screenshot
    def test_crud(self):
        """
        Basic CRUD: selinuxusermap
        """
        self.init_app()
        self.basic_crud(ENTITY, DATA)

    @screenshot
    def test_mod(self):
        """
        Mod: selinuxusermap
        """
        self.init_app()
        host = host_tasks(self.driver, self.config)

        self.add_record(user.ENTITY, user.DATA)
        self.add_record(user.ENTITY, user.DATA2, navigate=False)
        self.add_record(group.ENTITY, group.DATA)
        self.add_record(group.ENTITY, group.DATA2, navigate=False)
        self.add_record(HOST_ENTITY, host.data)
        self.add_record(HOST_ENTITY, host.data2, navigate=False)
        self.add_record(hostgroup.ENTITY, hostgroup.DATA)
        self.add_record(hostgroup.ENTITY, hostgroup.DATA2, navigate=False)
        self.add_record(ENTITY, DATA)

        self.navigate_to_record(PKEY)

        tables = [
            ['memberuser_user', [user.PKEY, user.PKEY2], ],
            ['memberuser_group', [group.PKEY, group.PKEY2], ],
            ['memberhost_host', [host.pkey, host.pkey2], ],
            ['memberhost_hostgroup', [hostgroup.PKEY, hostgroup.PKEY2], ],
        ]

        categories = [
            'usercategory',
            'hostcategory',
        ]

        self.mod_rule_tables(tables, categories, [])

        # cleanup
        # -------
        self.delete(ENTITY, [DATA])
        self.delete(user.ENTITY, [user.DATA, user.DATA2])
        self.delete(group.ENTITY, [group.DATA, group.DATA2])
        self.delete(HOST_ENTITY, [host.data, host.data2])
        self.delete(hostgroup.ENTITY, [hostgroup.DATA, hostgroup.DATA2])

    @screenshot
    def test_actions(self):
        """
        Test SELinux user map actions
        """
        self.init_app()

        self.add_record(ENTITY, DATA)
        self.navigate_to_record(PKEY)

        self.disable_action()
        self.enable_action()
        self.delete_action(ENTITY, PKEY)
