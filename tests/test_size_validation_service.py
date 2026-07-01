from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services import size_validation_service


def _set_size_command(size_inches: int) -> NormalizedCommand:
    return NormalizedCommand(
        command=CommandName.SET_SIZE,
        confidence=0.9,
        method=MatchMethod.llm,
        size_inches=size_inches,
    )


def test_dynamic_size_accepts_value_inside_configured_range(monkeypatch) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )

    command = _set_size_command(72)

    assert command.size_inches == 72
    assert size_validation_service.is_valid_size_inches(72) is True


@pytest.mark.parametrize("size_inches", [39, 151])
def test_dynamic_size_rejects_value_outside_configured_range(
    monkeypatch,
    size_inches: int,
) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )

    with pytest.raises(ValidationError):
        _set_size_command(size_inches)


def test_fixed_size_mode_accepts_configured_size(monkeypatch) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: False,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int_list",
        lambda key, default: [55, 65, 75, 95, 120],
    )

    command = _set_size_command(55)

    assert command.size_inches == 55
    assert size_validation_service.is_valid_size_inches(55) is True


def test_fixed_size_mode_rejects_unconfigured_size(monkeypatch) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: False,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int_list",
        lambda key, default: [55, 65, 75, 95, 120],
    )

    with pytest.raises(ValidationError):
        _set_size_command(72)
