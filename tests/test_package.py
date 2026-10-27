"""Tests for the Phase 0A package contract."""

import switchboard


def test_package_imports_with_version() -> None:
    """The installed package should import without custom path manipulation."""
    assert switchboard.__version__ == "0.1.0"
