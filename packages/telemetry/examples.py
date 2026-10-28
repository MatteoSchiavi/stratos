"""Explicitly synthetic, editable inputs. No real receivers/permissions asserted."""

from packages.telemetry.models import Contact, Observation, RecoveryRequest, RegionProfile, Window


def example_study() -> RecoveryRequest:
    return RecoveryRequest(
        positions=[
            Observation(
                time_s=t,
                sequence=t // 60,
                latitude_deg=45 + t / 360000,
                longitude_deg=9.7 + t / 180000,
                altitude_m=12500,
                temperature_k=225 + (t % 1200) / 1200,
                pressure_pa=18000,
                voltage_v=4.5,
                origin="simulated",
            )
            for t in range(0, 3601, 60)
        ],
        profiles=[
            RegionProfile(
                name="Illustrative EU test geofence",
                region="EU868",
                start_s=0,
                end_s=3600,
                south=40,
                north=50,
                west=5,
                east=15,
                permission_configured=True,
                permission_reference="DEMO ONLY — no airborne authorization",
                duty_fraction=0.01,
            )
        ],
        contacts=[
            Contact(
                start_s=0,
                end_s=900,
                receiver_id="demo-receiver-A",
                region="EU868",
                data_rates=[3, 5],
                compatible=True,
                source="Synthetic contact scenario; no real receiver",
                loss_probability=0.2,
            ),
            Contact(
                start_s=1800,
                end_s=3600,
                receiver_id="demo-receiver-B",
                region="EU868",
                data_rates=[4, 5],
                compatible=True,
                source="Synthetic contact scenario; no real receiver",
                loss_probability=0.2,
            ),
        ],
        outages=[Window(start_s=300, end_s=600)],
    )
