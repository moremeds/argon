from uw_scan.cards.magnets import build_read

_LEVELS = {
    "resistance": 340.08,
    "support": 275.15,
    "stretch": 380.21,
    "down": 235.02,
    "sma20": 320.0,
    "last": 313.33,
    "leg_state": "falling",
    "pivot_a": {"index": 14, "kind": "bottom", "price": 275.15},
    "pivot_b": {"index": 36, "kind": "top", "price": 340.08},
}


def _band(
    sigma: float, conf: float, lo: float, hi: float, up: float, dn: float
) -> dict:
    return {
        "horizon": 10,
        "band_sigma": sigma,
        "measured_confidence": conf,
        "measured_ci_lo": lo,
        "measured_ci_hi": hi,
        "measured_n_dates": 144,
        "upper": up,
        "lower": dn,
    }


_BANDS = [
    _band(1.0, 0.712, 0.666, 0.758, 328.0, 299.0),
    _band(1.96, 0.947, 0.924, 0.965, 343.0, 286.0),
]


def test_read_never_states_a_price_target():
    joined = " ".join(build_read(_LEVELS, _BANDS)).lower()
    assert "target" not in joined
    assert "will " not in joined


def test_read_flags_when_the_0618_stretch_sits_outside_the_cone():
    # stretch 380.21 is above the 1.96 sigma upper of 343.0 -> must be called out
    assert "outside" in " ".join(build_read(_LEVELS, _BANDS)).lower()


def test_read_flags_the_downside_too():
    assert "outside" in " ".join(build_read(_LEVELS, _BANDS)).lower()


def test_read_marks_the_0618_level_as_having_no_measured_edge():
    assert any("no measured edge" in line for line in build_read(_LEVELS, _BANDS))


def test_read_quotes_the_widest_band_not_the_narrowest():
    joined = " ".join(build_read(_LEVELS, _BANDS))
    assert "343.00" in joined and "286.00" in joined


def test_read_quotes_the_10d_band_when_several_horizons_are_present():
    # max(key=band_sigma) would return the 5d entry (first tie wins). The read
    # must name 10d.
    five = [
        {**b, "horizon": 5, "upper": b["upper"] + 50, "lower": b["lower"] - 50}
        for b in _BANDS
    ]
    joined = " ".join(build_read(_LEVELS, [*five, *_BANDS]))
    assert "10d range" in joined
    assert "393.00" not in joined  # the 5d upper, deliberately not quoted


def test_read_survives_an_empty_band_list():
    lines = build_read(_LEVELS, [])
    assert lines and all(isinstance(x, str) for x in lines)


def test_read_survives_a_missing_sma20():
    lines = build_read({**_LEVELS, "sma20": None}, _BANDS)
    assert not any("SMA20" in line for line in lines)


def test_read_is_deterministic():
    assert build_read(_LEVELS, _BANDS) == build_read(_LEVELS, _BANDS)
