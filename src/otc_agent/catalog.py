from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from .domain import ServiceMapping


class CatalogError(ValueError):
    pass


_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Catalog:
    mappings: tuple[ServiceMapping, ...]
    eligible_docs_repositories: frozenset[str]

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        raw = json.loads(path.read_text(encoding="utf-8"))
        mappings = tuple(
            ServiceMapping(
                sdk=item["sdk"],
                provider=item["provider"],
                docs=item["docs"],
                display_name=item["display_name"],
                key=item.get("key", item["sdk"]),
                api_ref_path=item.get("api_ref_path", "api-ref"),
                aliases=tuple(item.get("aliases", [])),
                reference=bool(item.get("reference", False)),
                bootstrap=False,
            )
            for item in raw["mappings"]
        )
        catalog = cls(mappings, frozenset(raw["eligible_docs_repositories"]))
        catalog.validate()
        return catalog

    def validate(self) -> None:
        keys: dict[str, str] = {}
        for item in self.mappings:
            for value in (item.key, item.sdk, *item.aliases):
                normalized = normalize(value)
                if normalized in keys and keys[normalized] != item.key:
                    raise CatalogError(f"ambiguous routing key or alias {value!r}: {keys[normalized]} and {item.key}")
                keys[normalized] = item.key
            if item.docs not in self.eligible_docs_repositories:
                raise CatalogError(f"{item.docs!r} is not verified to contain api-ref")
            if not all(_SAFE_NAME.fullmatch(value) for value in (item.key, item.sdk, item.provider, item.docs)):
                raise CatalogError(f"unsafe catalog name in {item.sdk!r}")

    def resolve(self, value: str, override: str | None = None) -> ServiceMapping:
        normalized = normalize(value)
        matches = [item for item in self.mappings if normalized in {normalize(item.key), normalize(item.sdk)}]
        if not matches:
            matches = [item for item in self.mappings if normalized in {normalize(a) for a in item.aliases}]
        if not matches:
            matches = [item for item in self.mappings if normalized in {normalize(item.provider), normalize(item.docs)}]
        if len(matches) != 1:
            suggestions = get_close_matches(normalized, [item.key for item in self.mappings], n=3, cutoff=0.55)
            suffix = f"; suggestions: {', '.join(suggestions)}" if suggestions else ""
            raise CatalogError(f"service {value!r} has no unambiguous reviewed mapping{suffix}")
        selected = matches[0]
        if override is not None:
            if override not in self.eligible_docs_repositories:
                raise CatalogError(f"documentation override {override!r} is not an api-ref repository")
            if override != selected.docs:
                raise CatalogError("documentation override conflicts with the reviewed service mapping")
        return selected

    def resolve_documentation(self, repository: str) -> ServiceMapping:
        normalized = normalize(repository)
        if normalized != repository or not _SAFE_NAME.fullmatch(repository):
            raise CatalogError("documentation repository must be an exact lower-case GitHub repository slug")
        if repository not in self.eligible_docs_repositories:
            raise CatalogError(f"documentation repository {repository!r} is not verified to contain api-ref")
        matches = [item for item in self.mappings if item.docs == repository]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            keys = ", ".join(sorted(item.key for item in matches))
            raise CatalogError(f"documentation repository {repository!r} has multiple service variants; specify one of: {keys}")
        return ServiceMapping(
            key=repository,
            sdk=None,
            provider=None,
            docs=repository,
            display_name=repository.replace("-", " ").title(),
            bootstrap=True,
        )


def normalize(value: str) -> str:
    value = value.strip().lower().replace("_", "-").replace(" ", "-")
    return re.sub(r"-+", "-", value)


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "services.json"
