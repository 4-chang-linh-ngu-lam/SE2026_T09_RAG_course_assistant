"""Convert real JUnit + optional load results to bounded rule traceability evidence."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def summarize(junit, catalog, performance=None):
    cases = list(ET.fromstring(junit).iter("testcase"))
    results = []
    for scenario in catalog["scenarios"]:
        result = {key: value for key, value in scenario.items() if key != "tests"}
        if "pending" in scenario:
            result["result"] = "pending"
        elif scenario.get("evidence") == "performance":
            complete = (
                performance
                and performance["load"]["configured_seconds"] >= 600
                and performance["load"]["users"] == 100
                and performance["load"]["elapsed_seconds"] >= 600
                and performance["load"]["classes"] == 10
                and performance["load"]["students_per_class"] == 50
                and performance["requests"] > 0
                and performance["backend_samples"] >= performance["status_counts"].get("200", 0)
                and performance["requests"] * 0.99
                <= performance["backend_samples"]
                <= performance["requests"]
                and performance["backend_p95_ms"] is not None
                and performance["backend_p95_ms"] <= 500
                and performance["success_ratio"] >= 0.99
                and performance["wrong_scope_responses"] == 0
            )
            if performance:
                result["observed"] = {
                    key: performance[key]
                    for key in (
                        "requests",
                        "backend_p95_ms",
                        "client_p95_ms",
                        "success_ratio",
                        "wrong_scope_responses",
                    )
                }
            result["result"] = (
                "passed"
                if complete and performance["passed_core_thresholds"]
                else "pending"
                if performance is None
                else "failed"
            )
        else:
            checks = []
            for selector in scenario["tests"]:
                file, function = selector.split("::")
                module = file.removesuffix(".py").replace("/", ".")
                matched = [
                    case
                    for case in cases
                    if case.get("classname", "").endswith(module)
                    and case.get("name", "").split("[")[0] == function
                ]
                status = (
                    "missing"
                    if not matched
                    else "failed"
                    if any(
                        case.find("failure") is not None or case.find("error") is not None
                        for case in matched
                    )
                    else "skipped"
                    if any(case.find("skipped") is not None for case in matched)
                    else "passed"
                )
                checks.append({"test": selector, "cases": len(matched), "result": status})
            result["checks"] = checks
            result["result"] = (
                "passed" if all(check["result"] == "passed" for check in checks) else "failed"
            )
        results.append(result)
    return {
        "scope": catalog["scope"],
        "test_cases": len(cases),
        "skipped_cases": sum(case.find("skipped") is not None for case in cases),
        "failed_cases": sum(
            case.find("failure") is not None or case.find("error") is not None for case in cases
        ),
        "scenarios": results,
        "complete_core_g2": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(Path(__file__).with_name("scenarios.json").read_text(encoding="utf-8"))
    performance = json.loads(args.performance.read_text()) if args.performance else None
    report = summarize(args.junit.read_text(encoding="utf-8"), catalog, performance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failures = sum(item["result"] == "failed" for item in report["scenarios"])
    print(
        json.dumps(
            {
                "test_cases": report["test_cases"],
                "skipped_cases": report["skipped_cases"],
                "failed_scenarios": failures,
            }
        )
    )
    return 1 if failures or report["skipped_cases"] or report["failed_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
