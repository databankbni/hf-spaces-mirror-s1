from __future__ import annotations

from typing import Any, Callable, Dict, Tuple, Union, get_args, get_origin, get_type_hints
import inspect

from .packet import InfoPacket


def extract_param_value(packet: InfoPacket, param_type: Any) -> Any:
    content = packet.content
    origin = get_origin(param_type)

    if origin is Union:
        for arg in get_args(param_type):
            if arg is type(None):
                continue
            result = extract_param_value(packet, arg)
            if result is not packet:
                return result
        return packet

    if param_type is InfoPacket or (origin is not None and InfoPacket in get_args(param_type)):
        return packet
    if param_type in (str, "str") and isinstance(content, str):
        return content
    if param_type in (dict, "dict") and isinstance(content, dict):
        return content
    if param_type in (bytes, "bytes") and isinstance(content, bytes):
        return content
    if param_type in (int, "int") and isinstance(content, int):
        return content
    if param_type in (float, "float") and isinstance(content, (int, float)):
        return content
    if param_type in (bool, "bool") and isinstance(content, bool):
        return content
    if param_type in (list, "list") and isinstance(content, list):
        return content

    try:
        if isinstance(content, param_type):
            return content
    except TypeError:
        pass
    return packet


def create_arg_extractor(func: Callable) -> Callable[[InfoPacket], Tuple[Any, ...]]:
    try:
        signature = inspect.signature(func)
        param_types: dict[str, Any] = {}
        for name, param in signature.parameters.items():
            if param.annotation != inspect.Parameter.empty:
                param_types[name] = param.annotation
            else:
                param_types[name] = type(param.default) if param.default != inspect.Parameter.empty else Any

        if not param_types:
            return lambda _packet: ()

        def extractor(packet: InfoPacket) -> tuple[Any, ...]:
            return tuple(extract_param_value(packet, param_type) for param_type in param_types.values())

        return extractor
    except (ValueError, TypeError):
        return lambda packet: (packet,)


def extract_call_arguments(packet: InfoPacket) -> Dict[str, Any]:
    content = packet.content
    if not isinstance(content, dict):
        return {}
    arguments = content.get("arguments")
    return arguments if isinstance(arguments, dict) else {}


def coerce_call_argument(value: Any, param_type: Any) -> Any:
    origin = get_origin(param_type)

    if param_type is Any or param_type == Any or param_type is inspect.Parameter.empty:
        return value
    if origin is Union:
        for arg in get_args(param_type):
            if arg is type(None):
                continue
            coerced = coerce_call_argument(value, arg)
            if coerced is not value or isinstance(value, arg if isinstance(arg, type) else object):
                return coerced
        return value
    if param_type is InfoPacket:
        return value
    if param_type in (str, "str"):
        return value if isinstance(value, str) else str(value)
    if param_type in (int, "int"):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip():
            return int(float(value.strip()))
        return value
    if param_type in (float, "float"):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str) and value.strip():
            return float(value.strip())
        return value
    if param_type in (bool, "bool"):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off"}:
                return False
        return value
    if param_type in (list, "list"):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            if "," in stripped:
                return [item.strip() for item in stripped.split(",") if item.strip()]
        return value
    if param_type in (dict, "dict"):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{"):
                import json

                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
        return value
    return value


def generate_schema_from_docstring(func: Callable, name: str) -> dict[str, Any] | None:
    docstring = inspect.getdoc(func)
    if not docstring:
        return None

    descriptions: dict[str, str] = {}
    in_args_section = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("Args:", "Arguments:")):
            in_args_section = True
            continue
        if in_args_section:
            if stripped.startswith(("Returns:", "Return")):
                break
            if stripped.startswith(("- ", "* ")):
                parts = stripped[2:].split(":", 1)
                if len(parts) == 2:
                    descriptions[parts[0].strip()] = parts[1].strip()
            elif stripped and ":" in stripped and not stripped[0].isspace():
                parts = stripped.split(":", 1)
                descriptions[parts[0].strip()] = parts[1].strip()

    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {
            param_name: param.annotation
            for param_name, param in inspect.signature(func).parameters.items()
            if param.annotation != inspect.Parameter.empty
        }

    py_type_to_json = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
        bytes: "string",
    }
    signature = inspect.signature(func)
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for param_name, param_type in hints.items():
        if param_name == "return" or param_type is InfoPacket:
            continue
        origin = get_origin(param_type)
        if origin is Union:
            json_type = next((py_type_to_json.get(arg, "string") for arg in get_args(param_type) if arg is not type(None)), "string")
        else:
            json_type = py_type_to_json.get(param_type, "string")
        properties[param_name] = {
            "type": json_type,
            "description": descriptions.get(param_name, f"The {param_name} parameter"),
        }
        if signature.parameters[param_name].default == inspect.Parameter.empty:
            required.append(param_name)

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": docstring.split("\n")[0].strip(),
            "parameters": parameters,
        },
    }
