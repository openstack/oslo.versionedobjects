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
class BasicFieldsObject(base.VersionedObject):
    VERSION = '1.0'
    fields = {
        'uuid': fields.UUIDField(),
        'name': fields.StringField(),
        'count': fields.IntegerField(),
        'ratio': fields.FloatField(),
        'active': fields.BooleanField(),
        'created_at': fields.DateTimeField(nullable=True),
    }


obj = BasicFieldsObject()
reveal_type(obj.uuid)  # N: Revealed type is "str"
reveal_type(obj.name)  # N: Revealed type is "str"
reveal_type(obj.count)  # N: Revealed type is "int"
reveal_type(obj.ratio)  # N: Revealed type is "float"
reveal_type(obj.active)  # N: Revealed type is "bool"
reveal_type(obj.created_at)  # N: Revealed type is "datetime.datetime | None"
