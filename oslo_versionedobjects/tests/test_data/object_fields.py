# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_versionedobjects import base
from oslo_versionedobjects import fields


@base.VersionedObjectRegistry.register
class Inner(base.VersionedObject):
    VERSION = '1.0'
    fields = {
        'name': fields.StringField(),
    }


@base.VersionedObjectRegistry.register
class Outer(base.VersionedObject):
    VERSION = '1.0'
    fields = {
        # ObjectField and ListOfObjectsField resolve to the concrete objtype
        # class (not just the VersionedObject base), because the plugin looks
        # up the named class in the mypy symbol table at analysis time.
        'child': fields.ObjectField('Inner'),
        'children': fields.ListOfObjectsField('Inner'),
        'nullable_child': fields.ObjectField('Inner', nullable=True),
    }


obj = Outer()
reveal_type(
    obj.child  # N: Revealed type is "oslo_versionedobjects.tests.test_data.object_fields.Inner"
)
reveal_type(
    obj.children  # N: Revealed type is "list[oslo_versionedobjects.tests.test_data.object_fields.Inner]"
)
reveal_type(
    obj.nullable_child  # N: Revealed type is "oslo_versionedobjects.tests.test_data.object_fields.Inner | None"
)
