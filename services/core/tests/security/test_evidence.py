from .evidence import summarize


def test_skipped_or_missing_cases_cannot_be_reported_as_verified():
    catalog = {
        "scope": "test",
        "scenarios": [{"id": "check", "tests": ["security/test_example.py::test_real"]}],
    }
    for xml in (
        "<testsuite/>",
        '<testsuite><testcase classname="tests.security.test_example" name="test_real"><skipped/></testcase></testsuite>',
    ):
        report = summarize(xml, catalog)
        assert report["scenarios"][0]["result"] == "failed"
    passed = summarize(
        '<testsuite><testcase classname="tests.security.test_example" name="test_real"/></testsuite>',
        catalog,
    )
    assert passed["scenarios"][0]["result"] == "passed"
    assert passed["complete_core_g2"] is False
    failed = summarize(
        '<testsuite><testcase classname="other" name="unselected"><failure/></testcase></testsuite>',
        catalog,
    )
    assert failed["failed_cases"] == 1
    short = {
        "load": {"configured_seconds": 600, "users": 100, "elapsed_seconds": 3},
        "passed_core_thresholds": True,
        "requests": 10,
        "backend_p95_ms": 5,
        "client_p95_ms": 7,
        "success_ratio": 1,
        "wrong_scope_responses": 0,
    }
    performance_catalog = {
        "scope": "test",
        "scenarios": [{"id": "performance", "evidence": "performance"}],
    }
    assert (
        summarize("<testsuite/>", performance_catalog, short)["scenarios"][0]["result"] == "failed"
    )
