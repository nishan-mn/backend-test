"""Verified historical lunar-mission records for the Historical Mission Explorer.

The records intentionally separate intended locations from actual landing or impact
locations. Historical facts come from the source keys in ``SOURCES``; modeled replay
results must be produced only by the shared visibility engine.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_REPLAY_DURATION_HOURS = 144

COORDINATE_CONVENTION = {
    "latitude": "Decimal degrees; south is negative and north is positive.",
    "longitude": "Decimal degrees; lunar east-positive longitude.",
    "coordinate_reference": (
        "Source-reported lunar cartographic/selenographic coordinates. "
        "Nishan must confirm compatibility with the visibility engine's Moon-fixed observer frame."
    ),
    "time": "ISO 8601 UTC timestamps. UTC is a time standard, not a coordinate reference frame.",
}


# Each source declares exactly which fields it supports. API responses can expose this
# provenance without requiring a live network request.
SOURCES: dict[str, dict[str, str]] = {
    "CE4-1": {
        "title": "CNSA: Chang'e-4 far-side landing announcement",
        "url": "https://www.cnsa.gov.cn/english/n6465652/n6465653/c6805049/content.html",
        "supports": "Chang'e-4 landing time, intended landing area, and successful far-side landing.",
    },
    "CE4-2": {
        "title": "LROC: Topographic Map of the Chang'e-4 Site",
        "url": "https://lroc.im-ldi.com/images/1100",
        "supports": "Chang'e-4 actual lander coordinate and stated positional uncertainty.",
    },
    "CY3-1": {
        "title": "ISRO: Chandrayaan-3 Details",
        "url": "https://www.isro.gov.in/ISRO_EN/Chandrayaan3_Details.html",
        "supports": "Chandrayaan-3 mission objectives and prime intended landing ellipse.",
    },
    "CY3-2": {
        "title": "ISRO / PRL: Chandrayaan-3 APXS report",
        "url": "https://www.isro.gov.in/media_isro/pdf/APXS_CH3.pdf",
        "supports": "Chandrayaan-3 landing time, Shiv Shakti Statio, and mission achievements.",
    },
    "CY3-3": {
        "title": "NASA NSSDC: Anthropogenic impacts and spacecraft on the Moon",
        "url": "https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_artifact_impacts.html",
        "supports": "Chandrayaan-3 actual lander coordinate.",
    },
    "BG1-1": {
        "title": "NASA: Blue Ghost touchdown release",
        "url": "https://www.nasa.gov/news-release/touchdown-carrying-nasa-science-fireflys-blue-ghost-lands-on-moon/",
        "supports": "Blue Ghost landing time/outcome, upright configuration, and Mare Crisium location.",
    },
    "BG1-2": {
        "title": "LROC: Blue Ghost Lunar Lander Seen From Above",
        "url": "https://lroc.im-ldi.com/images/1407",
        "supports": "Blue Ghost actual lander coordinate.",
    },
    "BG1-3": {
        "title": "Firefly Aerospace: Blue Ghost Mission 1",
        "url": "https://fireflyspace.com/missions/blue-ghost-mission-1/",
        "supports": "Blue Ghost operator, destination, and mission purpose.",
    },
    "CY2-1": {
        "title": "ISRO: Vikram lander mission information",
        "url": "https://www.isro.gov.in/media_isro/pdf/GSLVMkIII_M1.pdf",
        "supports": "Chandrayaan-2 intended landing region, purpose, and lander design.",
    },
    "CY2-2": {
        "title": "ISRO: Rajya Sabha response on Chandrayaan-2",
        "url": "https://www.isro.gov.in/media_isro/pdf/docs/UsefulLinks/ParliamentQuestions/winter_session_2019.pdf",
        "supports": "Chandrayaan-2 descent outcome, design-parameter deviation, and orbiter status.",
    },
    "CY2-3": {
        "title": "LROC: Vikram Lander Found",
        "url": "https://lroc.im-ldi.com/images/1131",
        "supports": "Chandrayaan-2 actual impact coordinate and elevation.",
    },
    "CY2-4": {
        "title": "Lunar and Planetary Science Conference: Report on the loss of Vikram",
        "url": "https://www.hou.usra.edu/meetings/lpsc2021/pdf/1039.pdf",
        "supports": "Secondary source for Chandrayaan-2's minute-level loss-of-contact time.",
    },
    "IM2-1": {
        "title": "NASA: IM-2 mission update",
        "url": "https://www.nasa.gov/news-release/nasa-receives-some-data-before-intuitive-machines-ends-lunar-mission/",
        "supports": "Athena approximate touchdown time, off-nominal orientation, and early mission end.",
    },
    "IM2-2": {
        "title": "LROC: IM-2 Athena Seen Obliquely",
        "url": "https://lroc.im-ldi.com/images/1408",
        "supports": "Athena actual location, crater size, and off-nominal orientation.",
    },
    "IM2-3": {
        "title": "NASA PDS: Athena mission context",
        "url": "https://pds.nasa.gov/services/search/search?f.facet_investigation.facet.prefix=2%2Cinternational+cometary+explorer%2C&f.facet_type.facet.prefix=2%2Cinstrument_host%2C&fq=facet_type%3A%221%2Cinstrument_host%22&q=&start=100",
        "supports": "Athena planned Mons Mouton site and payload objectives.",
    },
    "L25-1": {
        "title": "LROC: Luna 25 Impact Crater",
        "url": "https://lroc.im-ldi.com/images/1311",
        "supports": "Luna 25 impact time, intended site, actual impact coordinate, terrain, and uncertainty.",
    },
    "L25-2": {
        "title": "Roscosmos: preliminary Luna 25 failure investigation",
        "url": "https://www.roscosmos.ru/39790/",
        "supports": "Luna 25 source-supported failure mechanism and 127-second burn.",
    },
    "L25-3": {
        "title": "IKI: Luna-25 mission page",
        "url": "https://iki.cosmos.ru/research/missions/luna-25",
        "supports": "Luna 25 mission objective and sequence before the anomaly.",
    },
}


def location(
    *,
    name: str,
    latitude_deg: float,
    longitude_deg: float,
    location_type: str,
    coordinate_quality: str,
    precision_or_uncertainty: str,
    original_coordinate_text: str,
    source_keys: list[str],
) -> dict[str, Any]:
    """Create a location object with a consistent provenance contract."""
    return {
        "name": name,
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "location_type": location_type,
        "coordinate_quality": coordinate_quality,
        "precision_or_uncertainty": precision_or_uncertainty,
        "coordinate_reference": COORDINATE_CONVENTION["coordinate_reference"],
        "original_coordinate_text": original_coordinate_text,
        "source_keys": source_keys,
    }


MISSIONS: list[dict[str, Any]] = [
    {
        "id": "change_4",
        "name": "Chang'e-4",
        "spacecraft_or_lander": "Chang'e-4 lander and Yutu-2 rover",
        "country": "China",
        "operator": "China National Space Administration (CNSA)",
        "event_time_utc": "2019-01-03T02:26:00Z",
        "time_precision": "minute",
        "event_description": "Successful soft landing on the lunar far side.",
        "mission_objective": "Land and operate a rover on the lunar far side for radio astronomy and surface science.",
        "landing_outcome": "successful_soft_landing",
        "overall_mission_outcome": "successful",
        "documented_failure_reason": None,
        "what_happened": "The lander and rover reached the preselected Von Karman region. Communications use the Queqiao relay, so direct Earth visibility does not describe the mission's communications capability.",
        "achievements": "First soft landing and rover operation on the lunar far side.",
        "intended_location": location(
            name="Von Karman crater preselected area",
            latitude_deg=-45.5,
            longitude_deg=177.6,
            location_type="intended_landing_area",
            coordinate_quality="approximate",
            precision_or_uncertainty="CNSA reported the area to 0.1 degree; it is not an exact target-point coordinate.",
            original_coordinate_text="45.5 degrees S, 177.6 degrees E",
            source_keys=["CE4-1"],
        ),
        "actual_location": location(
            name="Von Karman crater",
            latitude_deg=-45.4561,
            longitude_deg=177.5885,
            location_type="actual_landing",
            coordinate_quality="confirmed",
            precision_or_uncertainty="LROC reports about 3 m positional uncertainty from its stereo model.",
            original_coordinate_text="45.4561 degrees S, 177.5885 degrees E",
            source_keys=["CE4-2"],
        ),
        "replay": {"status": "eligible", "location_field": "actual_location", "label": "Actual landing site"},
        "media": [],
        "source_keys": ["CE4-1", "CE4-2"],
    },
    {
        "id": "chandrayaan_3",
        "name": "Chandrayaan-3",
        "spacecraft_or_lander": "Vikram lander and Pragyan rover",
        "country": "India",
        "operator": "Indian Space Research Organisation (ISRO)",
        "event_time_utc": "2023-08-23T12:34:00Z",
        "time_precision": "minute",
        "event_description": "Successful soft landing at Shiv Shakti Statio.",
        "mission_objective": "Demonstrate safe soft landing, rover operations, and in-situ lunar science.",
        "landing_outcome": "successful_soft_landing",
        "overall_mission_outcome": "successful",
        "documented_failure_reason": None,
        "what_happened": "Vikram soft-landed and Pragyan carried out surface measurements during the mission's planned lunar-day operations.",
        "achievements": "India's first successful lunar soft landing; the mission returned in-situ surface measurements.",
        "intended_location": location(
            name="Prime landing ellipse",
            latitude_deg=-69.367621,
            longitude_deg=32.348126,
            location_type="intended_landing_area",
            coordinate_quality="documented_ellipse_center",
            precision_or_uncertainty="ISRO describes a 4 km by 2.4 km prime landing site; these values are its documented center, not a confirmed touchdown point.",
            original_coordinate_text="69.367621 degrees S, 32.348126 degrees E",
            source_keys=["CY3-1"],
        ),
        "actual_location": location(
            name="Shiv Shakti Statio",
            latitude_deg=-69.3741,
            longitude_deg=32.3200,
            location_type="actual_landing",
            coordinate_quality="confirmed",
            precision_or_uncertainty="NSSDC reports the coordinate to 4 decimal places in latitude and 2 decimal places in longitude.",
            original_coordinate_text="69.3741 degrees S, 32.32 degrees E",
            source_keys=["CY3-3"],
        ),
        "replay": {"status": "eligible", "location_field": "actual_location", "label": "Actual landing site"},
        "media": [],
        "source_keys": ["CY3-1", "CY3-2", "CY3-3"],
    },
    {
        "id": "blue_ghost_mission_1",
        "name": "Blue Ghost Mission 1",
        "spacecraft_or_lander": "Blue Ghost lunar lander",
        "country": "United States",
        "operator": "Firefly Aerospace, under NASA CLPS",
        "event_time_utc": "2025-03-02T08:34:00Z",
        "time_precision": "minute",
        "event_description": "Successful upright lunar landing near Mons Latreille in Mare Crisium.",
        "mission_objective": "Deliver NASA science and technology payloads to study lunar surface and environmental conditions.",
        "landing_outcome": "successful_soft_landing",
        "overall_mission_outcome": "successful",
        "documented_failure_reason": None,
        "what_happened": "NASA reported an upright, stable landing. LROC later imaged the spacecraft at a measured site coordinate.",
        "achievements": "Delivered ten NASA instruments and completed a successful commercial lunar delivery.",
        "intended_location": location(
            name="Mare Crisium landing region",
            latitude_deg=18.5604,
            longitude_deg=61.8071,
            location_type="intended_landing_area",
            coordinate_quality="documented_target",
            precision_or_uncertainty="Pre-landing mission documentation; not used for replay because a post-landing LROC coordinate is available.",
            original_coordinate_text="18.5604 degrees N, 61.8071 degrees E",
            source_keys=["BG1-3"],
        ),
        "actual_location": location(
            name="Mare Crisium, near Mons Latreille",
            latitude_deg=18.5623,
            longitude_deg=61.8103,
            location_type="actual_landing",
            coordinate_quality="confirmed",
            precision_or_uncertainty="LROC imaged the lander and reports this coordinate to four decimal places.",
            original_coordinate_text="18.5623 degrees N, 61.8103 degrees E",
            source_keys=["BG1-2"],
        ),
        "replay": {"status": "eligible", "location_field": "actual_location", "label": "Actual landing site"},
        "media": [],
        "source_keys": ["BG1-1", "BG1-2", "BG1-3"],
    },
    {
        "id": "chandrayaan_2_vikram",
        "name": "Chandrayaan-2 Vikram",
        "spacecraft_or_lander": "Vikram lander with Pragyan rover",
        "country": "India",
        "operator": "Indian Space Research Organisation (ISRO)",
        "event_time_utc": "2019-09-06T20:23:00Z",
        "time_precision": "minute; secondary scholarly time record",
        "event_description": "Loss of contact during descent followed by a hard impact.",
        "mission_objective": "Demonstrate soft landing and rover operations near the lunar south pole while the orbiter conducted lunar science.",
        "landing_outcome": "unsuccessful_hard_impact",
        "overall_mission_outcome": "partial_success",
        "documented_failure_reason": "ISRO reported velocity reduction outside the designed value, leaving fine-braking initial conditions beyond design parameters. The public source does not support a more specific root-cause label.",
        "what_happened": "ISRO lost communication after normal performance to about 2.1 km altitude. LROC identified the impact site; the orbiter continued science operations.",
        "achievements": "The orbiter continued producing lunar science data after the lander loss.",
        "intended_location": location(
            name="High plain between Manzinus C and Simpelius N",
            latitude_deg=-70.9,
            longitude_deg=22.7,
            location_type="intended_landing_area",
            coordinate_quality="approximate",
            precision_or_uncertainty="ISRO publicly describes the target only as about 70.9 degrees S, 22.7 degrees E; unsupported extra decimals are not retained.",
            original_coordinate_text="about 70.9 degrees S, 22.7 degrees E",
            source_keys=["CY2-1"],
        ),
        "actual_location": location(
            name="Vikram impact site",
            latitude_deg=-70.8810,
            longitude_deg=22.7840,
            location_type="actual_impact",
            coordinate_quality="confirmed",
            precision_or_uncertainty="LROC reports the impact coordinate and 834 m elevation. Elevation is not sent to the replay engine unless it supports altitude.",
            original_coordinate_text="70.8810 degrees S, 22.7840 degrees E",
            source_keys=["CY2-3"],
        ),
        "replay": {"status": "eligible", "location_field": "actual_location", "label": "Actual impact site"},
        "media": [],
        "source_keys": ["CY2-1", "CY2-2", "CY2-3", "CY2-4"],
    },
    {
        "id": "athena_im_2",
        "name": "Athena (Intuitive Machines IM-2)",
        "spacecraft_or_lander": "Nova-C lander Athena",
        "country": "United States",
        "operator": "Intuitive Machines, under NASA CLPS",
        "event_time_utc": "2025-03-06T17:30:00Z",
        "time_precision": "approximate minute; NASA reported approximately 11:30 a.m. CST",
        "event_description": "Off-nominal touchdown inside a crater; the lander came to rest on its side.",
        "mission_objective": "Deliver the PRIME-1 drilling and volatile-analysis payloads to the Mons Mouton region.",
        "landing_outcome": "off_nominal_touchdown_limited_operations",
        "overall_mission_outcome": "early_termination",
        "documented_failure_reason": "LROC reports the lander hit the surface faster than intended and ended on its side. NASA reports that the sideways orientation prevented full operations before battery depletion.",
        "what_happened": "Athena reached the surface near Mons Mouton but operated only briefly after the off-nominal landing.",
        "achievements": "Returned some data and images before operations ended.",
        "intended_location": location(
            name="Mons Mouton planned site",
            latitude_deg=-84.79,
            longitude_deg=29.20,
            location_type="intended_landing_area",
            coordinate_quality="documented_target",
            precision_or_uncertainty="PDS context gives the target to 0.01 degree.",
            original_coordinate_text="84.79 degrees S, 29.20 degrees E",
            source_keys=["IM2-3"],
        ),
        "actual_location": location(
            name="20 m crater near Mons Mouton",
            latitude_deg=-84.7906,
            longitude_deg=29.1957,
            location_type="actual_landing",
            coordinate_quality="confirmed",
            precision_or_uncertainty="LROC reports the landed location and off-nominal orientation; exact event-time seconds are not retained.",
            original_coordinate_text="84.7906 degrees S, 29.1957 degrees E",
            source_keys=["IM2-2"],
        ),
        "replay": {"status": "eligible", "location_field": "actual_location", "label": "Actual landing site"},
        "media": [],
        "source_keys": ["IM2-1", "IM2-2", "IM2-3"],
    },
    {
        "id": "luna_25",
        "name": "Luna 25",
        "spacecraft_or_lander": "Luna 25 lander",
        "country": "Russia",
        "operator": "Roscosmos / Space Research Institute (IKI)",
        "event_time_utc": "2023-08-19T11:58:00Z",
        "time_precision": "minute",
        "event_description": "Impact during the pre-landing orbit-transfer sequence.",
        "mission_objective": "Demonstrate polar soft landing and investigate the lunar south-polar surface environment.",
        "landing_outcome": "unsuccessful_pre_landing_impact",
        "overall_mission_outcome": "unsuccessful",
        "documented_failure_reason": "Roscosmos reported a 127-second engine burn instead of the planned 84 seconds, associated with an onboard control-system issue involving accelerometer data, which placed the spacecraft on an impact trajectory.",
        "what_happened": "The spacecraft impacted the southwest inner rim of Pontecoulant G crater before its planned landing. LROC identifies the new crater as likely Luna 25's impact crater.",
        "achievements": "Completed transfer and lunar-orbit operations, including observations, before the anomaly.",
        "intended_location": location(
            name="Luna 25 intended landing point",
            latitude_deg=-69.545,
            longitude_deg=43.544,
            location_type="intended_landing_area",
            coordinate_quality="documented_target",
            precision_or_uncertainty="LROC reports the intended landing point to three decimals.",
            original_coordinate_text="69.545 degrees S, 43.544 degrees E",
            source_keys=["L25-1"],
        ),
        "actual_location": location(
            name="Pontecoulant G southwest inner rim",
            latitude_deg=-57.865,
            longitude_deg=61.360,
            location_type="actual_impact",
            coordinate_quality="likely_confirmed",
            precision_or_uncertainty="LROC describes the new crater as likely Luna 25's crater and gives better-than-40-m accuracy.",
            original_coordinate_text="57.865 degrees S, 61.360 degrees E",
            source_keys=["L25-1"],
        ),
        "replay": {"status": "eligible_with_location_note", "location_field": "actual_location", "label": "Likely actual impact site"},
        "media": [],
        "source_keys": ["L25-1", "L25-2", "L25-3"],
    },
]

MISSION_BY_ID: dict[str, dict[str, Any]] = {mission["id"]: mission for mission in MISSIONS}


def list_mission_summaries() -> list[dict[str, Any]]:
    """Return the compact fields needed for mission cards and map markers."""
    summaries = []
    for mission in MISSIONS:
        actual = mission["actual_location"]
        summaries.append(
            {
                "id": mission["id"],
                "name": mission["name"],
                "country": mission["country"],
                "operator": mission["operator"],
                "event_time_utc": mission["event_time_utc"],
                "time_precision": mission["time_precision"],
                "landing_outcome": mission["landing_outcome"],
                "marker_location": {
                    "latitude_deg": actual["latitude_deg"],
                    "longitude_deg": actual["longitude_deg"],
                    "location_type": actual["location_type"],
                    "coordinate_quality": actual["coordinate_quality"],
                },
                "replay": mission["replay"],
            }
        )
    return deepcopy(summaries)


def get_mission(mission_id: str) -> dict[str, Any] | None:
    """Return a full mission record, or None for an unknown ID."""
    mission = MISSION_BY_ID.get(mission_id)
    return deepcopy(mission) if mission is not None else None


def get_replay_inputs(
    mission_id: str,
    duration_hours: int = DEFAULT_REPLAY_DURATION_HOURS,
) -> dict[str, Any] | None:
    """Return validated historical inputs for the shared visibility engine.

    The caller should return a clear client error if the mission is unknown, replay is not
    eligible, or ``duration_hours`` fails the engine's own duration limits.
    """
    mission = MISSION_BY_ID.get(mission_id)
    if mission is None or not mission["replay"]["status"].startswith("eligible"):
        return None

    selected_location = mission[mission["replay"]["location_field"]]
    return {
        "latitude_deg": selected_location["latitude_deg"],
        "longitude_deg": selected_location["longitude_deg"],
        "start_utc": mission["event_time_utc"],
        "duration_hours": duration_hours,
        "historical_context": {
            "mission_id": mission["id"],
            "location_label": mission["replay"]["label"],
            "location_type": selected_location["location_type"],
            "coordinate_quality": selected_location["coordinate_quality"],
        },
    }


__all__ = [
    "COORDINATE_CONVENTION",
    "DEFAULT_REPLAY_DURATION_HOURS",
    "MISSION_BY_ID",
    "MISSIONS",
    "SOURCES",
    "get_mission",
    "get_replay_inputs",
    "list_mission_summaries",
]
