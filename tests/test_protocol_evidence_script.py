import json
import subprocess
import sys
from pathlib import Path

from craft.security import ProtocolErrorCode

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_protocol_evidence_script_writes_report_ready_json(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/collect_protocol_evidence.py",
            "--scenarios",
            "happy-path",
            "tamper-action",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(output.read_text(encoding="utf-8"))

    assert "Wrote 2 protocol evidence scenarios" in result.stdout
    assert data["artifact_type"] == "security_protocol_evidence"
    assert data["summary"]["passed_count"] == 2
    assert [case["scenario"] for case in data["scenarios"]] == ["happy-path", "tamper-action"]
    assert data["scenarios"][0]["scenario_result"]["code"] == ProtocolErrorCode.OK.value
    assert (
        data["scenarios"][1]["scenario_result"]["code"]
        == ProtocolErrorCode.ACTION_DIGEST_MISMATCH.value
    )
    assert data["scenarios"][0]["transcript"]["audit_chain_digest"] is not None
