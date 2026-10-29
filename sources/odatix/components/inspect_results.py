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
"odatix results inspect FILE": a read-only look at one results file.

Exporting turns the reports of a work directory into results files Odatix
Explorer reads, and troubleshooting those results otherwise means opening the
YAML by hand or launching the explorer. This command reads one file and says
what it holds:

  * the format it was written in (v2, or a read-only v1 variant);
  * how many records it contains, split by run type and by tool;
  * every metric name with its unit;
  * the time range the timestamps of the records cover.

It only reads: it never migrates a legacy file, never touches the results
cache and never writes anything. A file it cannot parse, or whose format it
does not know, is an error the exit code reports.
"""

import json
import os

import yaml

import odatix.lib.printc as printc
import odatix.lib.results_schema as results_schema

#: The subcommand name, under "odatix results".
RESULT_TYPE = "inspect"

#: Version of the JSON summary. Bumped when a field is added, removed or
#: changes meaning, so a script reading "--json" output knows what it gets.
JSON_VERSION = 1

#: How a human reads each detected format; JSON keeps the stable token.
FORMAT_LABELS = {
  results_schema.FORMAT_V2: "v2 (current)",
  results_schema.FORMAT_V1_SYNTH: "v1 synthesis (legacy, read-only)",
  results_schema.FORMAT_V1_WORKFLOW: "v1 workflow (legacy, read-only)",
}

#: Stable order of the JSON fields, top level and in each nested object.
JSON_KEYS = (
  "report", "version", "file", "format", "records",
  "by_type", "by_tool", "metrics", "time_range",
)
TIME_RANGE_KEYS = ("earliest", "latest")


def add_arguments(parser):
  parser.add_argument("file", metavar="FILE", help='results file to inspect, e.g. "results/fmax_results.yml"')
  parser.add_argument("--json", action="store_true", help="print the summary as JSON with stable field order")


######################################
# Summary
######################################


def _sorted_counts(counts, key_name):
  """
  Turn a {value: count} mapping into a sorted list of ``{key_name, "count"}``
  dicts.

  A missing value (a record without that meta key) is reported as null, sorted
  first: JSON objects cannot have null keys, and a list keeps the ordering
  stable regardless of the underlying dict order.
  """
  items = sorted(counts.items(), key=lambda item: (item[0] is not None, str(item[0])))
  return [{key_name: value, "count": count} for value, count in items]


def summarize(results_file):
  """
  Build the summary of a loaded :class:`ResultsFile`: counts by run type and
  by tool, metrics with their units, and the timestamp range.

  Counts, metric names and the time range come from the records normalized to
  v2; units come from the file. Every list comes out sorted, so the same file
  always gives the same summary.
  """
  units = results_file.units if isinstance(results_file.units, dict) else {}

  type_counts = {}
  tool_counts = {}
  metric_names = set()
  timestamps = []

  for record in results_file.records:
    meta = record.get("meta") if isinstance(record, dict) else None
    if not isinstance(meta, dict):
      meta = {}

    type_value = meta.get(results_schema.META_TYPE)
    type_counts[type_value] = type_counts.get(type_value, 0) + 1

    tool_value = meta.get(results_schema.META_TOOL)
    tool_counts[tool_value] = tool_counts.get(tool_value, 0) + 1

    metrics = record.get("metrics") if isinstance(record, dict) else None
    if isinstance(metrics, dict):
      for name in metrics:
        metric_names.add(str(name))

    timestamp = meta.get(results_schema.META_TIMESTAMP)
    if isinstance(timestamp, str) and timestamp.strip() != "":
      timestamps.append(timestamp.strip())

  metrics = [{"name": name, "unit": units.get(name)} for name in sorted(metric_names)]

  if timestamps:
    time_range = {"earliest": min(timestamps), "latest": max(timestamps)}
  else:
    time_range = {"earliest": None, "latest": None}

  return {
    "format": results_file.schema_detected,
    "records": len(results_file.records),
    "by_type": _sorted_counts(type_counts, results_schema.META_TYPE),
    "by_tool": _sorted_counts(tool_counts, results_schema.META_TOOL),
    "metrics": metrics,
    "time_range": time_range,
  }


def json_payload(path, summary):
  """The summary as the versioned, stably ordered JSON-serialisable payload."""
  payload = {
    "report": "results_inspect",
    "version": JSON_VERSION,
    "file": path,
    "format": summary["format"],
    "records": summary["records"],
    "by_type": summary["by_type"],
    "by_tool": summary["by_tool"],
    "metrics": [{"name": metric["name"], "unit": metric["unit"]} for metric in summary["metrics"]],
    "time_range": {key: summary["time_range"][key] for key in TIME_RANGE_KEYS},
  }
  # Built in JSON_KEYS order: json.dumps(sort_keys=False) keeps it.
  return {key: payload[key] for key in JSON_KEYS}


######################################
# Human-readable output
######################################


def _print_counts(title, entries, value_key):
  printc.bold("{} ({}):".format(title, sum(entry["count"] for entry in entries)))
  if not entries:
    printc.grey("  none")
    return
  names = [entry[value_key] if entry[value_key] is not None else "(none)" for entry in entries]
  width = max(len(str(name)) for name in names)
  for entry in entries:
    name = entry[value_key] if entry[value_key] is not None else "(none)"
    print("  " + str(name).ljust(width + 2) + str(entry["count"]))


def print_summary(path, summary):
  printc.bold("File:    ", end="")
  print(path)
  printc.bold("Format:  ", end="")
  print(FORMAT_LABELS.get(summary["format"], summary["format"]))
  printc.bold("Records: ", end="")
  print(summary["records"])
  print()

  _print_counts("Run types", summary["by_type"], results_schema.META_TYPE)
  _print_counts("Tools", summary["by_tool"], results_schema.META_TOOL)

  print()
  printc.bold("Metrics ({}):".format(len(summary["metrics"])))
  if not summary["metrics"]:
    printc.grey("  none")
  for metric in summary["metrics"]:
    if metric["unit"]:
      print("  {} ({})".format(metric["name"], metric["unit"]))
    else:
      print("  " + metric["name"], end="")
      printc.grey("  (no unit)")

  print()
  printc.bold("Time range:")
  time_range = summary["time_range"]
  if time_range["earliest"] is None:
    printc.grey("  none (the records carry no timestamp)")
  else:
    print("  {} .. {}".format(time_range["earliest"], time_range["latest"]))


######################################
# Command
######################################


class InspectError(Exception):
  """A file inspect cannot report on: missing, unreadable or unrecognized."""


def inspect_file(path):
  """
  Read one results file, without migrating it, refreshing any cache or
  writing anything.

  Returns:
      ResultsFile: the loaded file, records normalized to v2.

  Raises:
      InspectError: the file is missing, cannot be parsed, or has an
          unrecognized format.
  """
  if not os.path.isfile(path):
    raise InspectError('Results file "' + path + '" does not exist')
  try:
    results_file = results_schema.load_results_file(path)
  except yaml.YAMLError as e:
    detail = str(e).splitlines()[0] if str(e) else "not valid YAML"
    raise InspectError('Cannot parse "' + path + '": ' + detail)
  except OSError as e:
    raise InspectError('Cannot read "' + path + '": ' + str(e))
  if results_file.schema_detected == results_schema.FORMAT_UNKNOWN:
    raise InspectError(
      '"' + path + '" is not an Odatix results file: unknown format '
      '(expected a v2 file or a v1 synthesis/workflow file)'
    )
  return results_file


def main(args):
  path = args.file
  try:
    results_file = inspect_file(path)
  except InspectError as e:
    printc.error(str(e), "odatix results inspect")
    return False

  summary = summarize(results_file)
  if getattr(args, "json", False):
    print(json.dumps(json_payload(path, summary), indent=2, sort_keys=False))
  else:
    print_summary(path, summary)
  return True
