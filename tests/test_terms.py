from datetime import date

import pytest

from mindtrail.organize.terms import (
    clean_term, next_term, term_of, term_rank, year_of, year_terms,
)


def test_dates_map_to_the_term_they_fall_in():
    assert term_of(date(2026, 1, 5)) == "2026-winter"
    assert term_of(date(2026, 5, 1)) == "2026-spring"
    assert term_of(date(2026, 7, 4)) == "2026-summer"
    assert term_of(date(2026, 10, 13)) == "2026-fall"
    assert term_of(date(2026, 12, 20)) == "2026-fall"


def test_next_term_walks_the_academic_year_and_ranks_increase():
    t = "2025-fall"
    seen = [t]
    for _ in range(8):
        t = next_term(t)
        seen.append(t)
    assert seen[:5] == ["2025-fall", "2026-winter", "2026-spring", "2026-summer", "2026-fall"]
    assert [term_rank(x) for x in seen] == sorted(term_rank(x) for x in seen)
    assert len(set(term_rank(x) for x in seen)) == len(seen)


def test_every_term_of_a_year_belongs_to_that_year():
    for number in range(1, 5):
        for term in year_terms(2025, number):
            assert year_of(term, 2025) == number


def test_clean_term_accepts_blank_and_rejects_nonsense():
    assert clean_term("") == "" and clean_term(" 2026-Fall ") == "2026-fall"
    with pytest.raises(ValueError):
        clean_term("fall 2026")
