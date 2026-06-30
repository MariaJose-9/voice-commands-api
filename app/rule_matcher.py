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
            "end stream",
            "stop transmission",
            "stop broadcast",
            "stop live",
            "detener stream",
            "deten stream",
            "parar stream",
            "detener transmision",
            "deten la transmision",
            "corta la transmision",
            "para la transmision",
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
    (
        CommandName.ZOOM_IN,
        ["zoom in", "acercar", "haz zoom", "aumenta el zoom"],
    ),
    (
        CommandName.ZOOM_OUT,
        ["zoom out", "alejar", "quitar zoom", "quita zoom", "reduce el zoom"],
    ),
    (CommandName.FOLLOW_ME, ["follow me", "sigueme", "que me siga"]),
    (
        CommandName.RESET_POSITION,
        ["reset position", "restaurar posicion", "posicion inicial"],
    ),
    (
        CommandName.SHOW_AITROL,
        ["show aitrol", "open aitrol", "mostrar aitrol", "abre aitrol", "abrir aitrol"],
    ),
    (CommandName.CLOSE_AITROL, ["close aitrol", "cerrar aitrol", "cierra aitrol"]),
    (
        CommandName.SHOW_VOICE_COMMANDS,
        [
            "show voice commands",
            "show voice command",
            "mostrar comandos de voz",
            "ayuda de voz",
            "abre ayuda de voz",
            "muestra la ayuda de voz",
            "muestrame los comandos",
            "que comandos puedo decir",
            "abre el panel de ayuda",
            "abre panel de comandos",
        ],
    ),
    (
        CommandName.CLOSE_VOICE_COMMANDS,
        [
            "close voice commands",
            "close voice command",
            "cerrar comandos de voz",
            "cierra ayuda de voz",
            "oculta ayuda de voz",
            "cierra el panel de ayuda",
            "cierra panel de comandos",
            "quita los comandos de voz",
        ],
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

_PRE_RELATIVE_RULES: list[tuple[CommandName, list[str]]] = [
    (
        CommandName.ZOOM_IN,
        ["zoom in", "acercar", "haz zoom", "aumenta el zoom"],
    ),
    (
        CommandName.ZOOM_OUT,
        ["zoom out", "alejar", "quitar zoom", "quita zoom", "reduce el zoom"],
    ),
]

_RELATIVE_SIZE_RULES: list[tuple[CommandName, list[str]]] = [
    (
        CommandName.INCREASE_SIZE,
        [
            r"\bsube(?:\s+el)?\s+tamano\b",
            r"\bsube\s+tamaño\b",
            r"\bsubele(?:\s+el)?\s+tamano\b",
            r"\baumenta\b",
            r"\bagranda\b",
            r"\baumenta(?:\s+el)?\s+tamano\b",
            r"\baumenta\s+tamaño\b",
            r"\bhazlo\s+(?:un\s+poco\s+)?mas\s+grande\b",
            r"\bagranda\s+(?:la\s+pantalla|el\s+monitor)\b",
            r"\bagranda\s+(?:la\s+pantalla|el\s+monitor)\s+(?:uno|dos|1|2)\b",
            r"\bquiero\s+verlo\s+mas\s+grande\b",
            r"\bpon(?:lo)?\s+mas\s+grande\b",
            r"\bincrease\b",
            r"\bmake\s+it\s+bigger\b",
            r"\bmake\s+(?:the\s+screen|monitor)\s+bigger\b",
            r"\bincrease\s+monitor\s+size\b",
        ],
    ),
    (
        CommandName.DECREASE_SIZE,
        [
            r"\bbaja(?:\s+el)?\s+tamano\b",
            r"\bbaja\s+tamaño\b",
            r"\bbajale(?:\s+el)?\s+tamano\b",
            r"\bdisminuye\b",
            r"\breduce\b",
            r"\breduce(?:\s+el)?\s+tamano\b",
            r"\breduce\s+tamaño\b",
            r"\bhazlo\s+(?:un\s+poco\s+)?mas\s+pequeno\b",
            r"\bachica\s+(?:la\s+pantalla|el\s+monitor)\b",
            r"\bachica\s+(?:la\s+pantalla|el\s+monitor)\s+(?:uno|dos|1|2)\b",
            r"\breduce\s+(?:la\s+pantalla|el\s+monitor)\b",
            r"\breduce\s+(?:la\s+pantalla|el\s+monitor)\s+(?:uno|dos|1|2)\b",
            r"\bquiero\s+verlo\s+mas\s+pequeno\b",
            r"\bpon(?:lo)?\s+mas\s+pequeno\b",
            r"\bdecrease\b",
            r"\bmake\s+it\s+smaller\b",
            r"\bmake\s+(?:the\s+screen|monitor)\s+smaller\b",
            r"\breduce\s+monitor\s+size\b",
        ],
    ),
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


def _find_pattern_fragment(text: str, patterns: list[str]) -> Optional[str]:
    """Return the matched text for the first regex pattern present in text."""

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
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
    if isinstance(size_inches, int) and size_inches > 0:
        _append_command(
            commands,
            seen,
            _entity_command(
                CommandName.SET_SIZE,
                str(size_inches),
                size_inches=size_inches,
            ),
        )
        suppressed.update({CommandName.INCREASE_SIZE, CommandName.DECREASE_SIZE})

    for command_name, aliases in _PRE_RELATIVE_RULES:
        if command_name in suppressed or command_name in seen:
            continue

        fragment = _find_fragment(normalized_text, aliases)
        if not fragment:
            continue

        _append_command(commands, seen, _exact_command(command_name, fragment))

    for command_name, patterns in _RELATIVE_SIZE_RULES:
        if command_name in suppressed or command_name in seen:
            continue

        fragment = _find_pattern_fragment(normalized_text, patterns)
        if not fragment:
            continue

        _append_command(commands, seen, _exact_command(command_name, fragment))

    for command_name, aliases in _EXACT_RULES:
        if command_name in suppressed or command_name in seen:
            continue

        fragment = _find_fragment(normalized_text, aliases)
        if not fragment:
            continue

        _append_command(commands, seen, _exact_command(command_name, fragment))
        suppressed.update(_SUPPRESSION_RULES.get(command_name, set()))

    return commands
