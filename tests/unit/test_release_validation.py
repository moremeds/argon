from __future__ import annotations

import pytest

from scripts.release.validate_release import ReleaseValidationError, validate_release


def test_current_final_release_is_valid():
    result = validate_release(
        tag_name="v1.2.3",
        file_version="1.2.3",
        main_version="1.2.3",
    )

    assert result.tag_version == "1.2.3"
    assert result.base_version == "1.2.3"
    assert result.prerelease is False


def test_current_prerelease_is_valid_without_changing_base_version():
    result = validate_release(
        tag_name="v1.2.3-rc.1",
        file_version="1.2.3",
        main_version="1.2.3",
    )

    assert result.tag_version == "1.2.3-rc.1"
    assert result.base_version == "1.2.3"
    assert result.prerelease is True


@pytest.mark.parametrize(
    "tag_name",
    [
        "v1.2",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        "v1.2.3-",
        "v1.2.3-rc..1",
        "v1.2.3-$(touch-pwned)",
        "v1.2.3;echo-pwned",
        "release-1.2.3",
    ],
)
def test_non_semver_or_shell_metacharacter_tag_is_rejected(tag_name: str):
    with pytest.raises(ReleaseValidationError, match="strict release SemVer"):
        validate_release(
            tag_name=tag_name,
            file_version="1.2.3",
            main_version="1.2.3",
        )


def test_tag_must_match_the_version_in_its_commit():
    with pytest.raises(ReleaseValidationError, match="does not match VERSION"):
        validate_release(
            tag_name="v1.2.4",
            file_version="1.2.3",
            main_version="1.2.3",
        )


def test_historical_release_rerun_is_rejected_after_main_version_advances():
    with pytest.raises(ReleaseValidationError, match="historical release replay"):
        validate_release(
            tag_name="v1.2.3",
            file_version="1.2.3",
            main_version="1.2.4",
        )
