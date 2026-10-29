"""
Tests for "odatix results inspect FILE": the read-only summary of a results
file (v2 and legacy v1), its JSON shape and its failure exit codes.
"""

import json
import os
import subprocess
import sys

import pytest

from conftest import SOURCES_DIR

import odatix.lib.results_cache as results_cache
import odatix.lib.results_schema as schema
import odatix.odatix_main as odatix_main
import odatix.components.inspect_results as inspect_results


######################################
# Fixtures
######################################


V2_WITH_UNITS = """\
schema: 2
units:
  Fmax: MHz
  Cycles: ""
results:
  - meta:
      type: fmax_synthesis
      tool: vivado
      target: target_a
      timestamp: "2025-09-02_18-12-30"
    metrics:
      Fmax: 450
  - meta:
      type: fmax_synthesis
      tool: vivado
      target: target_a
      timestamp: "2025-08-01_08-00-00"
    metrics:
      Fmax: 400
  - meta:
      type: simulation
      tool: verilator
      simulation: smoke
      timestamp: "2025-08-27_07-50-09"
    metrics:
      Cycles: 100
"""

V2_NO_UNITS = """\
schema: 2
results:
  - meta:
      type: simulation
      tool: verilator
      timestamp: "2025-03-03_10-00-00"
    metrics:
      Cycles: 100
"""

V2_EMPTY = """\
schema: 2
units: {}
results: []
"""

V1_SYNTH = """\
units:
  Fmax: MHz
fmax_synthesis:
  target_a:
    arch_a:
      cfg_a:
        Fmax: 450
        Param_Domains:
          __main__: cfg_a
          __timestamp__: "2024-12-31_23-59-59"
custom_freq_synthesis:
  target_a:
    arch_a:
      cfg_a:
        "50MHz":
          LUT_count: 3
"""

V1_WORKFLOW = """\
units:
  Total_time: s
workflows:
  wf:
    cfgkey:
      run_dir: /runs/1
      workflow_full: wf/cfg
      metrics:
        Total_time: 12
"""

UNKNOWN_YAML = "foo: bar\n"

# "results" is not a list: close to a v2 file but not one.
MALFORMED_V2 = "schema: 2\nresults: not-a-list\n"

CORRUPT_YAML = "results: [\n"


@pytest.fixture
def result_file(tmp_path):
  def write(name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path
  return write


def run_inspect(path, *extra):
  args = odatix_main.ArgParser.parse_arguments(["results", "inspect", str(path), *extra])
  return inspect_results.main(args)


def run_inspect_dispatch(path, *extra):
  """Through the same dispatch main() uses, as the command line does."""
  args = odatix_main.ArgParser.parse_arguments(["results", "inspect", str(path), *extra])
  return odatix_main.export_results_command(args)


def inspect_json(path):
  import contextlib
  import io

  buffer = io.StringIO()
  with contextlib.redirect_stdout(buffer):
    args = odatix_main.ArgParser.parse_arguments(["results", "inspect", str(path), "--json"])
    assert inspect_results.main(args)
  return json.loads(buffer.getvalue())


######################################
# summarize(): pure summary logic
######################################


class TestSummarize:
  def record(self, rtype, tool, metrics, timestamp=None):
    meta = {"type": rtype}
    if tool is not None:
      meta["tool"] = tool
    if timestamp is not None:
      meta["timestamp"] = timestamp
    return schema.make_record(meta, metrics)

  def test_counts_types_tools_metrics_and_range(self):
    results = schema.ResultsFile(
      units={"Fmax": "MHz"},
      records=[
        self.record("pnr", "vivado", {"Fmax": 1}, "2025-09-02_00-00-00"),
        self.record("fmax_synthesis", None, {"Fmax": 2}, "2025-01-01_00-00-00"),
        self.record("pnr", "genus", {"LUT": 7}, None),
      ],
      schema_detected=schema.FORMAT_V2,
    )
    summary = inspect_results.summarize(results)
    assert summary["records"] == 3
    assert summary["by_type"] == [
      {"type": "fmax_synthesis", "count": 1},
      {"type": "pnr", "count": 2},
    ]
    # A missing tool is reported as null, sorted before the named tools.
    assert summary["by_tool"] == [
      {"tool": None, "count": 1},
      {"tool": "genus", "count": 1},
      {"tool": "vivado", "count": 1},
    ]
    assert summary["metrics"] == [
      {"name": "Fmax", "unit": "MHz"},
      {"name": "LUT", "unit": None},
    ]
    assert summary["time_range"] == {
      "earliest": "2025-01-01_00-00-00",
      "latest": "2025-09-02_00-00-00",
    }

  def test_empty_records(self):
    results = schema.ResultsFile(units={}, records=[], schema_detected=schema.FORMAT_V2)
    summary = inspect_results.summarize(results)
    assert summary["records"] == 0
    assert summary["by_type"] == []
    assert summary["by_tool"] == []
    assert summary["metrics"] == []
    assert summary["time_range"] == {"earliest": None, "latest": None}

  def test_a_missing_unit_is_null_not_an_error(self):
    results = schema.ResultsFile(
      units={}, records=[self.record("pnr", "vivado", {"Area": 3})],
      schema_detected=schema.FORMAT_V2,
    )
    assert inspect_results.summarize(results)["metrics"] == [{"name": "Area", "unit": None}]

  def test_sorting_is_independent_of_record_order(self):
    records = [
      self.record("zzz_type", "zzz_tool", {"zzz_metric": 1}, "2025-05-05_00-00-00"),
      self.record("aaa_type", "aaa_tool", {"aaa_metric": 1}, "2024-05-05_00-00-00"),
      self.record("mmm_type", "mmm_tool", {"mmm_metric": 1}, "2026-05-05_00-00-00"),
    ]
    results = schema.ResultsFile(units={}, records=records, schema_detected=schema.FORMAT_V2)
    summary = inspect_results.summarize(results)
    assert [entry["type"] for entry in summary["by_type"]] == ["aaa_type", "mmm_type", "zzz_type"]
    assert [entry["tool"] for entry in summary["by_tool"]] == ["aaa_tool", "mmm_tool", "zzz_tool"]
    assert [entry["name"] for entry in summary["metrics"]] == ["aaa_metric", "mmm_metric", "zzz_metric"]
    assert summary["time_range"]["earliest"] == "2024-05-05_00-00-00"
    assert summary["time_range"]["latest"] == "2026-05-05_00-00-00"


######################################
# Files on disk: v2, v1, failures
######################################


class TestV2:
  def test_json_summary(self, result_file):
    path = result_file("v2.yml", V2_WITH_UNITS)
    payload = inspect_json(path)
    assert payload["report"] == "results_inspect"
    assert payload["version"] == inspect_results.JSON_VERSION == 1
    assert payload["file"] == str(path)
    assert payload["format"] == "v2"
    assert payload["records"] == 3
    assert payload["by_type"] == [
      {"type": "fmax_synthesis", "count": 2},
      {"type": "simulation", "count": 1},
    ]
    assert payload["by_tool"] == [
      {"tool": "verilator", "count": 1},
      {"tool": "vivado", "count": 2},
    ]
    assert payload["metrics"] == [
      {"name": "Cycles", "unit": ""},
      {"name": "Fmax", "unit": "MHz"},
    ]
    assert payload["time_range"] == {
      "earliest": "2025-08-01_08-00-00",
      "latest": "2025-09-02_18-12-30",
    }

  def test_human_summary(self, result_file, capsys):
    path = result_file("v2.yml", V2_WITH_UNITS)
    assert run_inspect(path)
    out = capsys.readouterr().out
    assert str(path) in out
    assert "v2 (current)" in out
    assert "fmax_synthesis" in out and "simulation" in out
    assert "vivado" in out and "verilator" in out
    assert "Fmax (MHz)" in out
    assert "2025-08-01_08-00-00 .. 2025-09-02_18-12-30" in out

  def test_missing_unit_is_reported_but_succeeds(self, result_file, capsys):
    path = result_file("no_units.yml", V2_NO_UNITS)
    payload = inspect_json(path)
    assert payload["metrics"] == [{"name": "Cycles", "unit": None}]
    assert run_inspect(path)
    out = capsys.readouterr().out
    assert "Cycles" in out and "no unit" in out

  def test_empty_records_succeed(self, result_file, capsys):
    path = result_file("empty.yml", V2_EMPTY)
    payload = inspect_json(path)
    assert payload["format"] == "v2"
    assert payload["records"] == 0
    assert payload["by_type"] == [] and payload["by_tool"] == [] and payload["metrics"] == []
    assert payload["time_range"] == {"earliest": None, "latest": None}
    assert run_inspect(path)
    out = capsys.readouterr().out
    assert "Records:" in out and "none" in out


class TestV1:
  def test_v1_synthesis(self, result_file):
    path = result_file("v1_synth.yml", V1_SYNTH)
    payload = inspect_json(path)
    assert payload["format"] == "v1_synth"
    assert payload["records"] == 2
    assert payload["by_type"] == [
      {"type": "custom_freq_synthesis", "count": 1},
      {"type": "fmax_synthesis", "count": 1},
    ]
    # v1 synthesis records carry no tool.
    assert payload["by_tool"] == [{"tool": None, "count": 2}]
    assert payload["metrics"] == [
      {"name": "Fmax", "unit": "MHz"},
      {"name": "LUT_count", "unit": None},
    ]
    assert payload["time_range"] == {
      "earliest": "2024-12-31_23-59-59",
      "latest": "2024-12-31_23-59-59",
    }

  def test_v1_workflow(self, result_file, capsys):
    path = result_file("v1_workflow.yml", V1_WORKFLOW)
    payload = inspect_json(path)
    assert payload["format"] == "v1_workflow"
    assert payload["records"] == 1
    assert payload["by_type"] == [{"type": "workflow", "count": 1}]
    assert payload["by_tool"] == [{"tool": None, "count": 1}]
    assert payload["metrics"] == [{"name": "Total_time", "unit": "s"}]
    assert payload["time_range"] == {"earliest": None, "latest": None}
    assert run_inspect(path)
    assert "v1 workflow (legacy, read-only)" in capsys.readouterr().out

  def test_a_v1_file_is_not_migrated(self, result_file):
    # Inspecting only reads: the v1 content on disk is byte-for-byte unchanged.
    path = result_file("v1_synth.yml", V1_SYNTH)
    before = path.read_bytes()
    assert run_inspect(path, "--json")
    assert path.read_bytes() == before


class TestFailures:
  def test_missing_file_fails(self, tmp_path, capsys):
    path = tmp_path / "nope.yml"
    assert not run_inspect(path)
    assert "does not exist" in capsys.readouterr().out
    assert run_inspect_dispatch(path) is False

  def test_corrupt_yaml_fails(self, result_file, capsys):
    path = result_file("corrupt.yml", CORRUPT_YAML)
    assert not run_inspect(path)
    assert "Cannot parse" in capsys.readouterr().out
    assert run_inspect_dispatch(path) is False

  def test_unknown_format_fails(self, result_file, capsys):
    path = result_file("unknown.yml", UNKNOWN_YAML)
    assert not run_inspect(path)
    assert "unknown format" in capsys.readouterr().out

  def test_structurally_broken_v2_fails(self, result_file, capsys):
    path = result_file("bad_v2.yml", MALFORMED_V2)
    assert not run_inspect(path)
    assert "unknown format" in capsys.readouterr().out

  def test_empty_file_fails(self, result_file, capsys):
    path = result_file("zero.yml", "")
    assert not run_inspect(path)
    assert "unknown format" in capsys.readouterr().out

  def test_a_directory_fails(self, tmp_path, capsys):
    assert not run_inspect(tmp_path)
    assert "does not exist" in capsys.readouterr().out


######################################
# JSON stability and read-only behavior
######################################


class TestJsonStability:
  def _scrambled_file(self, tmp_path):
    records = [
      schema.make_record(
        {"type": "pnr", "tool": "vivado", "timestamp": "2025-09-02_00-00-00"},
        {"Zeta": 9},
      ),
      schema.make_record(
        {"type": "fmax_synthesis", "timestamp": "2025-01-01_00-00-00"},
        {"alpha": 1, "Fmax": 450},
      ),
      schema.make_record(
        {"type": "workflow", "tool": "genus", "timestamp": "2025-06-06_00-00-00"},
        {"Fmax": 100},
      ),
    ]
    path = tmp_path / "scrambled.yml"
    schema.dump_results_file(str(path), {"Fmax": "MHz"}, records)
    return path

  def expected_payload(self, path):
    return {
      "report": "results_inspect",
      "version": 1,
      "file": str(path),
      "format": "v2",
      "records": 3,
      "by_type": [
        {"type": "fmax_synthesis", "count": 1},
        {"type": "pnr", "count": 1},
        {"type": "workflow", "count": 1},
      ],
      "by_tool": [
        {"tool": None, "count": 1},
        {"tool": "genus", "count": 1},
        {"tool": "vivado", "count": 1},
      ],
      "metrics": [
        {"name": "Fmax", "unit": "MHz"},
        {"name": "Zeta", "unit": None},
        {"name": "alpha", "unit": None},
      ],
      "time_range": {"earliest": "2025-01-01_00-00-00", "latest": "2025-09-02_00-00-00"},
    }

  def test_payload_shape_values_and_order(self, tmp_path):
    path = self._scrambled_file(tmp_path)
    payload = inspect_json(path)
    expected = self.expected_payload(path)
    assert payload == expected
    # Stable field order at every level.
    assert list(payload) == list(expected)
    assert all(list(entry) == ["type", "count"] for entry in payload["by_type"])
    assert all(list(entry) == ["tool", "count"] for entry in payload["by_tool"])
    assert all(list(entry) == ["name", "unit"] for entry in payload["metrics"])
    assert list(payload["time_range"]) == ["earliest", "latest"]

  def test_serialized_json_is_exact_and_deterministic(self, tmp_path, capsys):
    path = self._scrambled_file(tmp_path)
    run_inspect(path, "--json")
    first = capsys.readouterr().out
    run_inspect(path, "--json")
    second = capsys.readouterr().out
    assert first == second
    assert first == json.dumps(self.expected_payload(path), indent=2) + "\n"


class TestReadOnly:
  def test_inspect_writes_nothing(self, result_file, monkeypatch):
    path = result_file("v1_synth.yml", V1_SYNTH)
    before = path.read_bytes()
    stat_before = path.stat().st_mtime_ns

    def no_dump(*_args, **_kwargs):
      raise AssertionError("inspect must not write or migrate the results file")

    def no_cache_store(*_args, **_kwargs):
      raise AssertionError("inspect must not refresh the results cache")

    monkeypatch.setattr(schema, "dump_results_file", no_dump)
    monkeypatch.setattr(results_cache, "store", no_cache_store)

    assert run_inspect(path, "--json")
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stat_before


######################################
# Real entry point (subprocess exit codes)
######################################


def run_cli(*argv, cwd):
  env = dict(os.environ, PYTHONPATH=SOURCES_DIR)
  return subprocess.run(
    [sys.executable, "-m", "odatix.odatix_main", *argv],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    universal_newlines=True,
    encoding="utf-8",
    cwd=str(cwd),
    env=env,
    timeout=120,
  )


@pytest.mark.integration
class TestInspectExitCodes:
  def test_v2_succeeds_without_banner(self, tmp_path):
    path = tmp_path / "v2.yml"
    path.write_text(V2_WITH_UNITS, encoding="utf-8")
    result = run_cli("results", "inspect", str(path), "--json", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["format"] == "v2" and payload["records"] == 3

  @pytest.mark.parametrize("content", [V1_SYNTH, V1_WORKFLOW])
  def test_v1_succeeds(self, tmp_path, content):
    path = tmp_path / "v1.yml"
    path.write_text(content, encoding="utf-8")
    result = run_cli("results", "inspect", str(path), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "legacy" in result.stdout

  def test_empty_records_succeed(self, tmp_path):
    path = tmp_path / "empty.yml"
    path.write_text(V2_EMPTY, encoding="utf-8")
    assert run_cli("results", "inspect", str(path), cwd=tmp_path).returncode == 0

  @pytest.mark.parametrize("content", [CORRUPT_YAML, UNKNOWN_YAML, MALFORMED_V2, ""])
  def test_bad_files_fail(self, tmp_path, content):
    path = tmp_path / "bad.yml"
    path.write_text(content, encoding="utf-8")
    result = run_cli("results", "inspect", str(path), cwd=tmp_path)
    assert result.returncode != 0
    assert result.stdout.strip() != ""

  def test_missing_file_fails(self, tmp_path):
    result = run_cli("results", "inspect", str(tmp_path / "gone.yml"), cwd=tmp_path)
    assert result.returncode != 0
