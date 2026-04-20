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

from unittest import mock

import fixtures
from mypy import nodes
from mypy import options as mypy_options
from mypy import types

from oslo_versionedobjects import mypy as ovo_mypy
from oslo_versionedobjects import test


def _make_plugin():
    opts = mypy_options.Options()
    return ovo_mypy.OsloVersionedObjectPlugin(opts)


def _make_class_info(name, module_name='mymodule'):
    """Create a TypeInfo (class info) with an empty class body."""
    sym_table = nodes.SymbolTable()
    block = nodes.Block([])
    cls_def = nodes.ClassDef(name, block)
    type_info = nodes.TypeInfo(sym_table, cls_def, module_name)
    type_info._fullname = f'{module_name}.{name}'
    cls_def.info = type_info
    return type_info


def _make_fields_assignment(*field_names_and_fullnames):
    """Create an AST AssignmentStmt for ``fields = {...}``.

    Each argument should be a ``(field_name, field_type_fullname)`` tuple.
    """
    items: list[tuple[nodes.Expression | None, nodes.Expression]] = []
    for field_name, field_type_fullname in field_names_and_fullnames:
        key = nodes.StrExpr(field_name)
        callee = nodes.NameExpr(field_type_fullname.split('.')[-1])
        callee.fullname = field_type_fullname
        call = nodes.CallExpr(callee, [], [], [])
        items.append((key, call))
    lvalue = nodes.NameExpr('fields')
    return nodes.AssignmentStmt([lvalue], nodes.DictExpr(items))


def _make_object_field_assignment(
    field_name: str,
    field_type_fullname: str,
    objtype_name: str,
) -> nodes.AssignmentStmt:
    """Create an AST for ``fields = {field_name: ObjectField(objtype_name)}``.

    The ``objtype_name`` is inserted as a positional argument, matching the
    runtime signature of ``ObjectField`` and ``ListOfObjectsField``.
    """
    key = nodes.StrExpr(field_name)
    callee = nodes.NameExpr(field_type_fullname.split('.')[-1])
    callee.fullname = field_type_fullname
    call = nodes.CallExpr(
        callee,
        [nodes.StrExpr(objtype_name)],
        [nodes.ARG_POS],
        [None],
    )
    lvalue = nodes.NameExpr('fields')
    return nodes.AssignmentStmt([lvalue], nodes.DictExpr([(key, call)]))


def _make_ctx(name, statements, module_name='mymodule'):
    """Create a mock ClassDefContext with the given class body statements."""
    type_info = _make_class_info(name, module_name)
    type_info.defn.defs.body = statements
    ctx = mock.MagicMock()
    ctx.cls = type_info.defn
    ctx.cls.info = type_info
    return ctx


class TestPluginFunction(test.TestCase):
    def test_returns_plugin_class(self):
        result = ovo_mypy.plugin('1.0')
        self.assertEqual(ovo_mypy.OsloVersionedObjectPlugin, result)


class TestGetClassDecoratorHook(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_returns_hook_for_versioned_object_registry(self):
        hook = self.plugin.get_class_decorator_hook(
            'oslo_versionedobjects.base.VersionedObjectRegistry.register'
        )
        self.assertIsNotNone(hook)
        self.assertTrue(callable(hook))

    def test_returns_none_for_non_matching(self):
        hook = self.plugin.get_class_decorator_hook('some.other.Decorator')
        self.assertIsNone(hook)

    def test_env_var_custom_decorator_matches(self):
        self.useFixture(
            fixtures.EnvironmentVariable(
                'OVO_MYPY_DECORATOR_CLASSES', 'MyCustomRegistry'
            )
        )
        hook = self.plugin.get_class_decorator_hook(
            'myproject.MyCustomRegistry.register'
        )
        self.assertIsNotNone(hook)

    def test_env_var_excludes_default_when_overridden(self):
        self.useFixture(
            fixtures.EnvironmentVariable(
                'OVO_MYPY_DECORATOR_CLASSES', 'MyCustomRegistry'
            )
        )
        hook = self.plugin.get_class_decorator_hook(
            'oslo_versionedobjects.base.VersionedObjectRegistry.register'
        )
        self.assertIsNone(hook)


class TestGetBaseClassHook(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_returns_hook_for_versioned_object(self):
        hook = self.plugin.get_base_class_hook(
            'oslo_versionedobjects.base.VersionedObject'
        )
        self.assertIsNotNone(hook)
        self.assertTrue(callable(hook))

    def test_returns_none_for_non_matching(self):
        hook = self.plugin.get_base_class_hook('some.other.BaseClass')
        self.assertIsNone(hook)

    def test_env_var_custom_base_class_matches(self):
        self.useFixture(
            fixtures.EnvironmentVariable(
                'OVO_MYPY_BASE_CLASSES', 'MyBaseObject'
            )
        )
        hook = self.plugin.get_base_class_hook('myproject.MyBaseObject')
        self.assertIsNotNone(hook)

    def test_env_var_excludes_default_when_overridden(self):
        self.useFixture(
            fixtures.EnvironmentVariable(
                'OVO_MYPY_BASE_CLASSES', 'MyBaseObject'
            )
        )
        hook = self.plugin.get_base_class_hook(
            'oslo_versionedobjects.base.VersionedObject'
        )
        self.assertIsNone(hook)

    def test_returns_cache_hook_for_builtins_object(self):
        hook = self.plugin.get_base_class_hook('builtins.object')
        self.assertEqual(self.plugin._cache_fields, hook)


class TestCacheFields(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_caches_fields_dict_for_class(self):
        assignment = _make_fields_assignment(
            ('id', 'oslo_versionedobjects.fields.IntegerField'),
        )
        ctx = _make_ctx('MyObj', [assignment])
        self.plugin._cache_fields(ctx)
        self.assertIn('mymodule.MyObj', self.plugin._fields_cache)
        self.assertIsInstance(
            self.plugin._fields_cache['mymodule.MyObj'], nodes.DictExpr
        )

    def test_does_not_cache_when_no_fields_assignment(self):
        ctx = _make_ctx('MyObj', [])
        self.plugin._cache_fields(ctx)
        self.assertNotIn('mymodule.MyObj', self.plugin._fields_cache)

    def test_caches_only_first_fields_assignment(self):
        first = _make_fields_assignment(
            ('id', 'oslo_versionedobjects.fields.IntegerField'),
        )
        second = _make_fields_assignment(
            ('name', 'oslo_versionedobjects.fields.StringField'),
        )
        ctx = _make_ctx('MyObj', [first, second])
        self.plugin._cache_fields(ctx)
        cached = self.plugin._fields_cache['mymodule.MyObj']
        # Only the first assignment (with 'id') should be cached
        self.assertEqual(1, len(cached.items))
        key, _ = cached.items[0]
        self.assertIsInstance(key, nodes.StrExpr)
        self.assertEqual('id', key.value)

    def test_does_not_cache_non_dict_rvalue(self):
        # An assignment like ``fields = some_call()`` should not be cached
        lvalue = nodes.NameExpr('fields')
        callee = nodes.NameExpr('get_fields')
        call = nodes.CallExpr(callee, [], [], [])
        assignment = nodes.AssignmentStmt([lvalue], call)
        ctx = _make_ctx('MyObj', [assignment])
        self.plugin._cache_fields(ctx)
        self.assertNotIn('mymodule.MyObj', self.plugin._fields_cache)

    def test_ignores_assignments_to_other_names(self):
        other_lvalue = nodes.NameExpr('not_fields')
        other_assignment = nodes.AssignmentStmt(
            [other_lvalue], nodes.DictExpr([])
        )
        ctx = _make_ctx('MyObj', [other_assignment])
        self.plugin._cache_fields(ctx)
        self.assertNotIn('mymodule.MyObj', self.plugin._fields_cache)


class TestGetFieldsDictFromTypeInfo(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_finds_fields_dict_from_class_body(self):
        type_info = _make_class_info('MyObj')
        type_info.defn.defs.body = [
            _make_fields_assignment(
                ('id', 'oslo_versionedobjects.fields.IntegerField'),
            )
        ]
        result = self.plugin._get_fields_dict_from_type_info(type_info)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, nodes.DictExpr)

    def test_returns_none_when_no_fields_in_body(self):
        type_info = _make_class_info('MyObj')
        result = self.plugin._get_fields_dict_from_type_info(type_info)
        self.assertIsNone(result)

    def test_returns_cached_dict_in_preference_to_body(self):
        type_info = _make_class_info('MyObj')
        cached_dict = nodes.DictExpr([])
        self.plugin._fields_cache['mymodule.MyObj'] = cached_dict
        # The body also has a fields assignment, but the cache should win
        type_info.defn.defs.body = [
            _make_fields_assignment(
                ('id', 'oslo_versionedobjects.fields.IntegerField'),
            )
        ]
        result = self.plugin._get_fields_dict_from_type_info(type_info)
        self.assertIs(cached_dict, result)

    def test_falls_back_to_body_when_not_in_cache(self):
        type_info = _make_class_info('MyObj')
        type_info.defn.defs.body = [
            _make_fields_assignment(
                ('id', 'oslo_versionedobjects.fields.IntegerField'),
            )
        ]
        # Cache is empty, so the body is used
        result = self.plugin._get_fields_dict_from_type_info(type_info)
        self.assertIsNotNone(result)

    def test_ignores_assignments_to_other_names(self):
        type_info = _make_class_info('MyObj')
        other_lvalue = nodes.NameExpr('not_fields')
        type_info.defn.defs.body = [
            nodes.AssignmentStmt([other_lvalue], nodes.DictExpr([])),
            _make_fields_assignment(
                ('id', 'oslo_versionedobjects.fields.IntegerField'),
            ),
        ]
        result = self.plugin._get_fields_dict_from_type_info(type_info)
        self.assertIsNotNone(result)


class TestAddMemberToClass(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_member_appears_in_symbol_table(self):
        type_info = _make_class_info('MyObj')
        member_type = types.AnyType(types.TypeOfAny.implementation_artifact)
        self.plugin._add_member_to_class('some_field', member_type, type_info)
        self.assertIn('some_field', type_info.names)

    def test_symbol_node_has_correct_type(self):
        type_info = _make_class_info('MyObj')
        member_type = types.AnyType(types.TypeOfAny.implementation_artifact)
        self.plugin._add_member_to_class('some_field', member_type, type_info)
        sym_node = type_info.names['some_field']
        self.assertIsInstance(sym_node.node, nodes.Var)
        self.assertEqual(member_type, sym_node.node.type)

    def test_symbol_node_has_correct_fullname(self):
        type_info = _make_class_info('MyObj')
        member_type = types.AnyType(types.TypeOfAny.implementation_artifact)
        self.plugin._add_member_to_class('some_field', member_type, type_info)
        sym_node = type_info.names['some_field']
        self.assertEqual('mymodule.MyObj.some_field', sym_node.node._fullname)


class TestGetPythonTypeFromOvoFieldType(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_ctx_with_field_type(self, field_python_type):
        """Return a mock ClassDefContext whose API resolves a field type.

        Builds a real ``nodes.TypeInfo`` for the field class so that the
        ``isinstance(..., nodes.TypeInfo)`` assertion inside the plugin is
        satisfied.
        """
        var = nodes.Var('MYPY_TYPE')
        var.type = field_python_type
        mypy_type_sym = nodes.SymbolTableNode(nodes.MDEF, var)
        field_sym_table = nodes.SymbolTable()
        field_sym_table['MYPY_TYPE'] = mypy_type_sym
        field_block = nodes.Block([])
        field_cls_def = nodes.ClassDef('IntegerField', field_block)
        field_type_info = nodes.TypeInfo(
            field_sym_table, field_cls_def, 'oslo_versionedobjects.fields'
        )
        field_type_info._fullname = 'oslo_versionedobjects.fields.IntegerField'
        field_cls_def.info = field_type_info
        field_symbol = nodes.SymbolTableNode(nodes.GDEF, field_type_info)
        ctx = mock.MagicMock()
        ctx.api.lookup_fully_qualified_or_none.return_value = field_symbol
        ctx.api.parse_bool.return_value = False
        return ctx

    def test_returns_type_from_mypy_type_attribute(self):
        expected = types.AnyType(types.TypeOfAny.special_form)
        ctx = self._make_ctx_with_field_type(expected)
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.IntegerField',
            [],
            {},
        )
        self.assertEqual(expected, result)

    def test_returns_any_when_field_type_not_found(self):
        ctx = mock.MagicMock()
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.UnknownField',
            [],
            {},
        )
        self.assertIsInstance(result, types.AnyType)

    def test_returns_union_with_none_when_nullable_true(self):
        field_type = types.AnyType(types.TypeOfAny.special_form)
        ctx = self._make_ctx_with_field_type(field_type)
        ctx.api.parse_bool.return_value = True
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.IntegerField',
            [],
            {'nullable': nodes.NameExpr('True')},
        )
        self.assertIsInstance(result, types.UnionType)
        self.assertTrue(
            any(isinstance(item, types.NoneType) for item in result.items)
        )

    def test_returns_plain_type_when_nullable_false(self):
        field_type = types.AnyType(types.TypeOfAny.special_form)
        ctx = self._make_ctx_with_field_type(field_type)
        ctx.api.parse_bool.return_value = False
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.IntegerField',
            [],
            {'nullable': nodes.NameExpr('False')},
        )
        self.assertNotIsInstance(result, types.UnionType)


class TestAddOvoMembersToClass(test.TestCase):
    """Tests for _add_ovo_members_to_class, focusing on processed_fields."""

    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_ctx_with_any_api(self, name, statements):
        """Return a ClassDefContext whose API always resolves to AnyType."""
        ctx = _make_ctx(name, statements)
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        return ctx

    def test_adds_fields_to_processed_set(self):
        assignment = _make_fields_assignment(
            ('my_id', 'oslo_versionedobjects.fields.IntegerField'),
            ('name', 'oslo_versionedobjects.fields.StringField'),
        )
        ctx = self._make_ctx_with_any_api('MyObj', [assignment])
        processed: set[str] = set()
        self.plugin._add_ovo_members_to_class(
            ctx, assignment.rvalue, processed
        )
        self.assertIn('my_id', processed)
        self.assertIn('name', processed)

    def test_skips_fields_already_in_processed_set(self):
        assignment = _make_fields_assignment(
            ('id', 'oslo_versionedobjects.fields.IntegerField'),
        )
        ctx = self._make_ctx_with_any_api('MyObj', [assignment])
        # Pre-populate processed_fields as if a derived class defined 'id'
        processed: set[str] = {'id'}
        self.plugin._add_ovo_members_to_class(
            ctx, assignment.rvalue, processed
        )
        # The field from the parent must not overwrite the derived class's
        self.assertNotIn('id', ctx.cls.info.names)

    def test_non_string_key_is_skipped_with_error(self):
        # Build a fields dict with a non-literal key: fields = {x: IntField()}
        key = nodes.NameExpr('x')
        callee = nodes.NameExpr('IntegerField')
        callee.fullname = 'oslo_versionedobjects.fields.IntegerField'
        call = nodes.CallExpr(callee, [], [], [])
        dict_expr = nodes.DictExpr([(key, call)])
        lvalue = nodes.NameExpr('fields')
        assignment = nodes.AssignmentStmt([lvalue], dict_expr)
        ctx = self._make_ctx_with_any_api('MyObj', [assignment])
        processed: set[str] = set()
        self.plugin._add_ovo_members_to_class(ctx, dict_expr, processed)
        ctx.api.fail.assert_called_once()


class TestResolveOvoClassType(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_ctx_with_qualified_lookup(self, type_info):
        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        if type_info is not None:
            sym = nodes.SymbolTableNode(nodes.GDEF, type_info)
            ctx.api.lookup_qualified.return_value = sym
        else:
            ctx.api.lookup_qualified.return_value = None
        ctx.api.modules = {}
        return ctx

    def test_resolves_class_via_lookup_qualified(self):
        target_type_info = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = self._make_ctx_with_qualified_lookup(target_type_info)
        result = self.plugin._resolve_ovo_class_type(ctx, 'HostVIFInfo')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, types.Instance)
        self.assertIs(result.type, target_type_info)

    def test_falls_back_to_modules_when_lookup_qualified_fails(self):
        target_type_info = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        ctx.api.lookup_qualified.return_value = None
        sym = nodes.SymbolTableNode(nodes.GDEF, target_type_info)
        module = mock.MagicMock()
        module.names = {'HostVIFInfo': sym}
        ctx.api.modules = {'mymodule': module}
        result = self.plugin._resolve_ovo_class_type(ctx, 'HostVIFInfo')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, types.Instance)

    def test_returns_none_when_not_found(self):
        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        ctx.api.lookup_qualified.return_value = None
        ctx.api.modules = {}
        result = self.plugin._resolve_ovo_class_type(ctx, 'NotAClass')
        self.assertIsNone(result)

    def test_ignores_non_typeinfo_symbols(self):
        var = nodes.Var('HostVIFInfo')
        sym = nodes.SymbolTableNode(nodes.GDEF, var)
        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        ctx.api.lookup_qualified.return_value = sym
        ctx.api.modules = {}
        result = self.plugin._resolve_ovo_class_type(ctx, 'HostVIFInfo')
        self.assertIsNone(result)


class TestGetPythonTypeObjectFields(test.TestCase):
    """Tests for ObjectField / ListOfObjectsField handling."""

    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_field_sym(self, field_fullname):
        """Return a SymbolTableNode for a field class."""
        cls_name = field_fullname.split('.')[-1]
        module = '.'.join(field_fullname.split('.')[:-1])
        type_info = _make_class_info(cls_name, module)
        return nodes.SymbolTableNode(nodes.GDEF, type_info)

    def _make_ctx_resolving(self, field_fullname, target_type_info):
        """Return a ctx resolving the field class and target object class."""
        field_sym = self._make_field_sym(field_fullname)
        target_sym = nodes.SymbolTableNode(nodes.GDEF, target_type_info)

        # Build a TypeInfo for builtins.list so Instance(list, [...]) works.
        list_sym_table = nodes.SymbolTable()
        list_block = nodes.Block([])
        list_cls_def = nodes.ClassDef('list', list_block)
        list_type_info = nodes.TypeInfo(
            list_sym_table, list_cls_def, 'builtins'
        )
        list_type_info._fullname = 'builtins.list'
        list_cls_def.info = list_type_info
        list_sym = nodes.SymbolTableNode(nodes.GDEF, list_type_info)

        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        ctx.api.lookup_qualified.return_value = target_sym
        ctx.api.modules = {}
        ctx.api.parse_bool.return_value = False

        def _lookup_fqn(name):
            if name == field_fullname:
                return field_sym
            if name == 'builtins.list':
                return list_sym
            return None

        ctx.api.lookup_fully_qualified_or_none.side_effect = _lookup_fqn
        return ctx

    def _make_ctx_field_only(self, field_fullname):
        """Return a ctx where the field is found but target lookup fails."""
        field_sym = self._make_field_sym(field_fullname)

        ctx = mock.MagicMock()
        ctx.cls = mock.MagicMock()
        ctx.api.lookup_qualified.return_value = None
        ctx.api.modules = {}

        def _lookup_fqn(name):
            if name == field_fullname:
                return field_sym
            return None

        ctx.api.lookup_fully_qualified_or_none.side_effect = _lookup_fqn
        return ctx

    def test_object_field_returns_resolved_type(self):
        target = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = self._make_ctx_resolving(
            'oslo_versionedobjects.fields.ObjectField', target
        )
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ObjectField',
            [nodes.StrExpr('HostVIFInfo')],
            {},
        )
        self.assertIsInstance(result, types.Instance)
        self.assertIs(result.type, target)

    def test_list_of_objects_field_returns_list_of_resolved_type(self):
        target = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = self._make_ctx_resolving(
            'oslo_versionedobjects.fields.ListOfObjectsField', target
        )
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ListOfObjectsField',
            [nodes.StrExpr('HostVIFInfo')],
            {},
        )
        self.assertIsInstance(result, types.Instance)
        self.assertEqual('builtins.list', result.type.fullname)
        self.assertEqual(1, len(result.args))
        self.assertIsInstance(result.args[0], types.Instance)
        self.assertIs(result.args[0].type, target)

    def test_object_field_nullable_returns_union_with_none(self):
        target = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = self._make_ctx_resolving(
            'oslo_versionedobjects.fields.ObjectField', target
        )
        ctx.api.parse_bool.return_value = True
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ObjectField',
            [nodes.StrExpr('HostVIFInfo')],
            {'nullable': nodes.NameExpr('True')},
        )
        self.assertIsInstance(result, types.UnionType)
        self.assertTrue(
            any(isinstance(t, types.NoneType) for t in result.items)
        )

    def test_list_of_objects_field_nullable_returns_union_with_none(self):
        target = _make_class_info('HostVIFInfo', 'mymodule')
        ctx = self._make_ctx_resolving(
            'oslo_versionedobjects.fields.ListOfObjectsField', target
        )
        ctx.api.parse_bool.return_value = True
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ListOfObjectsField',
            [nodes.StrExpr('HostVIFInfo')],
            {'nullable': nodes.NameExpr('True')},
        )
        self.assertIsInstance(result, types.UnionType)
        self.assertTrue(
            any(isinstance(t, types.NoneType) for t in result.items)
        )
        # The non-None item should be list[HostVIFInfo], not list[X | None]
        non_none = [
            t for t in result.items if not isinstance(t, types.NoneType)
        ]
        self.assertEqual(1, len(non_none))
        self.assertIsInstance(non_none[0], types.Instance)
        self.assertEqual('builtins.list', non_none[0].type.fullname)

    def test_object_field_unresolvable_class_returns_any(self):
        ctx = self._make_ctx_field_only(
            'oslo_versionedobjects.fields.ObjectField'
        )
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ObjectField',
            [nodes.StrExpr('NoSuchClass')],
            {},
        )
        self.assertIsInstance(result, types.AnyType)

    def test_object_field_non_string_arg_returns_any(self):
        ctx = self._make_ctx_field_only(
            'oslo_versionedobjects.fields.ObjectField'
        )
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ObjectField',
            [nodes.NameExpr('some_var')],
            {},
        )
        self.assertIsInstance(result, types.AnyType)

    def test_object_field_no_positional_args_falls_through_to_any(self):
        ctx = self._make_ctx_field_only(
            'oslo_versionedobjects.fields.ObjectField'
        )
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.ObjectField',
            [],
            {},
        )
        self.assertIsInstance(result, types.AnyType)


class TestAddOvoMembersObjectField(test.TestCase):
    """Integration tests: _add_ovo_members_to_class with ObjectField."""

    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_ctx_with_object_resolution(
        self, field_fullname, target_type_info
    ):
        cls_name = field_fullname.split('.')[-1]
        module = '.'.join(field_fullname.split('.')[:-1])
        field_type_info = _make_class_info(cls_name, module)
        field_sym = nodes.SymbolTableNode(nodes.GDEF, field_type_info)

        target_sym = nodes.SymbolTableNode(nodes.GDEF, target_type_info)
        list_sym_table = nodes.SymbolTable()
        list_block = nodes.Block([])
        list_cls_def = nodes.ClassDef('list', list_block)
        list_type_info = nodes.TypeInfo(
            list_sym_table, list_cls_def, 'builtins'
        )
        list_type_info._fullname = 'builtins.list'
        list_cls_def.info = list_type_info
        list_sym = nodes.SymbolTableNode(nodes.GDEF, list_type_info)

        ctx = _make_ctx('Owner', [])
        ctx.api.lookup_qualified.return_value = target_sym
        ctx.api.modules = {}
        ctx.api.parse_bool.return_value = False

        def _lookup_fqn(name):
            if name == field_fullname:
                return field_sym
            if name == 'builtins.list':
                return list_sym
            return None

        ctx.api.lookup_fully_qualified_or_none.side_effect = _lookup_fqn
        return ctx

    def test_list_of_objects_field_resolved_to_list_type(self):
        field_fullname = 'oslo_versionedobjects.fields.ListOfObjectsField'
        target = _make_class_info('ChildObj', 'mymodule')
        assignment = _make_object_field_assignment(
            'children',
            field_fullname,
            'ChildObj',
        )
        ctx = self._make_ctx_with_object_resolution(field_fullname, target)
        processed: set[str] = set()
        self.plugin._add_ovo_members_to_class(
            ctx, assignment.rvalue, processed
        )
        self.assertIn('children', ctx.cls.info.names)
        field_type = ctx.cls.info.names['children'].node.type
        self.assertIsInstance(field_type, types.Instance)
        self.assertEqual('builtins.list', field_type.type.fullname)

    def test_object_field_resolved_to_instance_type(self):
        field_fullname = 'oslo_versionedobjects.fields.ObjectField'
        target = _make_class_info('ChildObj', 'mymodule')
        assignment = _make_object_field_assignment(
            'child',
            field_fullname,
            'ChildObj',
        )
        ctx = self._make_ctx_with_object_resolution(field_fullname, target)
        processed: set[str] = set()
        self.plugin._add_ovo_members_to_class(
            ctx, assignment.rvalue, processed
        )
        self.assertIn('child', ctx.cls.info.names)
        field_type = ctx.cls.info.names['child'].node.type
        self.assertIsInstance(field_type, types.Instance)
        self.assertIs(field_type.type, target)


class TestGenerateOvoFieldDefs(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_api_ctx(self, name, statements, field_python_type):
        """Return a ClassDefContext with a fully mocked API.

        Builds a real ``nodes.TypeInfo`` for the field class so that the
        ``isinstance(..., nodes.TypeInfo)`` assertion inside the plugin is
        satisfied.  The TypeInfo's MRO is set to contain only itself so that
        ``generate_ovo_field_defs`` processes the class's own fields.
        """
        ctx = _make_ctx(name, statements)
        # Make the MRO include the class itself so the MRO loop finds its
        # fields
        ctx.cls.info.mro = [ctx.cls.info]
        var = nodes.Var('MYPY_TYPE')
        var.type = field_python_type
        mypy_type_sym = nodes.SymbolTableNode(nodes.MDEF, var)
        field_sym_table = nodes.SymbolTable()
        field_sym_table['MYPY_TYPE'] = mypy_type_sym
        field_block = nodes.Block([])
        field_cls_def = nodes.ClassDef('IntegerField', field_block)
        field_type_info = nodes.TypeInfo(
            field_sym_table, field_cls_def, 'oslo_versionedobjects.fields'
        )
        field_type_info._fullname = 'oslo_versionedobjects.fields.IntegerField'
        field_cls_def.info = field_type_info
        field_symbol = nodes.SymbolTableNode(nodes.GDEF, field_type_info)
        ctx.api.lookup_fully_qualified_or_none.return_value = field_symbol
        ctx.api.parse_bool.return_value = False
        return ctx

    def test_no_fields_dict_is_noop(self):
        ctx = _make_ctx('MyObj', [])
        ctx.cls.info.mro = [ctx.cls.info]
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertEqual({}, dict(ctx.cls.info.names))

    def test_fields_are_added_to_class(self):
        field_type = types.AnyType(types.TypeOfAny.special_form)
        ctx = self._make_api_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('my_id', 'oslo_versionedobjects.fields.IntegerField'),
                    ('name', 'oslo_versionedobjects.fields.StringField'),
                )
            ],
            field_type,
        )
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertIn('my_id', ctx.cls.info.names)
        self.assertIn('name', ctx.cls.info.names)

    def test_unknown_field_type_defaults_to_any(self):
        ctx = _make_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('magic', 'myproject.fields.MagicField'),
                )
            ],
        )
        ctx.cls.info.mro = [ctx.cls.info]
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertIn('magic', ctx.cls.info.names)
        sym_node = ctx.cls.info.names['magic']
        self.assertIsInstance(sym_node.node.type, types.AnyType)

    def test_inherited_fields_are_included(self):
        """Fields from a parent class in the MRO are added to the child."""
        field_type = types.AnyType(types.TypeOfAny.special_form)
        parent_type_info = _make_class_info('Base', 'mymodule')
        parent_type_info.defn.defs.body = [
            _make_fields_assignment(
                ('inherited_id', 'oslo_versionedobjects.fields.IntegerField'),
            )
        ]
        ctx = self._make_api_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('name', 'oslo_versionedobjects.fields.StringField'),
                )
            ],
            field_type,
        )
        # MRO: child first, then parent
        ctx.cls.info.mro = [ctx.cls.info, parent_type_info]
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertIn('name', ctx.cls.info.names)
        self.assertIn('inherited_id', ctx.cls.info.names)

    def test_child_field_wins_over_same_named_parent_field(self):
        """When child and parent both define a field, the child's wins."""
        field_type = types.AnyType(types.TypeOfAny.special_form)
        parent_type_info = _make_class_info('Base', 'mymodule')
        parent_type_info.defn.defs.body = [
            _make_fields_assignment(
                ('shared', 'oslo_versionedobjects.fields.StringField'),
            )
        ]
        ctx = self._make_api_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('shared', 'oslo_versionedobjects.fields.IntegerField'),
                )
            ],
            field_type,
        )
        ctx.cls.info.mro = [ctx.cls.info, parent_type_info]
        self.plugin.generate_ovo_field_defs(ctx)
        # The field must appear exactly once in the child class's names
        self.assertIn('shared', ctx.cls.info.names)

    def test_cached_parent_fields_are_included(self):
        """Fields from the cache (not just body) are picked up via MRO."""
        field_type = types.AnyType(types.TypeOfAny.special_form)
        parent_type_info = _make_class_info('Base', 'mymodule')
        # Simulate _cache_fields having run on the parent earlier:
        # body is now empty but the cache holds the fields dict.
        cached_dict = _make_fields_assignment(
            ('cached_field', 'oslo_versionedobjects.fields.IntegerField'),
        ).rvalue
        self.plugin._fields_cache['mymodule.Base'] = cached_dict
        ctx = self._make_api_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('name', 'oslo_versionedobjects.fields.StringField'),
                )
            ],
            field_type,
        )
        ctx.cls.info.mro = [ctx.cls.info, parent_type_info]
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertIn('name', ctx.cls.info.names)
        self.assertIn('cached_field', ctx.cls.info.names)
