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

"""Base classes for our unit tests."""

import os
from unittest import mock

import fixtures
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error
import testtools

from oslo_versionedobjects.tests import obj_fixtures


CONF = cfg.CONF


class TestingException(Exception):
    pass


def _patch_mock_to_raise_for_invalid_assert_calls():
    def raise_for_invalid_assert_calls(wrapped):
        def wrapper(_self, name):
            valid_asserts = [
                'assert_called_with',
                'assert_called_once_with',
                'assert_has_calls',
                'assert_any_calls',
            ]

            if name.startswith('assert') and name not in valid_asserts:
                raise AttributeError(
                    f'{name} is not a valid mock assert method'
                )

            return wrapped(_self, name)

        return wrapper

    mock.Mock.__getattr__ = raise_for_invalid_assert_calls(
        mock.Mock.__getattr__
    )


# NOTE(gibi): needs to be called only once at import time
# to patch the mock lib
_patch_mock_to_raise_for_invalid_assert_calls()


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    REQUIRES_LOCKING = False

    TIMEOUT_SCALING_FACTOR = 1

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super().setUp()
        self.useFixture(
            obj_fixtures.Timeout(
                os.environ.get('OS_TEST_TIMEOUT', 0),
                self.TIMEOUT_SCALING_FACTOR,
            )
        )

        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())
        self.useFixture(obj_fixtures.TranslationFixture())
        self.useFixture(logging_error.get_logging_handle_error_fixture())

        self.useFixture(obj_fixtures.OutputStreamCapture())

        self.useFixture(obj_fixtures.StandardLogging())

        # NOTE(sdague): because of the way we were using the lock
        # wrapper we eneded up with a lot of tests that started
        # relying on global external locking being set up for them. We
        # consider all of these to be *bugs*. Tests should not require
        # global external locking, or if they do, they should
        # explicitly set it up themselves.
        #
        # The following REQUIRES_LOCKING class parameter is provided
        # as a bridge to get us there. No new tests should be added
        # that require it, and existing classes and tests should be
        # fixed to not need it.
        if self.REQUIRES_LOCKING:
            lock_path = self.useFixture(fixtures.TempDir()).path
            self.fixture = self.useFixture(
                config_fixture.Config(lockutils.CONF)
            )
            self.fixture.config(lock_path=lock_path, group='oslo_concurrency')

        # NOTE(blk-u): WarningsFixture must be after the Database fixture
        # because sqlalchemy-migrate messes with the warnings filters.
        self.useFixture(obj_fixtures.WarningsFixture())

        self.addCleanup(self._clear_attrs)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))

    def _clear_attrs(self):
        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__.keys() if k[0] != '_']:
            del self.__dict__[key]
