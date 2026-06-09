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
    mixins) by traversing the MRO and reading each parent class's ``fields``
    dict directly from its body. Parent class bodies have already had semantic
    analysis applied (and so have fully-resolved ``fullname`` attributes on
    their AST nodes) by the time subclasses are processed.
    """

    def get_class_decorator_hook(
        self, fullname: str
    ) -> Callable[[_plugin.ClassDefContext], None] | None:
        dec_classes = os.environ.get(
            "OVO_MYPY_DECORATOR_CLASSES", "VersionedObjectRegistry"
        )
        if any(dec_class in fullname for dec_class in dec_classes.split()):
            return self.generate_ovo_field_defs
        return None

    def get_class_decorator_hook_2(
        self, fullname: str
    ) -> Callable[[_plugin.ClassDefContext], bool] | None:
        dec_classes = os.environ.get(
            "OVO_MYPY_DECORATOR_CLASSES", "VersionedObjectRegistry"
        )
        if any(dec_class in fullname for dec_class in dec_classes.split()):
            return self.generate_ovo_field_defs_2
        return None

    def get_base_class_hook(
        self, fullname: str
    ) -> Callable[[_plugin.ClassDefContext], None] | None:
        base_classes = os.environ.get(
            "OVO_MYPY_BASE_CLASSES", "VersionedObject VersionedObjectMixin"
        )
        if any(base_class in fullname for base_class in base_classes.split()):
            return self.generate_ovo_field_defs
        return None

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

    def _resolve_ovo_class_type(
        self,
        ctx: _plugin.ClassDefContext,
        class_name: str,
    ) -> types.Type | None:
        """Look up a versioned object class by name and return its mypy Type.

        Tries the current module scope first, then falls back to searching all
        loaded modules.
        """
        sym = ctx.api.lookup_qualified(
            class_name, ctx.cls, suppress_errors=True
        )
        if sym is not None and isinstance(sym.node, nodes.TypeInfo):
            return types.Instance(sym.node, [])

        for module in ctx.api.modules.values():
            node = module.names.get(class_name)
            if node is not None and isinstance(node.node, nodes.TypeInfo):
                return types.Instance(node.node, [])

        return None

    def _get_python_type_from_ovo_field_type(
        self,
        ctx: _plugin.ClassDefContext,
        ovo_field_type_name: str,
        args: list[nodes.Expression],
        kwargs: dict[str, nodes.Expression],
    ) -> types.Type | None:
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

        field_fullname = field_symbol.node.fullname

        # ObjectField and ListOfObjectsField take the target class name as a
        # positional string arg rather than a generic parameter
        if field_fullname == 'oslo_versionedobjects.fields.ListOfObjectsField':
            base_type: types.Type | None = None
            if args and isinstance(args[0], nodes.StrExpr):
                resolved = self._resolve_ovo_class_type(ctx, args[0].value)
                if resolved is not None:
                    list_sym = ctx.api.lookup_fully_qualified_or_none(
                        'builtins.list'
                    )
                    if list_sym and isinstance(list_sym.node, nodes.TypeInfo):
                        base_type = types.Instance(list_sym.node, [resolved])
            if base_type is None:
                self.log(
                    f"Could not resolve object type for {ovo_field_type_name}"
                )
                return None
            return self._apply_nullable(base_type, ctx, kwargs)

        if field_fullname == 'oslo_versionedobjects.fields.ObjectField':
            if args and isinstance(args[0], nodes.StrExpr):
                resolved = self._resolve_ovo_class_type(ctx, args[0].value)
                if resolved is not None:
                    return self._apply_nullable(resolved, ctx, kwargs)
            self.log(
                f"Could not resolve object type for {ovo_field_type_name}"
            )
            return None

        # AutoTypedField is a proper generic. We can retrieve its type from
        # this.
        for class_info in field_symbol.node.mro:
            for base in class_info.bases:
                if (
                    isinstance(base, types.Instance)
                    and base.type.fullname
                    == 'oslo_versionedobjects.fields.AutoTypedField'
                    and base.args
                    and not isinstance(base.args[0], types.TypeVarType)
                ):
                    return self._apply_nullable(base.args[0], ctx, kwargs)

        return types.AnyType(types.TypeOfAny.implementation_artifact)

    def _add_ovo_members_to_class(
        self,
        ctx: _plugin.ClassDefContext,
        fields_def: nodes.DictExpr,
        processed_fields: set[str],
    ) -> bool:
        all_resolved = True

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
                or not v.callee.fullname
            ):
                self.log(
                    f"Skipping field {field_name}: unexpected AST structure"
                )
                field_type: types.Type = types.AnyType(
                    types.TypeOfAny.implementation_artifact
                )
            else:
                args = [
                    arg
                    for arg, arg_name in zip(v.args, v.arg_names)
                    if arg_name is None
                ]
                kwargs = {
                    arg_name: arg
                    for arg, arg_name in zip(v.args, v.arg_names)
                    if arg_name is not None
                }

                resolved = self._get_python_type_from_ovo_field_type(
                    ctx, v.callee.fullname, args, kwargs
                )
                if resolved is None:
                    all_resolved = False
                    field_type = types.AnyType(
                        types.TypeOfAny.implementation_artifact
                    )
                else:
                    field_type = resolved

            self._add_member_to_class(field_name, field_type, ctx.cls.info)

        return all_resolved

    def generate_ovo_field_defs(self, ctx: _plugin.ClassDefContext) -> None:
        self.generate_ovo_field_defs_2(ctx)

    def generate_ovo_field_defs_2(self, ctx: _plugin.ClassDefContext) -> bool:
        # Process fields from this class and all classes in its MRO whose
        # bodies are still available (i.e. same-file classes).  Cross-module
        # parent classes have their bodies cleared by mypy after their own
        # module is analyzed; their fields are instead picked up via mypy's
        # normal MRO attribute resolution because the plugin fires for those
        # classes too (via get_base_class_hook) while their bodies are intact.
        #
        # hook_2 callables can return False to request a retry, but we always
        # return True: by the time hook_2 fires all modules are loaded, so any
        # ObjectField target that is still unresolvable will remain so on
        # subsequent attempts.
        processed_fields: set[str] = set()

        for type_info in ctx.cls.info.mro:
            fields_dict_expr = _fields_dict_from_body(type_info.defn.defs.body)
            if fields_dict_expr is None:
                continue

            self._add_ovo_members_to_class(
                ctx, fields_dict_expr, processed_fields
            )

        return True

    def log(self, msg: str) -> None:
        if self.options.verbosity > 0:
            print("LOG:  OsloVersionedObjectPlugin: " + msg)


def plugin(version: str) -> type[_plugin.Plugin]:
    return OsloVersionedObjectPlugin
