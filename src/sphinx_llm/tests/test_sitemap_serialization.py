# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Focused regressions for generated llms.txt file-list serialization."""

from __future__ import annotations

import html
import posixpath
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit

import pytest

from sphinx_llm.txt import MarkdownGenerator


def _reference_parser_fields(entry: str) -> dict[str, str]:
    """Parse one entry using the field boundaries from llms-txt 0.0.6."""
    match = re.fullmatch(
        r"-\s*\[(?P<title>[^\]]+)\]\((?P<url>[^\)]+)\)"
        r"(?::\s*(?P<desc>.*))?",
        entry,
    )
    assert match is not None
    return match.groupdict()


def _generator(tmp_path: Path, http_base: str = "") -> MarkdownGenerator:
    config = SimpleNamespace(
        _raw_config={"markdown_http_base": http_base},
        copyright="",
        llms_txt_exclude=[],
        markdown_http_base=http_base,
        project="Serialization test",
    )
    app = SimpleNamespace(config=config, builder=SimpleNamespace(name="html"))
    generator = MarkdownGenerator(app)
    generator.outdir = tmp_path
    generator.suffix_mode = "auto"
    return generator


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested"])
@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_generated_entries_round_trip_markdown_edges(
    tmp_path: Path, builder: str, nested: bool, absolute: bool
) -> None:
    """Generated fields stay parseable, readable, and artifact-resolving."""
    http_base = "https://example.test/docs%20base" if absolute else ""
    generator = _generator(tmp_path, http_base)
    generator.app.builder.name = builder

    scope = Path("nested area") if nested else Path()
    page_name = "API [β](v2): 100% \\ draft? #1"
    artifact = scope / page_name
    artifact = (
        artifact.with_suffix(".html.md")
        if builder == "html"
        else artifact / "index.html.md"
    )
    artifact = tmp_path / artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# generated artifact\n", encoding="utf-8")

    title = "API [β]\n(v2): `path` &copy; <tag> *star* _under_ \\"
    normalized_title = "API [β] (v2): `path` &copy; <tag> *star* _under_ \\"
    description = (
        "Read [the guide](other.md): café\\\r\n"
        "then `code` &copy; <tag> *stars* _under_."
    )
    normalized_description = (
        "Read [the guide](other.md): café\\ then `code` &copy; <tag> *stars* _under_."
    )
    generator._docname_by_output_file[artifact] = "edge"
    generator.extract_title_from_markdown = lambda _: title
    generator.get_page_description = lambda _: description

    index = tmp_path / scope / "llms.txt"
    generator._write_sitemap(index, [artifact], subsection=nested)

    content = index.read_text(encoding="utf-8")
    page_lines = [line for line in content.splitlines() if line.startswith("- [API")]
    assert len(page_lines) == 1
    assert "_under_" not in page_lines[0]
    assert page_lines[0].count("&#95;under&#95;") == 2
    fields = _reference_parser_fields(page_lines[0])

    assert html.unescape(fields["title"]) == normalized_title
    assert html.unescape(fields["desc"]) == normalized_description
    assert "\n" not in fields["title"]
    assert "\n" not in fields["desc"]

    if absolute:
        expected_url = (
            f"{http_base}/{quote(artifact.relative_to(tmp_path).as_posix(), safe='/')}"
        )
        parsed_path = urlsplit(fields["url"]).path
        base_path = urlsplit(http_base).path.rstrip("/") + "/"
        assert parsed_path.startswith(base_path)
        resolved = tmp_path / unquote(parsed_path.removeprefix(base_path))
    else:
        relative_target = posixpath.relpath(
            artifact.relative_to(tmp_path).as_posix(),
            start=index.parent.relative_to(tmp_path).as_posix() or ".",
        )
        expected_url = quote(relative_target, safe="/")
        resolved = (index.parent / unquote(fields["url"])).resolve()

    assert fields["url"] == expected_url
    assert "%2520base" not in fields["url"]
    assert resolved == artifact.resolve()
    assert resolved.is_file()


def test_generated_ordinary_entry_keeps_existing_output(tmp_path: Path) -> None:
    """Plain generated content does not change byte source representation."""
    generator = _generator(tmp_path)
    artifact = tmp_path / "guide" / "page.html.md"
    artifact.parent.mkdir()
    artifact.write_text("# Plain Title\n", encoding="utf-8")
    generator._docname_by_output_file[artifact] = "guide/page"
    generator.extract_title_from_markdown = lambda _: "Plain Title"
    generator.get_page_description = lambda _: "Plain description."

    index = tmp_path / "llms.txt"
    generator._write_sitemap(index, [artifact])

    assert (
        "- [Plain Title](guide/page.html.md): Plain description.\n"
        in index.read_text(encoding="utf-8")
    )


def test_custom_override_content_is_not_serialized(tmp_path: Path) -> None:
    """Arbitrary authored Markdown remains byte-for-byte user-owned."""
    generator = _generator(tmp_path)
    generator.app.config.llms_txt_override_source = "index"
    source = tmp_path / "custom.md"
    authored = (
        "# User [owned] &copy;\n\n"
        "- [Raw \\] label](a b(1).md): line with *markup*\\\n"
        "  continuation\n"
    )
    source.write_text(authored, encoding="utf-8")
    generator._markdown_file_by_docname = {"index": source}

    generator.build_custom_llms_txt()

    assert (tmp_path / "llms.txt").read_text(encoding="utf-8") == authored
