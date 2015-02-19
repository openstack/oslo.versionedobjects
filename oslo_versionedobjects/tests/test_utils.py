#    Copyright 2011 Justin Santa Barbara
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg

from oslo_versionedobjects import _utils as utils
from oslo_versionedobjects import exception
from oslo_versionedobjects import test

CONF = cfg.CONF


class VersionTestCase(test.TestCase):
    def test_convert_version_to_int(self):
        self.assertEqual(utils.convert_version_to_int('6.2.0'), 6002000)
        self.assertEqual(utils.convert_version_to_int((6, 4, 3)), 6004003)
        self.assertEqual(utils.convert_version_to_int((5, )), 5)
        self.assertRaises(exception.VersionedObjectsException,
                          utils.convert_version_to_int, '5a.6b')

    def test_convert_version_to_string(self):
        self.assertEqual(utils.convert_version_to_str(6007000), '6.7.0')
        self.assertEqual(utils.convert_version_to_str(4), '4')

    def test_convert_version_to_tuple(self):
        self.assertEqual(utils.convert_version_to_tuple('6.7.0'), (6, 7, 0))
