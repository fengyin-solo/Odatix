# ********************************************************************** #
#                                Odatix                                  #
# ********************************************************************** #
#
# Copyright (C) 2022 Jonathan Saussereau
#
# This file is part of Odatix.
# Odatix is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Odatix is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Odatix. If not, see <https://www.gnu.org/licenses/>.
#

"""
"odatix config": read the settings of the workspace.

"odatix config get KEY" prints the value Odatix uses for one top-level setting
of the workspace settings file ("odatix.yml"): the value the file sets, or its
Odatix default when the file leaves the key out (or empty). The command never
writes to the file.
"""

import json

import odatix.lib.printc as printc
from odatix.lib.settings import OdatixSettings
from odatix.workspace.core import setting_defaults, setting_value

script_name = "odatix config"


def add_arguments(parser):
    parser.add_argument(
        "key", metavar="KEY",
        help='a top-level setting of the workspace settings file (e.g. "work_path", "result_path", "resource_guard")',
    )
    parser.add_argument(
        "--json", action="store_true",
        help='print the key and its value as JSON: {"key": ..., "value": ...}',
    )


def format_value(value):
    """
    A value as the text output prints it. Booleans read as YAML/JSON, lists and
    mappings as JSON, so the line keeps one value even when it holds spaces.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def get_setting(key, as_json=False):
    """
    Print one setting of the workspace of the current directory: the value the
    settings file sets, or its Odatix default. False when it could not be read
    or the key is not a setting.
    """
    settings_file = OdatixSettings.DEFAULT_SETTINGS_FILE
    # A missing file is not an error: every setting then holds its default, as
    # a directory about to be initialized looks to the workspace API. A file
    # that cannot be parsed is one, and already says what is wrong with it.
    data = OdatixSettings.get_settings_file_dict(settings_file, silent=True)
    if data is None:
        return False
    try:
        value = setting_value(key, data)
    except KeyError:
        printc.error('unknown setting "' + key + '"', script_name)
        printc.note("the settings of " + settings_file + " are: " + ", ".join(setting_defaults()), script_name)
        return False
    if as_json:
        print(json.dumps({"key": key, "value": value}, indent=2, ensure_ascii=False, default=str))
    else:
        print(key + ": " + format_value(value))
    return True


def main(args):
    """What "odatix config" does (only "get" so far)."""
    if getattr(args, "config_action", None) == "get":
        return get_setting(args.key, as_json=args.json)
    printc.error('nothing to do: use "odatix config get KEY"', script_name)
    return False
