# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Utilities and helper functions."""

import functools
import logging

import six

from oslo_versionedobjects._i18n import _
from oslo_versionedobjects import exception

LOG = logging.getLogger(__name__)


def convert_version_to_int(version):
    try:
        if isinstance(version, six.string_types):
            version = convert_version_to_tuple(version)
        if isinstance(version, tuple):
            return functools.reduce(lambda x, y: (x * 1000) + y, version)
    except Exception:
        msg = _("Hypervisor version %s is invalid.") % version
        raise exception.VersionedObjectsException(msg)


def convert_version_to_str(version_int):
    version_numbers = []
    factor = 1000
    while version_int != 0:
        version_number = version_int - (version_int // factor * factor)
        version_numbers.insert(0, str(version_number))
        version_int = version_int // factor

    return '.'.join(map(str, version_numbers))


def convert_version_to_tuple(version_str):
    return tuple(int(part) for part in version_str.split('.'))
