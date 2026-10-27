"""Cardinality-only oracle for the declared WLAN handler-output representations."""
import json
import re

SUMMARY = re.compile(r"^list_wlans returned (\d+) record\(s\)\.(?:\s|$)")


def observed_counts(output):
    """Read record cardinality only; ignore record values and unrelated metadata.

    Lists are terminal record collections. Only result/structuredContent wrapper
    keys are traversed, so nested record attributes cannot masquerade as a list.
    Multiple representations must agree, rather than one masking a contradiction.
    """
    found = set()
    def walk(value):
        if isinstance(value, str):
            match = SUMMARY.match(value.strip())
            if match:
                found.add(int(match.group(1)))
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                return
            if isinstance(parsed, (dict, list)):
                walk(parsed)
        elif isinstance(value, list):
            if all(isinstance(record, dict) for record in value):
                found.add(len(value))
        elif isinstance(value, dict):
            for key in ('result', 'structuredContent'):
                if key in value:
                    walk(value[key])
    walk(output)
    return sorted(found)


def count_retained(output, expected_count):
    if type(expected_count) is not int or expected_count < 0:
        raise ValueError('Expected a nonnegative integer count')
    return observed_counts(output) == [expected_count]
