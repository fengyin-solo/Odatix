"""
"odatix config get KEY": the value Odatix uses for one top-level setting of
odatix.yml -- the one the file sets, or its Odatix default. Read-only.
"""

import json

import pytest

from test_cli import run_cli

import odatix.odatix_main as odatix_main
from odatix.lib.settings import OdatixSettings
from odatix.workspace import open_workspace
from odatix.workspace.core import WorkspaceSettings, setting_defaults, setting_value

SETTINGS_FILE = OdatixSettings.DEFAULT_SETTINGS_FILE


######################################
# Parser
######################################

def test_parser_get():
    args = odatix_main.ArgParser.parse_arguments(["config", "get", "work_path", "--json"])
    assert args.command == "config"
    assert args.config_action == "get"
    assert args.key == "work_path"
    assert args.json is True


def test_parser_get_defaults():
    args = odatix_main.ArgParser.parse_arguments(["config", "get", "result_path"])
    assert args.key == "result_path"
    assert args.json is False
    assert args.nobanner is False


def test_config_without_an_action_is_an_error():
    with pytest.raises(SystemExit):
        odatix_main.ArgParser.parse_arguments(["config"])


def test_config_is_listed_as_a_workspace_command():
    grouped = dict((group, names) for group, names in odatix_main.COMMAND_GROUPS)
    assert "config" in grouped["Workspace"]
    assert "config" in odatix_main.COMMANDS


######################################
# Helpers
######################################

def write_settings(directory, text):
    path = directory / SETTINGS_FILE
    path.write_text(text, encoding="utf-8")
    return path


def run_config(capsys, *argv):
    args = odatix_main.ArgParser.parse_arguments(["config"] + list(argv))
    success = odatix_main.config_command.main(args)
    captured = capsys.readouterr()
    return success, captured.out


def run_main_exit(*argv):
    """The exit code odatix_main.main() stops with, for this command line."""
    with pytest.raises(SystemExit) as stop:
        odatix_main.main(odatix_main.ArgParser.parse_arguments(list(argv)))
    return stop.value.code


######################################
# File value
######################################

def test_get_reads_the_value_set_in_the_file(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "work_path: my_work\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "work_path")
    assert success
    assert out.strip() == "work_path: my_work"


def test_get_reads_non_string_values(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "resource_guard: false\ncpu_limit: 75\nwsl_tools: [vivado, verilator]\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "resource_guard")
    assert success and out.strip() == "resource_guard: false"
    success, out = run_config(capsys, "get", "cpu_limit")
    assert success and out.strip() == "cpu_limit: 75"
    success, out = run_config(capsys, "get", "wsl_tools")
    assert success and out.strip() == 'wsl_tools: ["vivado", "verilator"]'


######################################
# Default value
######################################

def test_get_falls_back_to_the_default_when_the_file_lacks_the_key(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "workspace: odatix\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "result_path")
    assert success
    assert out.strip() == "result_path: " + OdatixSettings.DEFAULT_RESULT_PATH


def test_get_uses_defaults_without_a_settings_file(in_tmp_dir, capsys):
    # A directory that holds no odatix.yml reads like an empty one: defaults.
    success, out = run_config(capsys, "get", "work_path")
    assert success
    assert out.strip() == "work_path: " + OdatixSettings.DEFAULT_WORK_PATH
    success, out = run_config(capsys, "get", "session_access")
    assert success and out.strip() == "session_access: user"


def test_an_empty_key_in_the_file_means_the_default(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "work_path:\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "work_path")
    assert success
    assert out.strip() == "work_path: " + OdatixSettings.DEFAULT_WORK_PATH


def test_former_key_names_are_still_read(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "simulation_settings_file: old_sim.yml\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "sim_settings_file")
    assert success
    assert "sim_settings_file: old_sim.yml" in out


######################################
# Unknown key
######################################

def test_an_unknown_key_fails(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "workspace: odatix\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "not_a_setting")
    assert not success
    assert "not_a_setting" in out
    # And the failure reaches the process as a non-zero exit status.
    assert run_main_exit("config", "get", "not_a_setting") != 0


def test_an_unknown_key_also_fails_without_a_file(in_tmp_dir, capsys):
    success, out = run_config(capsys, "get", "not_a_setting")
    assert not success
    assert "not_a_setting" in out


def test_an_invalid_settings_file_fails(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "work_path: [\n")
    monkeypatch.chdir(tmp_path)
    success, _out = run_config(capsys, "get", "work_path")
    assert not success


######################################
# JSON output
######################################

def test_json_outputs_the_file_value(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "work_path: my_work\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "work_path", "--json")
    assert success
    assert json.loads(out) == {"key": "work_path", "value": "my_work"}


def test_json_outputs_the_default_value(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "workspace: odatix\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "result_path", "--json")
    assert success
    assert json.loads(out) == {"key": "result_path", "value": OdatixSettings.DEFAULT_RESULT_PATH}


def test_json_outputs_typed_defaults(tmp_path, monkeypatch, capsys):
    write_settings(tmp_path, "workspace: odatix\n")
    monkeypatch.chdir(tmp_path)
    success, out = run_config(capsys, "get", "resource_guard", "--json")
    assert success and json.loads(out)["value"] is True
    success, out = run_config(capsys, "get", "wsl_tools", "--json")
    assert success and json.loads(out)["value"] == []


######################################
# Read-only
######################################

def test_the_command_never_modifies_the_file(tmp_path, monkeypatch, capsys):
    path = write_settings(tmp_path, "workspace: odatix\n# a comment kept as is\n")
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)

    assert run_config(capsys, "get", "work_path")[0]
    assert path.read_bytes() == before
    assert run_config(capsys, "get", "not_a_setting")[0] is False
    assert path.read_bytes() == before


######################################
# Python API
######################################

def test_every_declared_setting_has_a_default():
    defaults = setting_defaults()
    for spec in WorkspaceSettings.specs():
        if spec.stored:
            assert spec.key in defaults, "no default declared for " + spec.key


def test_setting_value_helper():
    assert setting_value("work_path", {"work_path": "x"}) == "x"
    assert setting_value("work_path", {}) == OdatixSettings.DEFAULT_WORK_PATH
    assert setting_value("work_path", None) == OdatixSettings.DEFAULT_WORK_PATH
    with pytest.raises(KeyError):
        setting_value("not_a_setting", {})


def test_workspace_setting_method(tmp_path):
    write_settings(tmp_path, "work_path: my_work\n")
    workspace = open_workspace(str(tmp_path))
    assert workspace.setting("work_path") == "my_work"
    assert workspace.setting("result_path") == OdatixSettings.DEFAULT_RESULT_PATH
    with pytest.raises(KeyError):
        workspace.setting("not_a_setting")


######################################
# Real entry point (subprocess smoke tests)
######################################

@pytest.mark.integration
class TestConfigSubprocess:
    def test_get_returns_the_file_value(self, example_workspace):
        result = run_cli("config", "get", "default_tool", cwd=str(example_workspace))
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "default_tool: vivado"

    def test_get_returns_a_default(self, example_workspace):
        result = run_cli("config", "get", "work_path", cwd=str(example_workspace))
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "work_path: " + OdatixSettings.DEFAULT_WORK_PATH

    def test_get_json(self, example_workspace):
        result = run_cli("config", "get", "result_path", "--json", cwd=str(example_workspace))
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {"key": "result_path", "value": OdatixSettings.DEFAULT_RESULT_PATH}

    def test_unknown_key_is_nonzero(self, example_workspace):
        result = run_cli("config", "get", "not_a_setting", cwd=str(example_workspace))
        assert result.returncode != 0

    def test_get_is_in_the_help(self):
        result = run_cli("-h")
        assert result.returncode == 0
        assert "config" in result.stdout
