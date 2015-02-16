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

import mock
import six

import fixtures
from oslo_serialization import jsonutils
from oslo_versionedobjects import base


class FakeIndirectionAPI(base.VersionedObjectIndirectionAPI):
    def __init__(self):
        super(FakeIndirectionAPI, self).__init__()
        self._ser = base.VersionedObjectSerializer()

    def _get_changes(self, orig_obj, new_obj):
        updates = dict()
        for name, field in new_obj.fields.items():
            if not new_obj.obj_attr_is_set(name):
                continue
            if (not orig_obj.obj_attr_is_set(name) or
                    getattr(orig_obj, name) != getattr(new_obj, name)):
                updates[name] = field.to_primitive(new_obj, name,
                                                   getattr(new_obj, name))
        return updates

    def object_action(self, context, objinst, objmethod, args, kwargs):
        objinst = self._ser.deserialize_entity(
            context, self._ser.serialize_entity(
                context, objinst))
        objmethod = six.text_type(objmethod)
        args = jsonutils.loads(jsonutils.dumps(args))
        kwargs = jsonutils.loads(jsonutils.dumps(kwargs))
        original = objinst.obj_clone()
        with mock.patch('oslo_versionedobjects.base.VersionedObject.'
                        'indirection_api', new=None):
            result = getattr(objinst, objmethod)(*args, **kwargs)
        updates = self._get_changes(original, objinst)
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        objname = six.text_type(objname)
        objmethod = six.text_type(objmethod)
        objver = six.text_type(objver)
        args = jsonutils.loads(jsonutils.dumps(args))
        kwargs = jsonutils.loads(jsonutils.dumps(kwargs))
        cls = base.VersionedObject.obj_class_from_name(objname, objver)
        with mock.patch('oslo_versionedobjects.base.VersionedObject.'
                        'indirection_api', new=None):
            result = getattr(cls, objmethod)(context, *args, **kwargs)
        return (base.VersionedObject.obj_from_primitive(
            result.obj_to_primitive(target_version=objver),
            context=context)
            if isinstance(result, base.VersionedObject) else result)

    def object_backport(self, context, objinst, target_version):
        raise Exception('not supported')


class IndirectionFixture(fixtures.Fixture):
    def setUp(self):
        super(IndirectionFixture, self).setUp()
        self.indirection_api = FakeIndirectionAPI()
        self.useFixture(fixtures.MonkeyPatch(
            'oslo_versionedobjects.base.VersionedObject.indirection_api',
            self.indirection_api))
