# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 TheHolyOneZ
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ValidationResult", "validate_against"]


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def total_issues(self) -> int:
        return len(self.errors) + len(self.warnings)

    def extend(self, other: ValidationResult) -> None:
        self.errors += other.errors
        self.warnings += other.warnings
        self.info += other.info


def _type_name(t: Any) -> str:
    if isinstance(t, tuple):
        return "/".join(x.__name__ for x in t)
    return getattr(t, "__name__", str(t))


def validate_against(data: dict[str, Any], schema: dict[str, Any], path: str = "",
                     *, warn_unknown: bool = True) -> ValidationResult:
    result = ValidationResult()
    for key, spec in schema.items():
        full = f"{path}.{key}" if path else key
        if key not in data:
            if spec.get("required"):
                result.errors.append(f"missing required key `{full}`")
            elif "default" in spec:
                result.info.append(f"`{full}` not set - default `{spec['default']!r}` applies")
            continue
        value = data[key]
        expected = spec.get("type")
        if expected is not None:
            ok = isinstance(value, expected)
            if ok and isinstance(value, bool) and expected in (int, float):
                ok = False
            if not ok:
                result.errors.append(f"`{full}`: expected {_type_name(expected)}, got {type(value).__name__}")
                continue
        if (choices := spec.get("choices")) and value not in choices:
            result.warnings.append(f"`{full}`: `{value}` is not one of {choices}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if (lo := spec.get("min")) is not None and value < lo:
                result.warnings.append(f"`{full}`: {value} is below the minimum {lo}")
            if (hi := spec.get("max")) is not None and value > hi:
                result.warnings.append(f"`{full}`: {value} is above the maximum {hi}")
        if isinstance(value, str) and (ml := spec.get("max_length")) is not None and len(value) > ml:
            result.warnings.append(f"`{full}`: length {len(value)} exceeds {ml}")
        if (children := spec.get("children")) and isinstance(value, dict):
            result.extend(validate_against(value, children, full, warn_unknown=warn_unknown))
    if warn_unknown:
        for key in data:
            if key not in schema and not key.startswith("_comment"):
                full = f"{path}.{key}" if path else key
                result.warnings.append(f"unknown key `{full}`")
    return result
