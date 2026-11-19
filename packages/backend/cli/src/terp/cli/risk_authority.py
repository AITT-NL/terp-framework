"""Fresh, purpose-bound authorization from an operator-configured approval authority.

The protected host configures the provider and issuer keys. The application supplies
neither. A fresh random challenge forces a current ledger read at every decision;
an exported old approval envelope cannot be replayed after revocation.
"""

from __future__ import annotations

import json
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from terp.cli.dependency_risk import RiskRefused, evaluate, time_value
from terp.cli.release import dsse
from terp.cli.release._common import ReleaseError

PAYLOAD_TYPE = "application/vnd.terp.dependency-risk-authorization.v1+json"


def authorize(checks: list[dict], *, policy_file: str, commit: str, checkout: str | Path) -> dict:
    """Query the trusted provider and compute permission; never accept its verdict blindly."""
    policy_path = Path(policy_file).resolve()
    if policy_path.is_relative_to(Path(checkout).resolve()):
        raise RiskRefused("risk authority policy must live outside the application checkout")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or set(policy) != {"project_id", "environment", "provider", "public_keys"}:
        raise RiskRefused("risk authority policy has an unknown shape")
    provider = policy["provider"]
    if (not isinstance(provider, list) or not provider
            or not all(isinstance(part, str) and part for part in provider)
            or not Path(provider[0]).is_absolute()):
        raise RiskRefused("risk authority provider must name an absolute executable")
    if (not isinstance(policy["public_keys"], list) or not policy["public_keys"]
            or not all(isinstance(pem, str) for pem in policy["public_keys"])):
        raise RiskRefused("risk authority has no pinned issuer keys")
    request = {"version": 1, "nonce": secrets.token_hex(32), "project_id": policy["project_id"],
               "commit": commit, "environment": policy["environment"]}
    try:
        completed = subprocess.run(  # noqa: S603 - protected operator configuration, never app argv
            provider, input=json.dumps(request).encode(), capture_output=True,
            cwd=policy_path.parent, timeout=30, check=False,
        )
        if completed.returncode or len(completed.stdout) > 4_000_000:
            raise RiskRefused("the risk authority could not be queried")
        keys = [dsse.load_public_key(pem.encode()) for pem in policy["public_keys"]]
        payload, issuer = dsse.verify(completed.stdout, keys, payload_type=PAYLOAD_TYPE)
        response = json.loads(payload)
        if not isinstance(response, dict) or any(response.get(k) != v for k, v in request.items()):
            raise RiskRefused("risk authority answered for another request")
        now = datetime.now(UTC)
        issued, expires = time_value(response.get("issued_at")), time_value(response.get("expires_at"))
        if not issued <= now < expires or expires - issued > timedelta(minutes=5):
            raise RiskRefused("risk authority response is expired or has an excessive lifetime")
        records = response.get("acceptances")
        if not isinstance(records, list):
            raise RiskRefused("risk authority omitted its acceptance records")
        decision = evaluate(checks, records, project=policy["project_id"], commit=commit,
                            environment=policy["environment"], now=now)
        if not decision["allowed"]:
            raise RiskRefused("release has failed checks or unaccepted dependency findings")
        return {"decision": decision, "project_id": policy["project_id"], "environment": policy["environment"],
                "commit": commit, "issuer": issuer, "authorization": json.loads(completed.stdout),
                "checks": checks, "acceptances": records}
    except (OSError, subprocess.SubprocessError, ValueError, ReleaseError) as exc:
        raise RiskRefused("dependency risk authorization could not be verified") from exc


def main() -> int:
    """Protected verifier process for Studio and Runner; the app cannot select policy."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-map", required=True)
    args = parser.parse_args()
    try:
        request = json.loads(sys.stdin.buffer.read(4_000_001))
        mapping = json.loads(Path(args.policy_map).read_text(encoding="utf-8"))
        policy_file = mapping[request["project_id"]][request["environment"]]
        if not Path(policy_file).is_absolute():
            raise RiskRefused("policy map must name absolute policy paths")
        result = authorize(request["checks"], policy_file=policy_file, commit=request["commit"],
                           checkout=request.get("checkout", Path(policy_file).parent / "no-app-checkout"))
        if result["project_id"] != request["project_id"] or result["environment"] != request["environment"]:
            raise RiskRefused("policy belongs to another project or environment")
        sys.stdout.write(json.dumps(result) + "\n")
        return 0
    except (KeyError, TypeError, ValueError, OSError, ReleaseError):
        sys.stderr.write("Dependency risk authorization refused. Check the protected authority configuration.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
