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

"""Integration tests for the mypy plugin.

These tests run mypy programmatically against fixture files in the
``test_data/`` directory and verify that field types are inferred correctly
by the plugin.

Expected types are declared as inline ``# N: Revealed type is "..."``
annotations alongside each ``reveal_type()`` call in the fixture files,
mirroring the convention used by mypy's own test harness. The test
infrastructure parses those annotations and compares them against the
structured JSON output from mypy, avoiding fragile stdout regex parsing.
"""

import json
import pathlib
import re
import tempfile
from typing import TypedDict

import mypy.api
from oslo_versionedobjects import test


class _MypyMessage(TypedDict):
    file: str
    line: int
    column: int
    end_line: int
    end_column: int
    message: str
    hint: str | None
    code: str | None
    severity: str


# Absolute path to the project root (contains pyproject.toml with the plugin
# configuration).
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent.resolve()
_TEST_DATA_DIR = pathlib.Path(__file__).parent / 'test_data'


def _run_mypy(fixture_name: str) -> tuple[list[_MypyMessage], int]:
    """Run mypy on a fixture file and return (messages, exit_code).

    Messages is the full list of structured JSON objects emitted by mypy
    (one per stdout line).  Each dict has at least ``severity``, ``line``,
    and ``message`` keys.
    """
    fixture_path = _TEST_DATA_DIR / fixture_name
    with tempfile.TemporaryDirectory() as cache_dir:
        stdout, _stderr, exit_code = mypy.api.run(
            [
                '--no-incremental',
                '--cache-dir',
                cache_dir,
                '--output',
                'json',
                '--config-file',
                str(_PROJECT_ROOT / 'pyproject.toml'),
                str(fixture_path),
            ]
        )
    messages: list[_MypyMessage] = [
        json.loads(line) for line in stdout.splitlines() if line.strip()
    ]
    return messages, exit_code


def _get_expected_notes(fixture_name: str) -> dict[int, str]:
    """Return ``{line_number: expected_message}`` from ``# N:`` annotations.

    Scans the fixture file for inline comments of the form::

        reveal_type(obj.x)  # N: Revealed type is "str"

    and returns a mapping from the 1-based line number to the expected note
    message string.
    """
    fixture_path = _TEST_DATA_DIR / fixture_name
    notes: dict[int, str] = {}
    for lineno, line in enumerate(
        fixture_path.read_text().splitlines(), start=1
    ):
        m = re.search(r'#\s*N:\s*(.+)', line)
        if m:
            notes[lineno] = m.group(1).strip()
    return notes


class TestMypyIntegration(test.TestCase):
    def assertNoErrors(self, messages: list[_MypyMessage]) -> None:
        errors = [m for m in messages if m['severity'] == 'error']
        self.assertEqual([], errors, f"Unexpected mypy errors: {errors}")

    def assertNotes(self, fixture_name: str) -> None:
        """Assert that mypy emits the notes declared in the fixture file."""
        messages, _exit_code = _run_mypy(fixture_name)
        self.assertNoErrors(messages)

        actual = {
            m['line']: m['message']
            for m in messages
            if m['severity'] == 'note'
            and m['line'] > 0
            and m['message'].startswith('Revealed type is')
        }

        for lineno, expected_msg in _get_expected_notes(fixture_name).items():
            self.assertIn(
                lineno,
                actual,
                f"No reveal_type note at line {lineno} of {fixture_name}",
            )
            self.assertEqual(
                expected_msg,
                actual[lineno],
                f"Wrong revealed type at line {lineno} of {fixture_name}",
            )

    def test_empty_fields(self):
        """A model with no fields should be accepted without errors."""
        messages, _exit_code = _run_mypy('empty_fields.py')
        self.assertNoErrors(messages)

    def test_basic_autotyped_fields(self):
        """Standard AutoTypedField subclasses should map to the right types."""
        self.assertNotes('basic_fields.py')

    def test_subclassing_inherits_parent_fields(self):
        """A child class should expose fields defined on the parent class."""
        self.assertNotes('subclassing.py')

    def test_timestamp_mixin_fields(self):
        """Fields from base.TimestampedObject are inherited correctly."""
        self.assertNotes('timestamp_mixin.py')

    def test_compound_fields(self):
        """AutoTypedField compound types infer exact container element types.

        Raw Field(List/Dict/Set(...)) wrappers fall back to Any because the
        plugin only resolves types through the AutoTypedField generic
        parameter.
        """
        self.assertNotes('compound_fields.py')

    def test_enum_fields(self):
        """Enum fields resolve to Any because BaseEnumField is typed Any."""
        self.assertNotes('enum_fields.py')

    def test_object_fields(self):
        """ObjectField resolves to the concrete named class, not the base."""
        self.assertNotes('object_fields.py')
