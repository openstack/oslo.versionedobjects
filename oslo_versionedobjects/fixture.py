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
import logging
import mock
import six

import fixtures
from oslo_versionedobjects import _utils as utils
from oslo_versionedobjects import base
from oslo_versionedobjects import fields


LOG = logging.getLogger(__name__)


class FakeIndirectionAPI(base.VersionedObjectIndirectionAPI):
    def __init__(self, serializer=None):
        super(FakeIndirectionAPI, self).__init__()
        self._ser = serializer or base.VersionedObjectSerializer()

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

    def _canonicalize_args(self, context, args, kwargs):
        args = tuple(
            [self._ser.deserialize_entity(
                context, self._ser.serialize_entity(context, arg))
             for arg in args])
        kwargs = dict(
            [(argname, self._ser.deserialize_entity(
                context, self._ser.serialize_entity(context, arg)))
             for argname, arg in six.iteritems(kwargs)])
        return args, kwargs

    def object_action(self, context, objinst, objmethod, args, kwargs):
        objinst = self._ser.deserialize_entity(
            context, self._ser.serialize_entity(
                context, objinst))
        objmethod = six.text_type(objmethod)
        args, kwargs = self._canonicalize_args(context, args, kwargs)
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
        args, kwargs = self._canonicalize_args(context, args, kwargs)
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
    def __init__(self, indirection_api=None):
        self.indirection_api = indirection_api or FakeIndirectionAPI()

    def setUp(self):
        super(IndirectionFixture, self).setUp()
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
        obj_fields = list(obj_class.fields.items())
        obj_fields.sort()
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
            relevant_data = (obj_fields, methods, obj_class.child_versions)
        else:
            relevant_data = (obj_fields, methods)
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

    def _get_dependencies(self, tree, obj_class):
        obj_name = obj_class.obj_name()
        if obj_name in tree:
            return

        for name, field in obj_class.fields.items():
            if isinstance(field._type, fields.Object):
                sub_obj_name = field._type._obj_name
                obj_classes = base.VersionedObjectRegistry.obj_classes()
                sub_obj_class = obj_classes[sub_obj_name][0]
                self._get_dependencies(tree, sub_obj_class)
                tree.setdefault(obj_name, {})
                tree[obj_name][sub_obj_name] = sub_obj_class.VERSION

    def get_dependency_tree(self):
        tree = {}
        obj_classes = base.VersionedObjectRegistry.obj_classes()
        for obj_name in base.VersionedObjectRegistry.obj_classes().keys():
            self._get_dependencies(tree, obj_classes[obj_name][0])
        return tree

    def test_relationships(self, expected_tree):
        actual_tree = self.get_dependency_tree()

        stored = set([(x, str(y)) for x, y in expected_tree.items()])
        computed = set([(x, str(y)) for x, y in actual_tree.items()])
        changed = stored.symmetric_difference(computed)
        expected = {}
        actual = {}
        for name, deps in changed:
            expected[name] = expected_tree.get(name)
            actual[name] = actual_tree.get(name)

        return expected, actual

    def _test_object_compatibility(self, obj_class):
        version = utils.convert_version_to_tuple(obj_class.VERSION)
        for n in range(version[1] + 1):
            test_version = '%d.%d' % (version[0], n)
            LOG.info('testing obj: %s version: %s' %
                     (obj_class.obj_name(), test_version))
            obj_class().obj_to_primitive(target_version=test_version)

    def test_compatibility_routines(self):
        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.
        all_obj_classes = base.VersionedObjectRegistry.obj_classes()
        for obj_name in all_obj_classes:
            obj_classes = base.VersionedObjectRegistry.obj_classes()[obj_name]
            for obj_class in obj_classes:
                self._test_object_compatibility(obj_class)

    def _test_relationships_in_order(self, obj_class):
        for field, versions in obj_class.obj_relationships.items():
            last_my_version = (0, 0)
            last_child_version = (0, 0)
            for my_version, child_version in versions:
                _my_version = utils.convert_version_to_tuple(my_version)
                _ch_version = utils.convert_version_to_tuple(child_version)
                assert (last_my_version < _my_version
                        and last_child_version <= _ch_version), \
                    ('Object %s relationship '
                     '%s->%s for field %s is out of order') % (
                         obj_class.obj_name(), my_version,
                         child_version, field)
                last_my_version = _my_version
                last_child_version = _ch_version

    def test_relationships_in_order(self):
        # Iterate all object classes and verify that we can run
        # obj_make_compatible with every older version than current.
        # This doesn't actually test the data conversions, but it at least
        # makes sure the method doesn't blow up on something basic like
        # expecting the wrong version format.
        all_obj_classes = base.VersionedObjectRegistry.obj_classes()
        for obj_name in all_obj_classes:
            obj_classes = base.VersionedObjectRegistry.obj_classes()[obj_name]
            for obj_class in obj_classes:
                self._test_relationships_in_order(obj_class)
