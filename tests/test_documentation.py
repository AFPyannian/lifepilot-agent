"""验证配置说明和本地 Markdown 链接不会随代码演进失效。"""

import re
from pathlib import Path

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]

NON_SETTINGS_ENVIRONMENT_KEYS = {
    "LIFEPILOT_API_URL",
    "MINIO_ROOT_PASSWORD",
    "MINIO_ROOT_USER",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
}


def test_environment_example_and_configuration_cover_settings() -> None:
    example_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    example_keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example_text, re.MULTILINE))
    settings_keys = {name.upper() for name in Settings.model_fields}

    assert settings_keys <= example_keys
    assert example_keys <= settings_keys | NON_SETTINGS_ENVIRONMENT_KEYS

    configuration_text = (PROJECT_ROOT / "docs" / "configuration.md").read_text(
        encoding="utf-8"
    )
    documented_keys = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", configuration_text))
    assert example_keys <= documented_keys


def test_local_markdown_links_exist() -> None:
    markdown_paths = [PROJECT_ROOT / "README.md"]
    markdown_paths.extend(sorted((PROJECT_ROOT / "docs").glob("*.md")))
    missing_links: list[str] = []

    for markdown_path in markdown_paths:
        content = markdown_path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue

            relative_target = target.split("#", 1)[0]
            resolved_target = (markdown_path.parent / relative_target).resolve()
            if not resolved_target.exists():
                missing_links.append(f"{markdown_path.name}: {target}")

    assert missing_links == []
