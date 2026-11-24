"""Generate SDK wire types from the pinned Pulse OpenAPI snapshots."""

from __future__ import annotations

import argparse
import keyword
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "pulse_agent_sdk"
PRIMITIVES = {"string": "str", "integer": "int", "boolean": "bool", "number": "float", "null": "None"}
SESSION_NAMES = {"AuthSignalMetadata": "AuthSignal", "AgentSessionUpdate": "SessionUpdate"}


class Generator:
    def __init__(self, schemas: dict[str, Any], aliases: dict[str, str]) -> None:
        self.schemas = schemas
        self.aliases = aliases
        self.models: dict[str, str] = {}
        self.active: set[str] = set()

    def parts(self, schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Resolve OpenAPI allOf wrappers and the 3.0/3.1 null spellings."""
        nullable = schema.get("nullable", False)
        kind = schema.get("type")
        if isinstance(kind, list):
            nonnull = [entry for entry in kind if entry != "null"]
            if len(nonnull) != 1:
                raise ValueError(f"Unsupported type list: {kind!r}")
            schema = {**schema, "type": nonnull[0]}
            nullable = nullable or "null" in kind
        if "allOf" not in schema:
            return schema, nullable
        parts = [self.parts(part) for part in schema["allOf"]]
        nullable = nullable or any(is_nullable for _, is_nullable in parts)
        shapes = [part for part, _ in parts if {"type", "$ref", "properties"} & part.keys()]
        if len(shapes) == 1:
            return shapes[0], nullable
        properties: dict[str, Any] = {}
        required: set[str] = set()
        for shape in shapes:
            if "$ref" in shape:
                shape, _ = self.parts(self.schemas[shape["$ref"].rsplit("/", 1)[-1]])
            if "properties" not in shape:
                raise ValueError("Unsupported allOf intersection")
            for key, value in shape["properties"].items():
                if key in properties and properties[key] != value:
                    raise ValueError(f"Conflicting allOf property: {key}")
                properties[key] = value
            required.update(shape.get("required", []))
        if not shapes:
            raise ValueError("Untyped allOf")
        return {"type": "object", "properties": properties, "required": sorted(required)}, nullable

    def annotation(self, schema: dict[str, Any], name: str) -> str:
        schema, nullable = self.parts(schema)
        if "$ref" in schema:
            value = self.named(schema["$ref"].rsplit("/", 1)[-1])
        elif "enum" in schema or "const" in schema:
            options = schema.get("enum", [schema.get("const")])
            literals = ", ".join(repr(option) for option in options if option is not None)
            value = f"Literal[{literals}]" if literals else "None"
            nullable = (nullable or None in options) and bool(literals)
        elif "oneOf" in schema or "anyOf" in schema:
            variants = schema.get("oneOf", schema.get("anyOf", []))
            if "properties" in schema and all(set(part) == {"required"} for part in variants):
                variants = [
                    {"type": "object", "required": part["required"], "properties": {
                        key: schema["properties"][key] for key in part["required"]
                    }}
                    for part in variants
                ]
            value = " | ".join(dict.fromkeys(
                self.annotation(part, f"{name}Variant{index}") for index, part in enumerate(variants, 1)
            ))
        elif "properties" in schema:
            value = f"{name}Fields" if nullable and name in self.active else name
            self.model(value, schema)
        elif schema.get("type") == "object":
            extra = schema.get("additionalProperties")
            value = f"dict[str, {self.annotation(extra, f'{name}Value')}]" if isinstance(extra, dict) else "dict[str, object]"
        elif schema.get("type") == "array":
            value = f"list[{self.annotation(schema['items'], f'{name}Item')}]"
        elif schema.get("type") in PRIMITIVES:
            value = PRIMITIVES[schema["type"]]
        elif schema.keys() <= {"description", "example", "default", "title", "nullable", "x-go-type"}:
            value = "object"
        else:
            raise ValueError(f"Unsupported schema for {name}: {schema.keys()}")
        if nullable and value not in {"None", "object"}:
            value += " | None"
        return value

    def model(self, name: str, schema: dict[str, Any]) -> None:
        fields = {}
        required = set(schema.get("required", []))
        for key, definition in schema["properties"].items():
            suffix = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^\w]+|_", key))
            derived = "SelectOption" if name == "SelectSignalMetadata" and key == "options" else f"{name}{suffix}"
            if derived == "SelectOption":
                self.model(derived, definition["items"])
                annotation = "list[SelectOption]"
            else:
                annotation = self.annotation(definition, derived)
            if self.active.intersection(re.findall(r"\b\w+\b", annotation)):
                annotation = repr(annotation)
            fields[key] = annotation if key in required else f"NotRequired[{annotation}]"
        if all(key.isidentifier() and not keyword.iskeyword(key) for key in fields):
            lines = [f"class {name}(TypedDict):"]
            lines.extend(f"    {key}: {annotation}" for key, annotation in fields.items())
            if not fields:
                lines.append("    pass")
        else:
            lines = [f'{name} = TypedDict("{name}", {{']
            lines.extend(f"    {key!r}: {annotation}," for key, annotation in fields.items())
            lines.append("})")
        rendered = "\n".join(lines)
        if name in self.models and rendered != self.models[name]:
            raise ValueError(f"Conflicting generated model name: {name}")
        self.models[name] = rendered

    def named(self, source: str) -> str:
        name = self.aliases.get(source, source)
        if name in self.models:
            return name
        if name in self.active:
            return name
        self.active.add(name)
        annotation = self.annotation(self.schemas[source], name)
        if annotation != name:
            self.models[name] = f"{name}: TypeAlias = {annotation}"
        self.active.remove(name)
        return name

    def render(self, filename: str, roots: list[str]) -> str:
        for root in roots:
            self.named(root)
        first = next(iter(self.models.values()))
        spacing = "\n\n\n" if first.startswith("class ") else "\n\n"
        return (
            f'"""Generated from specs/{filename} by scripts/generate_types.py."""\n\n'
            "from typing import Literal, NotRequired, TypeAlias, TypedDict" + spacing
            + "\n\n\n".join(self.models.values()) + "\n"
        )


def generate(filename: str) -> str:
    document = yaml.safe_load((ROOT / "specs" / filename).read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]
    if filename == "agent-sessions.yaml":
        return Generator(schemas, SESSION_NAMES).render(filename, list(schemas))
    token = document["paths"]["/oauth/token"]["post"]["responses"]["200"]
    schemas["OAuthTokenResponse"] = token["content"]["application/json"]["schema"]
    roots = ["AgentAppScope", "AppWebhookEnvelope", "Error", "Issue", "MeResponse", "OAuthError", "OAuthTokenResponse"]
    return Generator(schemas, {"Error": "ApiErrorBody", "OAuthError": "OAuthErrorBody"}).render(filename, roots)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    specs = {"agent-sessions.yaml": "_generated.py", "pulse-api.agent-sdk.yaml": "_generated_api.py"}
    for filename, target in specs.items():
        output = generate(filename)
        path = PACKAGE / target
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != output:
                raise SystemExit(f"{target} differs from OpenAPI. Run python scripts/generate_types.py.")
        else:
            path.write_text(output, encoding="utf-8")
    print("Python wire types match the pinned OpenAPI.")


if __name__ == "__main__":
    main()
