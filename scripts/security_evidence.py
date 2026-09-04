#!/usr/bin/env python3
"""Generate fail-closed dependency audit evidence and CycloneDX SBOMs."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "evidence"


def run_json(command: list[str], *, cwd: Path, timeout_seconds: float = 300.0) -> tuple[int, dict]:
    try:
        result = subprocess.run(  # noqa: S603 - callers provide fixed release commands
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{Path(command[0]).name} exceeded the {timeout_seconds:g}-second audit deadline"
        ) from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        diagnostic = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise RuntimeError(f"Command did not return JSON: {diagnostic}") from exc
    return result.returncode, payload


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    python_audit_code, python_audit = run_json(
        [
            str(ROOT / ".venv" / "bin" / "pip-audit"),
            "--local",
            "--skip-editable",
            "--format=json",
            "--progress-spinner=off",
        ],
        cwd=ROOT,
    )
    python_sbom_code, python_sbom = run_json(
        [
            str(ROOT / ".venv" / "bin" / "pip-audit"),
            "--local",
            "--skip-editable",
            "--format=cyclonedx-json",
            "--progress-spinner=off",
        ],
        cwd=ROOT,
    )
    frontend_audit_code, frontend_audit = run_json(
        ["npm", "audit", "--json", "--audit-level=low"],
        cwd=ROOT / "frontend",
    )
    frontend_sbom_code, frontend_sbom = run_json(
        ["npm", "sbom", "--sbom-format=cyclonedx", "--sbom-type=application"],
        cwd=ROOT / "frontend",
    )

    python_vulnerabilities = sum(
        len(dependency.get("vulns", [])) for dependency in python_audit["dependencies"]
    )
    python_dependencies_audited = sum(
        "skip_reason" not in dependency for dependency in python_audit["dependencies"]
    )
    python_editable_skipped = sum(
        dependency.get("skip_reason") == "distribution marked as editable"
        for dependency in python_audit["dependencies"]
    )
    frontend_severity = frontend_audit["metadata"]["vulnerabilities"]
    frontend_vulnerabilities = sum(
        count for severity, count in frontend_severity.items() if severity != "total"
    )
    passed = (
        python_audit_code == 0
        and python_sbom_code == 0
        and frontend_audit_code == 0
        and frontend_sbom_code == 0
        and python_vulnerabilities == 0
        and frontend_vulnerabilities == 0
    )
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "python": {
            "audit_tool": "pip-audit 2.10.1",
            "dependencies_audited": python_dependencies_audited,
            "editable_packages_skipped": python_editable_skipped,
            "known_vulnerabilities": python_vulnerabilities,
            "exit_code": python_audit_code,
            "scope": "Installed local environment excluding editable project package",
        },
        "frontend": {
            "audit_tool": "npm audit",
            "dependencies_audited": frontend_audit["metadata"]["dependencies"]["total"],
            "known_vulnerabilities": frontend_vulnerabilities,
            "severity_counts": frontend_severity,
            "exit_code": frontend_audit_code,
            "scope": "Resolved frontend package-lock dependency graph",
        },
        "artifacts": {
            "python_audit": "python_dependency_audit.json",
            "python_sbom": "python_sbom.cdx.json",
            "frontend_audit": "frontend_dependency_audit.json",
            "frontend_sbom": "frontend_sbom.cdx.json",
        },
        "limitations": [
            (
                "The result covers vulnerabilities known to the configured advisory "
                "services at scan time."
            ),
            (
                "Dependency audit is not source-code analysis and cannot prove absence "
                "of vulnerabilities."
            ),
            "SBOM inventory and advisory status must be refreshed for every release.",
        ],
    }
    artifacts = {
        "dependency_security.json": evidence,
        "python_dependency_audit.json": python_audit,
        "python_sbom.cdx.json": python_sbom,
        "frontend_dependency_audit.json": frontend_audit,
        "frontend_sbom.cdx.json": frontend_sbom,
    }
    for filename, payload in artifacts.items():
        (OUTPUT / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        "Dependency security evidence passed: "
        f"{python_dependencies_audited} third-party Python packages and "
        f"{frontend_audit['metadata']['dependencies']['total']} frontend dependencies, "
        "zero known vulnerabilities."
    )
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        raise SystemExit(f"Security evidence failed: {exc}") from exc
