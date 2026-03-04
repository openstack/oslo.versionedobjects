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
    """

    def __init__(self, options: _options.Options) -> None:
        super().__init__(options)

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
        return None

    def _get_fields_dict_expr(
        self, ctx: _plugin.ClassDefContext
    ) -> nodes.DictExpr | None:
        # defs is the Block of the class definition
        fields_assignments = [
            statement
            for statement in ctx.cls.defs.body
            if isinstance(statement, nodes.AssignmentStmt)
            and
            # could be multiple lvalues and each can assign to 'fields'
            isinstance(statement.lvalues[0], nodes.NameExpr)
            and statement.lvalues[0].name == "fields"
        ]

        # what if there are more than that?
        if len(fields_assignments) == 1:
            fields_assignment = fields_assignments[0]
            assert isinstance(fields_assignment.rvalue, nodes.DictExpr)
            return fields_assignment.rvalue

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

    def _get_python_type_from_ovo_field_type(
        self,
        ctx: _plugin.ClassDefContext,
        ovo_field_type_name: str,
        args: dict[str, nodes.Expression],
    ) -> types.Type:

        try:
            field_symbol = ctx.api.lookup_fully_qualified_or_none(
                ovo_field_type_name
            )
            assert field_symbol is not None
            assert field_symbol.node is not None
            assert isinstance(field_symbol.node, nodes.TypeInfo)
            assert "MYPY_TYPE" in field_symbol.node.names
            assert field_symbol.node.names["MYPY_TYPE"] is not None
            assert isinstance(
                field_symbol.node.names["MYPY_TYPE"].node, nodes.Var
            )
            assert field_symbol.node.names["MYPY_TYPE"].node.type is not None

            type = field_symbol.node.names["MYPY_TYPE"].node.type

            if "nullable" in args and ctx.api.parse_bool(args["nullable"]):
                return types.UnionType([type, types.NoneType()])

            return type
        except Exception as e:
            self.log(
                f"looking up {ovo_field_type_name} got exception {str(e)}"
            )

        # defaults to Any if the stub is incomplete
        return types.AnyType(types.TypeOfAny.implementation_artifact)

    def _add_ovo_members_to_class(
        self, ctx: _plugin.ClassDefContext, fields_def: nodes.DictExpr
    ) -> None:

        for k, v in fields_def.items:
            # This means we does not support the case when the name of the
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

            # TODO(gibi): make these proper errors
            assert isinstance(v, nodes.CallExpr)
            assert isinstance(v.callee, (nodes.MemberExpr, nodes.NameExpr))
            assert v.callee.fullname is not None
            args = {
                arg_name: arg
                for arg, arg_name in zip(v.args, v.arg_names)
                if arg_name is not None  # skip positional args
            }

            field_type_name = v.callee.fullname

            field_type = self._get_python_type_from_ovo_field_type(
                ctx, field_type_name, args
            )

            # insert a typed field definition to the current class
            self._add_member_to_class(field_name, field_type, ctx.cls.info)

    def generate_ovo_field_defs(self, ctx: _plugin.ClassDefContext) -> None:
        # check if there is a fields dict assignment in the class body
        fields_dict_expr = self._get_fields_dict_expr(ctx)
        if not fields_dict_expr:
            # No 'fields' definition in body
            return

        if not isinstance(fields_dict_expr, nodes.DictExpr):
            ctx.api.fail(
                "oslo versioned object `fields` definition should be a dict",
                fields_dict_expr,
            )

        # add a typed field def per `fields` dict k-v pair.
        self._add_ovo_members_to_class(ctx, fields_dict_expr)

    def log(self, msg: str) -> None:
        if self.options.verbosity > 0:
            print("LOG:  OsloVersionedObjectPlugin: " + msg)


def plugin(version: str) -> type[_plugin.Plugin]:
    return OsloVersionedObjectPlugin
