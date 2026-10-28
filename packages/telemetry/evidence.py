from packages.domain.models import digest


def verify_evidence(value: dict, ident: str, kind: str):
    if value.get("id") != ident or value.get("kind") != kind:
        raise ValueError("Telemetry evidence identity mismatch")
    if digest({k: v for k, v in value.items() if k != "sha256"}) != value.get("sha256"):
        raise ValueError("Telemetry evidence SHA-256 mismatch")
