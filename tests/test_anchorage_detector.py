"""Detector de esperas en fondeo (tarea 6.1): trayectorias sintéticas."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.ais_parser import PositionUpdate
from app.services.anchorage_detector import (
    MIN_STAY,
    AnchorageEvent,
    AnchorageTrack,
    VisitEnded,
    VisitStarted,
    expire,
    on_position,
)

MMSI = 353_123_000
T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)

ATLANTIC = (-79.85, 9.45)
PACIFIC = (-79.52, 8.84)
OUTSIDE = (-79.70, 9.60)


def position(
    minutes: float,
    point: tuple[float, float] = ATLANTIC,
    *,
    sog: float | None = 0.1,
    nav_status: int | None = 1,
) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=MMSI,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=None,
        heading=None,
        nav_status=nav_status,
    )


def feed(
    positions: list[PositionUpdate], track: AnchorageTrack | None = None
) -> tuple[AnchorageTrack, list[AnchorageEvent]]:
    track = track or AnchorageTrack(mmsi=MMSI)
    events: list[AnchorageEvent] = []
    for item in positions:
        track, produced = on_position(track, item, timeout=TIMEOUT)
        events.extend(produced)
    return track, events


def every(minutes: range, **kwargs: object) -> list[PositionUpdate]:
    return [position(m, **kwargs) for m in minutes]  # type: ignore[arg-type]


def test_a_vessel_stopped_for_the_minimum_stay_opens_a_visit_from_when_it_stopped() -> None:
    track, events = feed(every(range(0, 20, 5)))

    assert events == [VisitStarted(mmsi=MMSI, anchorage="atlantic", arrived_at=T0)]
    assert track.visit is not None
    assert track.visit.arrived_at == T0


def test_a_stop_shorter_than_the_minimum_stay_leaves_no_trace() -> None:
    track, events = feed([*every(range(0, 15, 5)), position(18, sog=6.0, nav_status=0)])

    assert events == []
    assert track.visit is None
    assert track.candidate is None


def test_exactly_the_minimum_stay_counts() -> None:
    _, events = feed([position(0), position(MIN_STAY.total_seconds() / 60)])

    assert [type(event) for event in events] == [VisitStarted]


def test_just_under_the_minimum_stay_does_not() -> None:
    _, events = feed([position(0), position(MIN_STAY.total_seconds() / 60 - 0.1)])

    assert events == []


def test_the_visit_ends_when_the_vessel_starts_moving() -> None:
    _, events = feed([*every(range(0, 60, 5)), position(60, sog=4.0, nav_status=0)])

    started, ended = events
    assert isinstance(started, VisitStarted)
    assert ended == VisitEnded(
        mmsi=MMSI,
        anchorage="atlantic",
        arrived_at=T0,
        departed_at=T0 + timedelta(minutes=60),
    )
    assert isinstance(ended, VisitEnded)
    assert ended.duration == timedelta(hours=1)


def test_the_visit_ends_when_the_vessel_leaves_the_polygon() -> None:
    _, events = feed([*every(range(0, 30, 5)), position(30, OUTSIDE, sog=0.2)])

    assert [type(event) for event in events] == [VisitStarted, VisitEnded]


def test_drifting_between_half_and_one_knot_neither_confirms_nor_breaks() -> None:
    drifting = [position(m, sog=0.7) for m in range(0, 60, 5)]
    track, events = feed([*every(range(0, 20, 5)), *drifting[4:]])

    assert [type(event) for event in events] == [VisitStarted]
    assert track.visit is not None  # el borneo no cierra la visita

    # Y por sí solo tampoco la abre.
    _, none = feed(drifting)
    assert none == []


def test_a_vessel_that_never_slows_down_in_the_anchorage_opens_nothing() -> None:
    _, events = feed([position(m, sog=7.0, nav_status=0) for m in range(0, 120, 5)])

    assert events == []


def test_nav_status_decides_only_when_there_is_no_speed() -> None:
    anchored_no_speed, started = feed(every(range(0, 20, 5), sog=None, nav_status=1))
    underway_no_speed, none = feed(every(range(0, 20, 5), sog=None, nav_status=0))
    fast_but_status_anchored, also_none = feed(every(range(0, 20, 5), sog=8.0, nav_status=1))

    assert [type(event) for event in started] == [VisitStarted]
    assert none == [] and also_none == []
    assert underway_no_speed.visit is None and fast_but_status_anchored.visit is None
    assert anchored_no_speed.visit is not None


def test_the_pacific_anchorage_is_a_different_visit() -> None:
    _, events = feed(every(range(0, 20, 5), point=PACIFIC))

    assert events == [VisitStarted(mmsi=MMSI, anchorage="pacific", arrived_at=T0)]


def test_moving_from_one_anchorage_to_the_other_ends_one_and_restarts_the_clock() -> None:
    track, events = feed([*every(range(0, 30, 5)), position(35, PACIFIC), position(45, PACIFIC)])

    assert [type(event) for event in events] == [VisitStarted, VisitEnded]
    assert track.visit is None
    assert track.candidate is not None
    assert track.candidate.anchorage == "pacific"
    assert track.candidate.since == T0 + timedelta(minutes=35)


def test_stopped_outside_every_anchorage_does_nothing() -> None:
    track, events = feed(every(range(0, 120, 5), point=OUTSIDE))

    assert (events, track.visit, track.candidate) == ([], None, None)


def test_a_candidate_is_dropped_when_the_vessel_leaves_before_the_minimum() -> None:
    track, _ = feed([*every(range(0, 10, 5)), position(10, OUTSIDE)])

    assert track.candidate is None
    # Vuelve y se para otra vez: el reloj empieza de cero, no cuenta lo anterior.
    _, events = feed([position(12), position(20)], track)
    assert events == []


def test_a_position_not_newer_than_the_last_is_ignored() -> None:
    track, _ = feed([position(10)])

    same, same_events = on_position(track, position(10), timeout=TIMEOUT)
    older, older_events = on_position(track, position(5), timeout=TIMEOUT)

    assert (same, same_events, older, older_events) == (track, [], track, [])


def test_the_state_is_immutable() -> None:
    track = AnchorageTrack(mmsi=MMSI)

    new_track, _ = on_position(track, position(0), timeout=TIMEOUT)

    assert track.candidate is None and track.last_seen_at is None
    assert new_track.candidate is not None


# --- Señal ----------------------------------------------------------------------------------


def opened() -> AnchorageTrack:
    track, _ = feed(every(range(0, 30, 5)))
    return track


def test_expire_leaves_a_visit_alone_until_the_timeout_is_exceeded() -> None:
    track = opened()
    last = T0 + timedelta(minutes=25)

    same, events = expire(track, last + TIMEOUT, timeout=TIMEOUT)  # justo el límite

    assert (same, events) == (track, [])


def test_expire_ends_the_visit_at_the_last_signal_not_at_now() -> None:
    track = opened()
    last = T0 + timedelta(minutes=25)

    after, events = expire(track, last + TIMEOUT + timedelta(hours=5), timeout=TIMEOUT)

    assert events == [VisitEnded(mmsi=MMSI, anchorage="atlantic", arrived_at=T0, departed_at=last)]
    assert after.visit is None


def test_expire_does_nothing_for_a_vessel_never_seen() -> None:
    track = AnchorageTrack(mmsi=MMSI)

    assert expire(track, T0, timeout=TIMEOUT) == (track, [])


def test_a_late_position_closes_the_old_visit_at_its_last_signal_first() -> None:
    track = opened()

    after, events = on_position(track, position(25 + 90, sog=0.1), timeout=TIMEOUT)

    assert events == [
        VisitEnded(
            mmsi=MMSI,
            anchorage="atlantic",
            arrived_at=T0,
            departed_at=T0 + timedelta(minutes=25),
        )
    ]
    # Y la que llega tarde empieza un candidato nuevo: no cuenta como continuación.
    assert after.visit is None
    assert after.candidate is not None
    assert after.candidate.since == T0 + timedelta(minutes=115)


def test_after_a_gap_a_vessel_has_to_stay_the_minimum_again() -> None:
    track = opened()

    _, events = feed([position(115), position(125)], track)
    assert [type(event) for event in events] == [VisitEnded]

    _, more = feed([position(115), position(131)], track)
    assert [type(event) for event in more] == [VisitEnded, VisitStarted]


@pytest.mark.parametrize("gap_minutes", [5, 29])
def test_gaps_under_the_timeout_keep_the_visit_open(gap_minutes: int) -> None:
    track, events = feed([*every(range(0, 20, 5)), position(15 + gap_minutes)])

    assert [type(event) for event in events] == [VisitStarted]
    assert track.visit is not None
