"""Enlace de visitas a fondeaderos con el tránsito siguiente (tarea 6.2)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.services.waiting import (
    CLOCK_TOLERANCE,
    MAX_WAIT_GAP,
    TransitCandidate,
    VisitCandidate,
    entry_side,
    match_visits_to_transits,
    precedes,
)

T0 = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)
MMSI = 352000001


def visit(
    arrived: float,
    departed: float | None,
    *,
    anchorage: str = "atlantic",
    mmsi: int = MMSI,
) -> VisitCandidate:
    return VisitCandidate(
        id=uuid4(),
        mmsi=mmsi,
        anchorage=anchorage,
        arrived_at=T0 + timedelta(hours=arrived),
        departed_at=None if departed is None else T0 + timedelta(hours=departed),
    )


def transit(entered: float, *, direction: str = "southbound", mmsi: int = MMSI) -> TransitCandidate:
    return TransitCandidate(
        id=uuid4(), mmsi=mmsi, direction=direction, entered_at=T0 + timedelta(hours=entered)
    )


def ids(pairs: list[tuple[UUID, UUID]]) -> set[tuple[UUID, UUID]]:
    return set(pairs)


def test_the_side_to_wait_at_depends_on_the_direction() -> None:
    assert entry_side("southbound") == "atlantic"
    assert entry_side("northbound") == "pacific"


def test_a_wait_before_a_transit_is_linked() -> None:
    v, t = visit(0, 10), transit(10.2)

    assert match_visits_to_transits([v], [t]) == [(v.id, t.id)]


def test_a_northbound_transit_waits_at_the_pacific_anchorage() -> None:
    v, t = visit(0, 10, anchorage="pacific"), transit(10.2, direction="northbound")

    assert match_visits_to_transits([v], [t]) == [(v.id, t.id)]


def test_the_anchorage_must_be_on_the_entry_side() -> None:
    # Esperó en el Pacífico y su siguiente tránsito entra por el Atlántico: no es esa espera.
    v, t = visit(0, 10, anchorage="pacific"), transit(10.2, direction="southbound")

    assert match_visits_to_transits([v], [t]) == []


def test_only_the_same_vessel_counts() -> None:
    v, t = visit(0, 10), transit(10.2, mmsi=352000002)

    assert match_visits_to_transits([v], [t]) == []


def test_a_visit_after_the_transit_started_is_not_its_wait() -> None:
    assert match_visits_to_transits([visit(11, 12)], [transit(10)]) == []


def test_a_visit_that_arrived_exactly_when_the_transit_started_is_not_its_wait() -> None:
    assert not precedes(visit(10, 11), transit(10))


def test_a_visit_still_open_is_linked() -> None:
    v, t = visit(0, None), transit(10)

    assert match_visits_to_transits([v], [t]) == [(v.id, t.id)]


def test_the_clock_tolerance_covers_a_visit_closed_a_moment_after_the_transit_opened() -> None:
    inside = timedelta(minutes=9)
    outside = timedelta(minutes=11)
    base = T0 + timedelta(hours=10)
    t = TransitCandidate(uuid4(), MMSI, "southbound", base)
    close = VisitCandidate(uuid4(), MMSI, "atlantic", T0, base + inside)
    late = VisitCandidate(uuid4(), MMSI, "atlantic", T0, base + outside)

    assert precedes(close, t)
    assert not precedes(late, t)
    assert timedelta(minutes=9) < CLOCK_TOLERANCE < timedelta(minutes=11)


def test_a_wait_that_ended_too_long_before_the_transit_is_not_linked() -> None:
    gap = MAX_WAIT_GAP.total_seconds() / 3600
    just_in = visit(0, 10)
    too_old = visit(0, 10)

    assert precedes(just_in, transit(10 + gap))
    assert not precedes(too_old, transit(10 + gap + 0.1))


def test_each_transit_gets_the_most_recent_visit() -> None:
    older, newer = visit(0, 5), visit(6, 10)
    t = transit(10.2)

    assert match_visits_to_transits([older, newer], [t]) == [(newer.id, t.id)]
    assert match_visits_to_transits([newer, older], [t]) == [(newer.id, t.id)]


def test_each_visit_gets_the_first_transit_after_it() -> None:
    v = visit(0, 10)
    first, second = transit(10.2), transit(30)

    assert match_visits_to_transits([v], [second, first]) == [(v.id, first.id)]


def test_two_waits_and_two_transits_pair_up_in_order() -> None:
    v1, v2 = visit(0, 10), visit(12, 20)
    t1, t2 = transit(10.2), transit(20.2)

    assert ids(match_visits_to_transits([v1, v2], [t1, t2])) == {(v1.id, t1.id), (v2.id, t2.id)}


def test_vessels_are_matched_independently() -> None:
    a, b = visit(0, 10), visit(0, 10, mmsi=352000002)
    ta, tb = transit(10.2), transit(10.2, mmsi=352000002)

    assert ids(match_visits_to_transits([a, b], [ta, tb])) == {(a.id, ta.id), (b.id, tb.id)}


def test_nothing_to_match() -> None:
    assert match_visits_to_transits([], []) == []
    assert match_visits_to_transits([visit(0, 1)], []) == []
    assert match_visits_to_transits([], [transit(1)]) == []
