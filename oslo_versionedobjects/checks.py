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

import hashlib
import inspect
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


class ObjectHashMismatch(Exception):
    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual

    def __str__(self):
        return 'Hashes have changed for %s' % (
            ','.join(set(self.expected.keys() + self.actual.keys())))


class ObjectVersionChecker(object):
    def _find_remotable_method(self, cls, thing, parent_was_remotable=False):
        """Follow a chain of remotable things down to the original function."""
        if isinstance(thing, classmethod):
            return self._find_remotable_method(cls, thing.__get__(None, cls))
        elif (inspect.ismethod(thing)
              or inspect.isfunction(thing)) and hasattr(thing, 'remotable'):
            return self._find_remotable_method(cls, thing.original_fn,
                                               parent_was_remotable=True)
        elif parent_was_remotable:
            # We must be the first non-remotable thing underneath a stack of
            # remotable things (i.e. the actual implementation method)
            return thing
        else:
            # This means the top-level thing never hit a remotable layer
            return None

    def _get_fingerprint(self, obj_name):
        obj_class = base.VersionedObjectRegistry.obj_classes()[obj_name][0]
        fields = list(obj_class.fields.items())
        fields.sort()
        methods = []
        for name in dir(obj_class):
            thing = getattr(obj_class, name)
            if inspect.ismethod(thing) or inspect.isfunction(thing) \
               or isinstance(thing, classmethod):
                method = self._find_remotable_method(obj_class, thing)
                if method:
                    methods.append((name, inspect.getargspec(method)))
        methods.sort()
        # NOTE(danms): Things that need a version bump are any fields
        # and their types, or the signatures of any remotable methods.
        # Of course, these are just the mechanical changes we can detect,
        # but many other things may require a version bump (method behavior
        # and return value changes, for example).
        if hasattr(obj_class, 'child_versions'):
            relevant_data = (fields, methods, obj_class.child_versions)
        else:
            relevant_data = (fields, methods)
        fingerprint = '%s-%s' % (obj_class.VERSION, hashlib.md5(
            six.binary_type(repr(relevant_data).encode())).hexdigest())
        return fingerprint

    def get_hashes(self):
        """Return a dict of computed object hashes."""

        fingerprints = {}
        for obj_name in sorted(base.VersionedObjectRegistry.obj_classes()):
            fingerprints[obj_name] = self._get_fingerprint(obj_name)
        return fingerprints

    def test_hashes(self, expected_hashes):
        fingerprints = self.get_hashes()

        stored = set(expected_hashes.items())
        computed = set(fingerprints.items())
        changed = stored.symmetric_difference(computed)
        expected = {}
        actual = {}
        for name, hash in changed:
            expected[name] = expected_hashes.get(name)
            actual[name] = fingerprints.get(name)

        return expected, actual
