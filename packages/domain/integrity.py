"""Shared saved-result verification for reopening, export and recovery."""

from uuid import UUID

from packages.domain.models import digest

RESULT_METADATA = frozenset(
    {"id", "name", "created_utc", "revision_id", "operating_mode", "weather_provider", "manifest"}
)


def verify_simulation(payload: dict, expected_id: str | None = None) -> None:
    try:
        manifest = payload["manifest"]
        config = manifest["config"]
        for identifier in (payload["id"], manifest["mission_id"], manifest["revision_id"]):
            UUID(identifier)
        consistent = (
            (expected_id is None or payload["id"] == expected_id)
            and payload["id"] == manifest["simulation_id"]
            and payload["revision_id"] == manifest["revision_id"]
            and manifest["mission_id"] == config["id"]
            and payload["name"] == config["name"]
            and payload["operating_mode"] == config["operating_mode"]
            and payload["weather_provider"]
            == config["weather"]["provider"]
            == manifest["weather"]["provider"]
            and payload["created_utc"] == manifest["created_utc"]
            and digest({k: v for k, v in manifest.items() if k != "sha256"}) == manifest["sha256"]
            and digest(config) == manifest["config_sha256"]
            and digest({k: v for k, v in payload.items() if k not in RESULT_METADATA})
            == manifest["output_sha256"]
        )
        if not consistent:
            raise ValueError("Saved identifiers, labels or checksums differ")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            "Stored prediction integrity check failed; identifiers, labels or scientific evidence differ"
        ) from exc
