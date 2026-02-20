# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
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

"""VersionedObjects base exception handling.

Includes decorator for re-raising VersionedObjects-type exceptions.

SHOULD include dedicated exception logging.

"""

from collections.abc import Callable
import functools
import inspect
import logging
from typing import Any, Concatenate, ParamSpec, TypeVar

from oslo_config import cfg
from oslo_utils import excutils

from oslo_versionedobjects._i18n import _

LOG: logging.Logger = logging.getLogger(__name__)

exc_log_opts: list[cfg.Opt] = [
    cfg.BoolOpt(
        'fatal_exception_format_errors',
        default=False,
        help='Make exception message format errors fatal',
    ),
]

CONF: cfg.ConfigOpts = cfg.CONF
CONF.register_opts(exc_log_opts, group='oslo_versionedobjects')


def _cleanse_dict(original: dict[str, Any]) -> dict[str, Any]:
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return {k: v for k, v in original.items() if "_pass" not in k}


_F = TypeVar('_F', bound=Callable[..., Any])

P = ParamSpec('P')
R = TypeVar('R')


def wrap_exception(
    notifier: Any = None, get_notifier: Callable[[], Any] | None = None
) -> Callable[
    [Callable[Concatenate[Any, P], R]],
    Callable[Concatenate[Any, P], R | None],
]:
    """Catch all exceptions in wrapped method

    This decorator wraps a method to catch any exceptions that may
    get thrown. It also optionally sends the exception to the notification
    system.
    """

    def inner(
        f: Callable[Concatenate[Any, P], R],
    ) -> Callable[Concatenate[Any, P], R | None]:
        def wrapped(
            self: Any, /, context: Any, *args: P.args, **kw: P.kwargs
        ) -> R | None:
            # Don't store self or context in the payload, it now seems to
            # contain confidential information.
            try:
                return f(self, context, *args, **kw)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    if notifier or get_notifier:
                        payload: dict[str, Any] = dict(exception=e)
                        call_dict = inspect.getcallargs(
                            f, self, context, *args, **kw
                        )
                        cleansed = _cleanse_dict(call_dict)
                        payload.update({'args': cleansed})

                        # If f has multiple decorators, they must use
                        # functools.wraps to ensure the name is
                        # propagated.
                        event_type = f.__name__

                        if notifier:
                            actual_notifier = notifier
                        else:
                            # get_notifier must be set since we're in
                            # the 'if notifier or get_notifier' block
                            actual_notifier = get_notifier()  # type: ignore[misc]
                        actual_notifier.error(context, event_type, payload)
                return None

        return functools.wraps(f)(wrapped)  # type: ignore[return-value]

    return inner


class VersionedObjectsException(Exception):
    """Base VersionedObjects Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.
    """

    msg_fmt = _("An unknown exception occurred.")

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = 500
            except AttributeError:
                pass

        if not message:
            try:
                message = self.msg_fmt % kwargs
            except Exception:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception('Exception in string format operation')
                for name, value in kwargs.items():
                    LOG.error(f"{name}: {value}")  # noqa

                if CONF.oslo_versionedobjects.fatal_exception_format_errors:
                    raise
                else:
                    # at least get the core message out if something happened
                    message = self.msg_fmt

        super().__init__(message)

    def format_message(self) -> str:
        # NOTE(mrodden): use the first argument to the python Exception object
        # which should be our full VersionedObjectsException message,
        # (see __init__)
        return str(self.args[0])


class ObjectActionError(VersionedObjectsException):
    msg_fmt = _('Object action %(action)s failed because: %(reason)s')


class ObjectFieldInvalid(VersionedObjectsException):
    msg_fmt = _('Field %(field)s of %(objname)s is not an instance of Field')


class OrphanedObjectError(VersionedObjectsException):
    msg_fmt = _('Cannot call %(method)s on orphaned %(objtype)s object')


class IncompatibleObjectVersion(VersionedObjectsException):
    msg_fmt = _(
        'Version %(objver)s of %(objname)s is not supported, '
        'supported version is %(supported)s'
    )


class ReadOnlyFieldError(VersionedObjectsException):
    msg_fmt = _('Cannot modify readonly field %(field)s')


class UnsupportedObjectError(VersionedObjectsException):
    msg_fmt = _('Unsupported object type %(objtype)s')


class EnumRequiresValidValuesError(VersionedObjectsException):
    msg_fmt = _('Enum fields require a list of valid_values')


class EnumValidValuesInvalidError(VersionedObjectsException):
    msg_fmt = _('Enum valid values are not valid')


class EnumFieldInvalid(VersionedObjectsException):
    msg_fmt = _('%(typename)s in %(fieldname)s is not an instance of Enum')


class EnumFieldUnset(VersionedObjectsException):
    msg_fmt = _('%(fieldname)s missing field type')


class InvalidTargetVersion(VersionedObjectsException):
    msg_fmt = _('Invalid target version %(version)s')


class TargetBeforeSubobjectExistedException(VersionedObjectsException):
    msg_fmt = _("No subobject existed at version %(target_version)s")


class UnregisteredSubobject(VersionedObjectsException):
    msg_fmt = _(
        "%(child_objname)s is referenced by %(parent_objname)s but "
        "is not registered"
    )
