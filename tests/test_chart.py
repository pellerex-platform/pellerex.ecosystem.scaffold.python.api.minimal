"""The chart's Kubernetes checks act on the health test, which runs once a minute: out of traffic
after two failed tests, restarted after five, about 5 minutes, and an answer that takes over 5
seconds counts as failed."""

from pathlib import Path

CHART = Path(__file__).parent.parent / "infrastructure/Helm/templates/deployment.yaml"


def probe_settings(probe: str) -> dict[str, str]:
    """Every 'key: value' line under one Kubernetes check of the chart, with the nesting dropped
    ('path', 'periodSeconds'). The chart is a Helm template, not plain YAML, so it is read as
    text."""
    chart = CHART.read_text(encoding="utf-8").splitlines()
    start = [line.strip() for line in chart].index(f"{probe}:")
    indent = chart[start].index(probe)
    settings = {}
    for line in chart[start + 1 :]:
        if len(line) - len(line.lstrip()) <= indent:
            break
        key, _, value = line.strip().partition(":")
        if value.strip():
            settings[key] = value.strip()
    return settings


def test_the_chart_waits_up_to_2_minutes_for_the_first_health_test():
    assert probe_settings("startupProbe") == {
        "path": "/health/startup",
        "port": "http",
        "periodSeconds": "5",
        "failureThreshold": "24",
    }


def test_the_chart_takes_the_pod_out_of_traffic_after_two_failed_tests():
    assert probe_settings("readinessProbe") == {
        "path": "/health/ready",
        "port": "http",
        "periodSeconds": "60",
        "timeoutSeconds": "5",
        "failureThreshold": "2",
    }


def test_the_chart_restarts_the_pod_after_5_minutes_of_failed_tests():
    assert probe_settings("livenessProbe") == {
        "path": "/health/live",
        "port": "http",
        "periodSeconds": "60",
        "timeoutSeconds": "5",
        "failureThreshold": "5",
    }
