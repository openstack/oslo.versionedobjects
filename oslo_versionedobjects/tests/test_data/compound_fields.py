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
class CompoundFieldsObject(base.VersionedObject):
    VERSION = '1.0'
    fields = {
        # AutoTypedField subclasses — plugin infers exact container types
        'str_list': fields.ListOfStringsField(),
        'str_set': fields.SetOfStringsField(),
        'str_dict': fields.DictOfStringsField(),
        'int_dict': fields.DictOfIntegersField(),
        'nested_list': fields.ListOfListsOfStringsField(),
        'states': fields.ListOfEnumField(['active', 'inactive']),
        'nullable_list': fields.ListOfStringsField(nullable=True),
        'nullable_str_dict': fields.DictOfNullableStringsField(),
        # Raw compound field types (Field wrapping a CompoundFieldType) — the
        # plugin only handles AutoTypedField subclasses, so these fall back to
        # Any.  Use a dedicated AutoTypedField subclass to get a precise type.
        'raw_list': fields.Field(fields.List(fields.Integer())),
        'raw_dict': fields.Field(fields.Dict(fields.String())),
        'raw_set': fields.Field(fields.Set(fields.Integer())),
    }


obj = CompoundFieldsObject()
reveal_type(obj.str_list)  # N: Revealed type is "list[str]"
reveal_type(obj.str_set)  # N: Revealed type is "set[str]"
reveal_type(obj.str_dict)  # N: Revealed type is "dict[str, str]"
reveal_type(obj.int_dict)  # N: Revealed type is "dict[str, int]"
reveal_type(obj.nested_list)  # N: Revealed type is "list[list[str]]"
reveal_type(obj.states)  # N: Revealed type is "list[str]"
reveal_type(obj.nullable_list)  # N: Revealed type is "list[str] | None"
reveal_type(
    obj.nullable_str_dict  # N: Revealed type is "dict[str, str | None]"
)
reveal_type(obj.raw_list)  # N: Revealed type is "Any"
reveal_type(obj.raw_dict)  # N: Revealed type is "Any"
reveal_type(obj.raw_set)  # N: Revealed type is "Any"
