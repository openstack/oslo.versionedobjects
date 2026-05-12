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
class TimestampedObject(base.TimestampedObject, base.VersionedObject):
    VERSION = '1.0'
    fields = {
        'name': fields.StringField(),
    }


obj = TimestampedObject()
reveal_type(obj.name)  # N: Revealed type is "str"
reveal_type(obj.created_at)  # N: Revealed type is "datetime.datetime | None"
reveal_type(obj.updated_at)  # N: Revealed type is "datetime.datetime | None"
