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


class StatusField(fields.BaseEnumField):
    """A named enum with a fixed set of values."""

    AUTO_TYPE = fields.Enum(valid_values=['active', 'error', 'deleted'])


@base.VersionedObjectRegistry.register
class EnumFieldsObject(base.VersionedObject):
    VERSION = '1.0'
    fields = {
        # Anonymous EnumField and its named BaseEnumField subclass both resolve
        # to Any — the generic parameter on BaseEnumField is explicitly Any
        # because enum values are strings at runtime but the field accepts any
        # valid value type.
        'status': StatusField(),
        'state': fields.EnumField(['pending', 'running', 'done']),
        'nullable_status': StatusField(nullable=True),
    }


obj = EnumFieldsObject()
reveal_type(obj.status)  # N: Revealed type is "Any"
reveal_type(obj.state)  # N: Revealed type is "Any"
reveal_type(obj.nullable_status)  # N: Revealed type is "Any | None"
