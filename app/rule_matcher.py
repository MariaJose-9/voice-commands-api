"""Rule-based command matching."""

from __future__ import annotations

import re
from typing import Optional

from app.schemas import CommandName, MatchMethod, NormalizedCommand


_SPECIAL_RULES: list[tuple[CommandName, list[str]]] = [
    (
        CommandName.STOP_FOLLOW_ME,
        [
            "stop follow me",
            "stop following me",
            "deja de seguirme",
            "detener seguimiento",
            "parar seguimiento",
            "desactivar seguimiento",
        ],
    ),
    (
        CommandName.STOP_STREAM,
        [
            "stop stream",
            "stop streaming",
            "detener stream",
            "parar stream",
            "detener transmision",
        ],
    ),
]

_EXACT_RULES: list[tuple[CommandName, list[str]]] = [
    (
        CommandName.RECENTER_OBJECTS,
        ["recenter objects", "center objects", "recentrar objetos", "centrar objetos"],
    ),
    (CommandName.MOVE_LEFT, ["left", "izquierda"]),
    (CommandName.MOVE_RIGHT, ["right", "derecha"]),
    (CommandName.MOVE_UP, ["up", "arriba"]),
    (CommandName.MOVE_DOWN, ["down", "abajo"]),
    (CommandName.ZOOM_IN, ["zoom in", "acercar", "haz zoom"]),
    (CommandName.ZOOM_OUT, ["zoom out", "alejar", "quitar zoom"]),
    (CommandName.INCREASE_SIZE, ["increase", "aumenta", "agranda"]),
    (CommandName.DECREASE_SIZE, ["decrease", "disminuye", "reduce"]),
    (CommandName.FOLLOW_ME, ["follow me", "sigueme", "que me siga"]),
    (
        CommandName.RESET_POSITION,
        ["reset position", "restaurar posicion", "posicion inicial"],
    ),
    (CommandName.SHOW_AITROL, ["show aitrol", "open aitrol", "mostrar aitrol", "abre aitrol"]),
    (CommandName.CLOSE_AITROL, ["close aitrol", "cerrar aitrol", "cierra aitrol"]),
    (
        CommandName.SHOW_VOICE_COMMANDS,
        ["show voice commands", "show voice command", "mostrar comandos de voz"],
    ),
    (
        CommandName.CLOSE_VOICE_COMMANDS,
        ["close voice commands", "close voice command", "cerrar comandos de voz"],
    ),
    (
        CommandName.OPEN_SETTINGS,
        ["settings", "ajustes", "configuracion"],
    ),
    (CommandName.CAPTURE, ["capture", "screenshot", "captura", "pantallazo"]),
    (CommandName.START_STREAM, ["stream", "start stream", "iniciar stream", "transmitir"]),
    (
        CommandName.START_RECORDING,
        ["record", "start recording", "grabar", "iniciar grabacion"],
    ),
    (CommandName.STOP_ACTIVE, ["stop", "detener", "parar", "cancelar"]),
]

_SUPPRESSION_RULES: dict[CommandName, set[CommandName]] = {
    CommandName.STOP_FOLLOW_ME: {CommandName.FOLLOW_ME, CommandName.STOP_ACTIVE},
    CommandName.STOP_STREAM: {CommandName.STOP_ACTIVE, CommandName.START_STREAM},
    CommandName.RECENTER_OBJECTS: {
        CommandName.MOVE_LEFT,
        CommandName.MOVE_RIGHT,
        CommandName.MOVE_UP,
        CommandName.MOVE_DOWN,
    },
}


def _find_fragment(text: str, aliases: list[str]) -> Optional[str]:
    """Return the first alias present in text."""

    for alias in aliases:
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return alias
    return None


def _append_command(
    commands: list[NormalizedCommand],
    seen: set[CommandName],
    command: NormalizedCommand,
) -> None:
    """Append a command once, preserving insertion order."""

    if command.command in seen:
        return

    commands.append(command)
    seen.add(command.command)


def _entity_command(
    command: CommandName,
    raw_fragment: Optional[str],
    *,
    monitor: Optional[int] = None,
    layout: Optional[int] = None,
    size_inches: Optional[int] = None,
) -> NormalizedCommand:
    """Create an entity-based normalized command."""

    return NormalizedCommand(
        command=command,
        confidence=1.0,
        method=MatchMethod.entity_rule,
        raw_fragment=raw_fragment,
        monitor=monitor,
        layout=layout,
        size_inches=size_inches,
    )


def _exact_command(command: CommandName, raw_fragment: str) -> NormalizedCommand:
    """Create an exact-rule normalized command."""

    return NormalizedCommand(
        command=command,
        confidence=1.0,
        method=MatchMethod.exact_rule,
        raw_fragment=raw_fragment,
    )


def match_by_rules(normalized_text: str, entities: dict) -> list[NormalizedCommand]:
    """Match commands using ordered deterministic rules."""

    commands: list[NormalizedCommand] = []
    seen: set[CommandName] = set()
    suppressed: set[CommandName] = set()

    for command_name, aliases in _SPECIAL_RULES:
        fragment = _find_fragment(normalized_text, aliases)
        if not fragment:
            continue

        _append_command(commands, seen, _exact_command(command_name, fragment))
        suppressed.update(_SUPPRESSION_RULES.get(command_name, set()))

    monitor = entities.get("monitor")
    if monitor in {1, 2}:
        _append_command(
            commands,
            seen,
            _entity_command(
                CommandName.SELECT_MONITOR,
                f"monitor {monitor}",
                monitor=monitor,
            ),
        )

    layout = entities.get("layout")
    if layout in {1, 2}:
        _append_command(
            commands,
            seen,
            _entity_command(CommandName.SET_LAYOUT, f"layout {layout}", layout=layout),
        )

    size_inches = entities.get("size_inches")
    if size_inches in {55, 65, 75, 95, 120}:
        _append_command(
            commands,
            seen,
            _entity_command(
                CommandName.SET_SIZE,
                str(size_inches),
                size_inches=size_inches,
            ),
        )

    for command_name, aliases in _EXACT_RULES:
        if command_name in suppressed or command_name in seen:
            continue

        fragment = _find_fragment(normalized_text, aliases)
        if not fragment:
            continue

        _append_command(commands, seen, _exact_command(command_name, fragment))
        suppressed.update(_SUPPRESSION_RULES.get(command_name, set()))

    return commands
