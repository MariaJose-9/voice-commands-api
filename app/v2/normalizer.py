from __future__ import annotations

"""Flexible v2 normalizer that can return core and custom commands."""

import re
from typing import Optional

from app import config
from app.entity_extractor import extract_entities
from app.normalizer import normalize_command_text
from app.preprocessor import normalize_text
from app.services import runtime_settings_service
from app.services.command_spec_service import CommandSpec, get_active_command_specs
from app.v2.adapter import v1_response_to_v2
from app.v2.dynamic_command_validation import validate_dynamic_command
from app.v2.llm_interpreter import interpret_dynamic_commands_with_llm
from app.v2.schemas import DynamicCommand, NormalizeV2Response


def _llm_enabled() -> bool:
    enabled = runtime_settings_service.get_runtime_bool_setting(
        "ENABLE_OLLAMA_FALLBACK",
        config.ENABLE_OLLAMA_FALLBACK,
    )
    mode = runtime_settings_service.get_runtime_str_setting(
        "LLM_COMMAND_MODE",
        config.LLM_COMMAND_MODE,
    )
    return enabled and mode != "off"


def _command_key(command: DynamicCommand) -> tuple:
    return (command.code, tuple(sorted(command.params.items())))


_NUMBER_WORDS = {
    "zero": 0,
    "cero": 0,
    "one": 1,
    "uno": 1,
    "una": 1,
    "two": 2,
    "dos": 2,
    "three": 3,
    "tres": 3,
    "four": 4,
    "cuatro": 4,
    "five": 5,
    "cinco": 5,
    "six": 6,
    "seis": 6,
    "seven": 7,
    "siete": 7,
    "eight": 8,
    "ocho": 8,
    "nine": 9,
    "nueve": 9,
    "ten": 10,
    "diez": 10,
    "twenty": 20,
    "veinte": 20,
    "thirty": 30,
    "treinta": 30,
    "forty": 40,
    "cuarenta": 40,
    "fifty": 50,
    "cincuenta": 50,
    "sixty": 60,
    "sesenta": 60,
    "seventy": 70,
    "setenta": 70,
    "eighty": 80,
    "ochenta": 80,
    "ninety": 90,
    "noventa": 90,
    "hundred": 100,
    "cien": 100,
    "ciento": 100,
}


def _extract_first_number(normalized_text: str) -> int | float | None:
    match = re.search(r"\b\d+(?:\.\d+)?\b", normalized_text)
    if match:
        value = match.group(0)
        return float(value) if "." in value else int(value)

    tokens = [token for token in normalized_text.split() if token != "y"]
    for index, token in enumerate(tokens):
        if token not in _NUMBER_WORDS:
            continue
        value = _NUMBER_WORDS[token]
        if value in {20, 30, 40, 50, 60, 70, 80, 90} and index + 1 < len(tokens):
            next_value = _NUMBER_WORDS.get(tokens[index + 1])
            if next_value is not None and 0 < next_value < 10:
                return value + next_value
        return value
    return None


def _word_number_before_units(normalized_text: str, units: set[str]) -> int | None:
    tokens = normalized_text.split()
    for index, token in enumerate(tokens):
        if token not in units:
            continue
        previous = [item for item in tokens[max(0, index - 3) : index] if item != "y"]
        for start in range(len(previous)):
            chunk = previous[start:]
            if not chunk:
                continue
            first = _NUMBER_WORDS.get(chunk[0])
            if first is None:
                continue
            if (
                len(chunk) >= 2
                and first in {20, 30, 40, 50, 60, 70, 80, 90}
                and 0 < _NUMBER_WORDS.get(chunk[1], 0) < 10
            ):
                return first + _NUMBER_WORDS[chunk[1]]
            return first
    return None


def _extract_number_for_parameter(parameter, normalized_text: str) -> int | float | None:
    if "angle" in parameter.target_field or "degree" in parameter.entity_code:
        digit_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(?:grados?|degrees?)\b",
            normalized_text,
        )
        if digit_match:
            value = digit_match.group(1)
            return float(value) if "." in value else int(value)
        word_value = _word_number_before_units(
            normalized_text,
            {"grado", "grados", "degree", "degrees"},
        )
        if word_value is not None:
            return word_value
        return None
    return _extract_first_number(normalized_text)


def _spec_matches_text(spec: CommandSpec, normalized_text: str) -> bool:
    text_tokens = set(normalized_text.split())
    if not text_tokens:
        return False
    for example in spec.examples:
        normalized_example = normalize_text(example)
        if not normalized_example:
            continue
        if normalized_example in normalized_text:
            return True
        example_tokens = set(normalized_example.split())
        if not example_tokens:
            continue
        overlap = len(text_tokens & example_tokens) / len(example_tokens)
        if overlap >= 0.55:
            return True
    return False


def _params_for_custom_spec(
    spec: CommandSpec,
    normalized_text: str,
    base_commands: list[DynamicCommand],
) -> dict:
    params = {}
    entities = extract_entities(normalized_text)
    for command in base_commands:
        if command.code == "SELECT_MONITOR" and "monitor" in command.params:
            params.setdefault("monitor", command.params["monitor"])

    for parameter in spec.parameters:
        target_field = parameter.target_field
        if target_field in params:
            continue
        if parameter.entity_code == "monitor" and entities.get("monitor") is not None:
            params[target_field] = entities["monitor"]
            continue
        if parameter.entity_code == "layout" and entities.get("layout") is not None:
            params[target_field] = entities["layout"]
            continue
        if parameter.entity_code == "size_inches" and entities.get("size_inches") is not None:
            params[target_field] = entities["size_inches"]
            continue
        if parameter.data_type in {"integer", "float"}:
            number = _extract_number_for_parameter(parameter, normalized_text)
            if number is not None:
                params[target_field] = int(number) if parameter.data_type == "integer" else float(number)
    return params


def _match_custom_commands_from_specs(
    *,
    normalized_text: str,
    specs: list[CommandSpec],
    base_commands: list[DynamicCommand],
    client_capabilities: Optional[list[str]],
) -> tuple[list[DynamicCommand], bool, str | None]:
    commands: list[DynamicCommand] = []
    needs_confirmation = False
    message = None
    for spec in specs:
        if spec.command_type != "custom" or not _spec_matches_text(spec, normalized_text):
            continue
        candidate = DynamicCommand(
            code=spec.code,
            type="custom",
            client_action_key=spec.client_action_key,
            confidence=0.88,
            method="custom_example",
            params=_params_for_custom_spec(spec, normalized_text, base_commands),
            raw_fragment=normalized_text,
        )
        try:
            commands.append(
                validate_dynamic_command(
                    candidate,
                    specs,
                    client_capabilities=client_capabilities,
                )
            )
        except ValueError as exc:
            needs_confirmation = True
            message = str(exc)
    return commands, needs_confirmation, message


def normalize_command_text_v2(
    text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
    client_capabilities: Optional[list[str]] = None,
) -> NormalizeV2Response:
    """Normalize text into the flexible v2 response shape."""

    base_v1_response = normalize_command_text(
        text=text,
        language_hint=language_hint,
        context=context,
    )
    response = v1_response_to_v2(base_v1_response)

    specs = get_active_command_specs()
    commands = list(response.commands)
    needs_confirmation = response.needs_confirmation
    message = response.message

    custom_commands, custom_needs_confirmation, custom_message = (
        _match_custom_commands_from_specs(
            normalized_text=response.normalized_text,
            specs=specs,
            base_commands=commands,
            client_capabilities=client_capabilities,
        )
    )
    if custom_commands:
        seen = {_command_key(command) for command in commands}
        for command in custom_commands:
            key = _command_key(command)
            if key not in seen:
                commands.append(command)
                seen.add(key)
    if custom_needs_confirmation:
        needs_confirmation = True
        message = f"{message}; {custom_message}" if message and custom_message else custom_message or message

    if _llm_enabled():
        llm_result = interpret_dynamic_commands_with_llm(
            raw_text=text,
            normalized_text=response.normalized_text,
            language_hint=language_hint,
            context=context,
            previous_commands=commands,
            specs=specs,
            client_capabilities=client_capabilities,
        )
        if isinstance(llm_result, tuple):
            llm_commands, llm_needs_confirmation = llm_result
            needs_confirmation = needs_confirmation or llm_needs_confirmation
        else:
            llm_commands = llm_result
        seen = {_command_key(command) for command in commands}
        accepted: list[DynamicCommand] = []
        rejected = False
        for command in llm_commands:
            try:
                validated = validate_dynamic_command(
                    command,
                    specs,
                    client_capabilities=client_capabilities,
                )
            except ValueError:
                rejected = True
                continue
            key = _command_key(validated)
            if key in seen:
                continue
            seen.add(key)
            accepted.append(validated)
        commands.extend(accepted)
        if rejected:
            needs_confirmation = True
            message = (
                f"{message}; Some v2 dynamic commands were rejected"
                if message
                else "Some v2 dynamic commands were rejected"
            )

    return NormalizeV2Response(
        ok=response.ok and all(command.code != "UNKNOWN" for command in commands),
        raw_text=response.raw_text,
        normalized_text=response.normalized_text,
        language=response.language,
        commands=commands,
        needs_confirmation=needs_confirmation,
        message=message,
    )
