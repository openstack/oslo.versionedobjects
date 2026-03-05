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
    items = []
    for field_name, field_type_fullname in field_names_and_fullnames:
        key = nodes.StrExpr(field_name)
        callee = nodes.NameExpr(field_type_fullname.split('.')[-1])
        callee.fullname = field_type_fullname
        call = nodes.CallExpr(callee, [], [], [])
        items.append((key, call))
    lvalue = nodes.NameExpr('fields')
    return nodes.AssignmentStmt([lvalue], nodes.DictExpr(items))


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


class TestGetFieldsDictExpr(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def test_finds_fields_dict(self):
        assignment = _make_fields_assignment(
            ('id', 'oslo_versionedobjects.fields.IntegerField'),
        )
        ctx = _make_ctx('MyObj', [assignment])
        result = self.plugin._get_fields_dict_expr(ctx)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, nodes.DictExpr)

    def test_returns_none_when_no_fields_assignment(self):
        ctx = _make_ctx('MyObj', [])
        result = self.plugin._get_fields_dict_expr(ctx)
        self.assertIsNone(result)

    def test_returns_none_when_multiple_fields_assignments(self):
        ctx = _make_ctx(
            'MyObj',
            [
                _make_fields_assignment(
                    ('id', 'oslo_versionedobjects.fields.IntegerField')
                ),
                _make_fields_assignment(
                    ('name', 'oslo_versionedobjects.fields.StringField')
                ),
            ],
        )
        result = self.plugin._get_fields_dict_expr(ctx)
        self.assertIsNone(result)

    def test_ignores_assignments_to_other_names(self):
        other_lvalue = nodes.NameExpr('not_fields')
        other_assignment = nodes.AssignmentStmt(
            [other_lvalue], nodes.DictExpr([])
        )
        fields_assignment = _make_fields_assignment(
            ('id', 'oslo_versionedobjects.fields.IntegerField'),
        )
        ctx = _make_ctx('MyObj', [other_assignment, fields_assignment])
        result = self.plugin._get_fields_dict_expr(ctx)
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
            {},
        )
        self.assertEqual(expected, result)

    def test_returns_any_when_field_type_not_found(self):
        ctx = mock.MagicMock()
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        result = self.plugin._get_python_type_from_ovo_field_type(
            ctx,
            'oslo_versionedobjects.fields.UnknownField',
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
            {'nullable': nodes.NameExpr('False')},
        )
        self.assertNotIsInstance(result, types.UnionType)


class TestGenerateOvoFieldDefs(test.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = _make_plugin()

    def _make_api_ctx(self, name, statements, field_python_type):
        """Return a ClassDefContext with a fully mocked API.

        Builds a real ``nodes.TypeInfo`` for the field class so that the
        ``isinstance(..., nodes.TypeInfo)`` assertion inside the plugin is
        satisfied.
        """
        ctx = _make_ctx(name, statements)
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
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        self.plugin.generate_ovo_field_defs(ctx)
        self.assertIn('magic', ctx.cls.info.names)
        sym_node = ctx.cls.info.names['magic']
        self.assertIsInstance(sym_node.node.type, types.AnyType)
