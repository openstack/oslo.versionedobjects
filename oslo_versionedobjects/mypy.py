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

from collections.abc import Callable
import os

from mypy import nodes
from mypy import options as _options
from mypy import plugin as _plugin
from mypy import types


def _fields_dict_from_body(
    body: list[nodes.Statement],
) -> nodes.DictExpr | None:
    """Return the first ``fields = {...}`` DictExpr found in a class body."""
    for statement in body:
        if (
            isinstance(statement, nodes.AssignmentStmt)
            and isinstance(statement.lvalues[0], nodes.NameExpr)
            and statement.lvalues[0].name == "fields"
            and isinstance(statement.rvalue, nodes.DictExpr)
        ):
            return statement.rvalue
    return None


class OsloVersionedObjectPlugin(_plugin.Plugin):
    """A mypy plugin for Oslo VersionedObjects

    The goal of this plugin to add typing information to o.vos during mypy
    static analysis. So that mypy can detect type errors in codes involving
    o.vos.

    It triggers for every class that is decorated with one of the
    VersionedObjectRegistry decorator that generates the o.vo fields runtime
    (e.g. register, register_if, objectify). Then analyze the `fields`
    declaration in the class body to gather the o.vo fields. Then maps the
    type of the field to python types and insert such typed field definition
    to the class definition.

    The plugin also handles inherited fields (e.g. from TimestampedObject
    mixins) by caching each class's fields dict while its body is still
    intact, then using that cache when processing subclasses.
    """

    def __init__(self, options: _options.Options) -> None:
        super().__init__(options)
        # Cache of class fullname -> fields DictExpr, populated by
        # _cache_fields while each class body is still accessible.
        self._fields_cache: dict[str, nodes.DictExpr] = {}

    def get_class_decorator_hook(
        self, fullname: str
    ) -> Callable[[_plugin.ClassDefContext], None] | None:
        dec_classes = os.environ.get(
            "OVO_MYPY_DECORATOR_CLASSES", "VersionedObjectRegistry"
        )
        if any(dec_class in fullname for dec_class in dec_classes.split()):
            return self.generate_ovo_field_defs
        return None

    def get_base_class_hook(
        self, fullname: str
    ) -> Callable[[_plugin.ClassDefContext], None] | None:
        base_classes = os.environ.get(
            "OVO_MYPY_BASE_CLASSES", "VersionedObject"
        )
        if any(base_class in fullname for base_class in base_classes.split()):
            return self.generate_ovo_field_defs
        # Cache field dicts for all classes while their bodies are intact.
        # This is needed to support MRO traversal for mixin parent classes
        # (e.g. TimestampedObject) whose bodies are empty by the time we
        # process subclasses.
        if fullname == "builtins.object":
            return self._cache_fields
        return None

    def _cache_fields(self, ctx: _plugin.ClassDefContext) -> None:
        """Cache the fields dict from this class's body while it is intact."""
        fields = _fields_dict_from_body(ctx.cls.defs.body)
        if fields is not None:
            self._fields_cache[ctx.cls.info.fullname] = fields

    def _get_fields_dict_from_type_info(
        self, type_info: nodes.TypeInfo
    ) -> nodes.DictExpr | None:
        """Get the 'fields' dict expression for a class in the MRO.

        Checks the cache first (populated by _cache_fields), then falls back
        to reading from the class body (which is only non-empty for the class
        currently being processed).
        """
        if type_info.fullname in self._fields_cache:
            return self._fields_cache[type_info.fullname]
        return _fields_dict_from_body(type_info.defn.defs.body)

    def _add_member_to_class(
        self, member_name: str, member_type: types.Type, clazz: nodes.TypeInfo
    ) -> None:
        """Add a new member to the class.

        Add a variable with given name and type to the symbol table of a
        class. This also takes care about setting necessary attributes on the
        variable node.
        """
        var = nodes.Var(member_name)
        var.info = clazz
        var._fullname = clazz.fullname + "." + member_name
        var.type = member_type
        clazz.names[member_name] = nodes.SymbolTableNode(nodes.MDEF, var)
        self.log(
            f"Defined o.vo field: {clazz.fullname}.{member_name} as "
            f"{member_type}"
        )

    def _apply_nullable(
        self,
        field_type: types.Type,
        ctx: _plugin.ClassDefContext,
        kwargs: dict[str, nodes.Expression],
    ) -> types.Type:
        if "nullable" in kwargs and ctx.api.parse_bool(kwargs["nullable"]):
            return types.UnionType([field_type, types.NoneType()])
        return field_type

    def _get_python_type_from_ovo_field_type(
        self,
        ctx: _plugin.ClassDefContext,
        ovo_field_type_name: str,
        args: dict[str, nodes.Expression],
    ) -> types.Type:
        # lookup_fully_qualified_or_none requires a dotted name (bare names
        # like a local callable would raise ValueError inside mypy)
        if '.' not in ovo_field_type_name:
            self.log(f"Unqualified field type name: {ovo_field_type_name}")
            return types.AnyType(types.TypeOfAny.implementation_artifact)

        field_symbol = ctx.api.lookup_fully_qualified_or_none(
            ovo_field_type_name
        )
        if field_symbol is None or not isinstance(
            field_symbol.node, nodes.TypeInfo
        ):
            self.log(f"Could not find field type {ovo_field_type_name}")
            return types.AnyType(types.TypeOfAny.implementation_artifact)

        mypy_type_node = field_symbol.node.names.get("MYPY_TYPE")
        if (
            mypy_type_node is None
            or not isinstance(mypy_type_node.node, nodes.Var)
            or mypy_type_node.node.type is None
        ):
            self.log(f"No MYPY_TYPE defined on {ovo_field_type_name}")
            return types.AnyType(types.TypeOfAny.implementation_artifact)

        return self._apply_nullable(mypy_type_node.node.type, ctx, args)

    def _add_ovo_members_to_class(
        self,
        ctx: _plugin.ClassDefContext,
        fields_def: nodes.DictExpr,
        processed_fields: set[str],
    ) -> None:

        for k, v in fields_def.items:
            # This means we do not support the case when the name of the
            # field is calculated e.g.:
            # fields = {'first' + 'name': fields.StringField()}
            if not isinstance(k, nodes.StrExpr):
                ctx.api.fail(
                    "oslo.versionedobject `fields` dict should have string "
                    "literal keys",
                    ctx.cls,
                )
                continue

            field_name = k.value

            # Skip fields already defined by a more derived class in the MRO
            if field_name in processed_fields:
                continue
            processed_fields.add(field_name)

            if (
                not isinstance(v, nodes.CallExpr)
                or not isinstance(v.callee, (nodes.MemberExpr, nodes.NameExpr))
                or v.callee.fullname is None
            ):
                self.log(
                    f"Skipping field {field_name}: unexpected AST structure"
                )
                field_type: types.Type = types.AnyType(
                    types.TypeOfAny.implementation_artifact
                )
            else:
                args = {
                    arg_name: arg
                    for arg, arg_name in zip(v.args, v.arg_names)
                    if arg_name is not None  # skip positional args
                }

                field_type = self._get_python_type_from_ovo_field_type(
                    ctx, v.callee.fullname, args
                )

            self._add_member_to_class(field_name, field_type, ctx.cls.info)

    def generate_ovo_field_defs(self, ctx: _plugin.ClassDefContext) -> None:
        # Process fields from this class and all inherited classes via MRO,
        # so that inherited fields (e.g. from TimestampedObject) are included.
        processed_fields: set[str] = set()

        for type_info in ctx.cls.info.mro:
            fields_dict_expr = self._get_fields_dict_from_type_info(type_info)
            if fields_dict_expr is None:
                continue

            # add a typed field def per `fields` dict k-v pair
            self._add_ovo_members_to_class(
                ctx, fields_dict_expr, processed_fields
            )

    def log(self, msg: str) -> None:
        if self.options.verbosity > 0:
            print("LOG:  OsloVersionedObjectPlugin: " + msg)


def plugin(version: str) -> type[_plugin.Plugin]:
    return OsloVersionedObjectPlugin
