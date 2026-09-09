# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Audit generated documentation with the official llms.txt parser."""

from __future__ import annotations

import argparse
import posixpath
import tempfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import docutils.nodes
from llms_txt import parse_llms_file
from sphinx.application import Sphinx

from sphinx_llm.txt import MarkdownGenerator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "docs" / "source"
AUDIT_DESCRIPTION = "Representative documentation for the llms.txt v2 audit."
ABSOLUTE_BASE_URL = "https://docs.example.test/sphinx-llm/"
EXCLUDED_DOCNAMES = {"nested/orphan"}


class _DiscoveryParser(HTMLParser):
    """Collect link elements from an HTML document's head."""

    def __init__(self) -> None:
        super().__init__()
        self.in_head = False
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self.in_head = True
        elif tag == "link" and self.in_head:
            self.links.append(
                {name: value for name, value in attrs if value is not None}
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False


def resolve_local_target(
    url: str,
    *,
    source: PurePosixPath,
    build_root: Path,
    absolute_base_url: str = "",
) -> Path:
    """Map a generated URL to a regular file contained by ``build_root``.

    The interoperability audit never dereferences a URL over the network. Absolute
    HTTP(S) URLs are accepted only when they use the configured fixture base and
    are mapped back into the ephemeral build directory.
    """
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise AssertionError(f"Generated URL must not have query/fragment: {url!r}")

    decoded_path = unquote(parts.path)
    if "\\" in decoded_path or "\0" in decoded_path:
        raise AssertionError(f"Unsafe generated URL path: {url!r}")

    if parts.scheme or parts.netloc:
        if not absolute_base_url:
            raise AssertionError(f"Unexpected absolute generated URL: {url!r}")
        base = urlsplit(absolute_base_url)
        if parts.scheme not in {"http", "https"} or (
            parts.scheme,
            parts.netloc,
        ) != (base.scheme, base.netloc):
            raise AssertionError(
                f"Generated URL is outside the configured base: {url!r}"
            )
        try:
            relative = PurePosixPath(decoded_path).relative_to(
                PurePosixPath(unquote(base.path))
            )
        except ValueError as exc:
            raise AssertionError(
                f"Generated URL is outside the configured base: {url!r}"
            ) from exc
    else:
        relative_url = PurePosixPath(decoded_path)
        if relative_url.is_absolute():
            raise AssertionError(f"Absolute filesystem-style URL is forbidden: {url!r}")
        relative = PurePosixPath(
            posixpath.normpath((source.parent / relative_url).as_posix())
        )

    root = build_root.resolve()
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AssertionError(f"Generated URL escapes the build root: {url!r}") from exc
    if not candidate.is_file():
        raise AssertionError(f"Generated URL has no local artifact: {url!r}")
    return candidate


def _canonical_markdown_path(
    html_path: PurePosixPath, suffix_mode: str
) -> PurePosixPath:
    if suffix_mode == "append":
        return PurePosixPath(f"{html_path}.md")
    return html_path.with_suffix(".md")


def _html_path(app: Sphinx, build_root: Path, docname: str) -> PurePosixPath:
    """Return a document's HTML artifact path relative to the build root."""
    return PurePosixPath(
        Path(app.builder.get_outfilename(docname))
        .resolve()
        .relative_to(build_root.resolve())
        .as_posix()
    )


def _scope_contains(scope: PurePosixPath, page_directory: PurePosixPath) -> bool:
    """Return whether an index scope covers a published page directory."""
    return (
        scope == PurePosixPath(".")
        or page_directory == scope
        or scope in page_directory.parents
    )


def _expected_markdown_paths(
    app: Sphinx, build_root: Path, suffix_mode: str
) -> set[PurePosixPath]:
    paths = set()
    for docname in app.env.found_docs:
        html_path = _html_path(app, build_root, docname)
        paths.add(_canonical_markdown_path(html_path, suffix_mode))
        if suffix_mode == "append" and app.builder.name == "dirhtml":
            if docname == app.config.root_doc:
                continue
            # Append also emits the no-trailing-slash dirhtml companion:
            # ``page.md``, or the directory name for an ``index`` document.
            doc_path = PurePosixPath(docname)
            paths.add(
                doc_path.parent.with_suffix(".md")
                if doc_path.name == "index"
                else doc_path.with_suffix(".md")
            )
    return paths


def _expected_index_paths(app: Sphinx, build_root: Path) -> set[PurePosixPath]:
    indexes = {PurePosixPath("llms.txt")}
    for docname in app.env.found_docs - EXCLUDED_DOCNAMES:
        html_path = _html_path(app, build_root, docname)
        for directory in (html_path.parent, *html_path.parent.parents):
            if directory == PurePosixPath("."):
                break
            indexes.add(directory / "llms.txt")
    return indexes


def _ordered_docnames(app: Sphinx) -> list[str]:
    order = {
        docname: index for index, docname in enumerate(app.env.collect_relations())
    }
    return sorted(
        app.env.found_docs - EXCLUDED_DOCNAMES,
        key=lambda docname: (order.get(docname, len(order)), docname),
    )


def _description(app: Sphinx, docname: str, markdown_path: Path) -> str:
    doctree = app.env.get_doctree(docname)
    for node in doctree.findall(docutils.nodes.meta):
        content = node.get("content")
        if (
            node.get("name") == "description"
            and isinstance(content, str)
            and content.strip()
        ):
            return content.strip()
    return MarkdownGenerator.extract_description_from_markdown(markdown_path)


def _validate_v2_structure(text: str) -> None:
    """Independently enforce the proposal's generated document structure."""
    lines = text.removeprefix("\ufeff").splitlines()
    assert lines and lines[0].startswith("# ") and not lines[0].startswith("## ")
    assert sum(line.startswith("# ") for line in lines) == 1

    in_file_list = False
    for line in lines[1:]:
        if line.startswith("## "):
            in_file_list = True
        elif line.startswith("#"):
            raise AssertionError(f"Unexpected heading in llms.txt: {line!r}")
        elif in_file_list and line.strip():
            assert line.startswith("- ["), (
                f"File-list content is not a Markdown link item: {line!r}"
            )


def _expected_page_entries(
    app: Sphinx,
    build_root: Path,
    index_path: PurePosixPath,
    suffix_mode: str,
    absolute_base_url: str,
) -> list[dict[str, str]]:
    scope = index_path.parent
    entries = []
    for docname in _ordered_docnames(app):
        html_path = _html_path(app, build_root, docname)
        page_directory = html_path.parent
        if not _scope_contains(scope, page_directory):
            continue
        markdown_path = _canonical_markdown_path(html_path, suffix_mode)
        url = (
            f"{absolute_base_url.rstrip('/')}/{markdown_path.as_posix()}"
            if absolute_base_url
            else posixpath.relpath(markdown_path.as_posix(), start=scope.as_posix())
        )
        local_markdown = build_root.joinpath(*markdown_path.parts)
        entries.append(
            {
                "title": app.env.titles[docname].astext(),
                "url": url,
                "desc": _description(app, docname, local_markdown),
            }
        )
    return entries


def _audit_index(
    app: Sphinx,
    build_root: Path,
    index_path: PurePosixPath,
    suffix_mode: str,
    absolute_base_url: str,
) -> None:
    local_index = build_root.joinpath(*index_path.parts)
    source = local_index.read_text(encoding="utf-8")
    _validate_v2_structure(source)
    parsed = parse_llms_file(source)
    assert parsed.title == app.config.project
    assert parsed.summary == AUDIT_DESCRIPTION
    assert parsed.info == app.config.copyright

    pages_heading = (
        "Pages"
        if index_path == PurePosixPath("llms.txt")
        else "Pages in this subsection"
    )
    expected_pages = _expected_page_entries(
        app, build_root, index_path, suffix_mode, absolute_base_url
    )
    expected_sections = [pages_heading]
    if index_path != PurePosixPath("llms.txt"):
        expected_sections.append("Optional")
    assert list(parsed.sections) == expected_sections
    parsed_pages = [dict(entry) for entry in parsed.sections[pages_heading]]
    assert parsed_pages == expected_pages
    if absolute_base_url:
        assert all(
            not entry["url"].startswith(f"{absolute_base_url}/")
            for entry in parsed_pages
        )

    for entry in parsed_pages:
        artifact = resolve_local_target(
            entry["url"],
            source=index_path,
            build_root=build_root,
            absolute_base_url=absolute_base_url,
        )
        assert artifact.stat().st_size > 0

    if index_path != PurePosixPath("llms.txt"):
        root_url = (
            f"{absolute_base_url.rstrip('/')}/llms.txt"
            if absolute_base_url
            else posixpath.relpath("llms.txt", start=index_path.parent.as_posix())
        )
        assert [dict(entry) for entry in parsed.sections["Optional"]] == [
            {
                "title": "Top-level llms.txt",
                "url": root_url,
                "desc": "Complete documentation index.",
            }
        ]
        assert (
            resolve_local_target(
                root_url,
                source=index_path,
                build_root=build_root,
                absolute_base_url=absolute_base_url,
            )
            == (build_root / "llms.txt").resolve()
        )


def _audit_indexes(
    app: Sphinx,
    build_root: Path,
    suffix_mode: str,
    absolute_base_url: str,
    case: str,
) -> int:
    expected_paths = _expected_index_paths(app, build_root)
    actual_paths = {
        PurePosixPath(path.relative_to(build_root).as_posix())
        for path in build_root.rglob("llms.txt")
    }
    assert actual_paths, f"{case}: no llms.txt files were generated"
    assert actual_paths == expected_paths, f"{case}: unexpected index path set"

    for index_path in sorted(actual_paths):
        try:
            _audit_index(app, build_root, index_path, suffix_mode, absolute_base_url)
        except Exception as exc:
            raise AssertionError(f"{case}: audit failed for {index_path}") from exc
    return len(actual_paths)


def _discovery_links(path: Path) -> list[dict[str, str]]:
    parser = _DiscoveryParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.links


def _audit_discovery(
    app: Sphinx,
    build_root: Path,
    suffix_mode: str,
    index_paths: set[PurePosixPath],
) -> None:
    for docname in app.env.found_docs:
        html_file = Path(app.builder.get_outfilename(docname)).resolve()
        html_path = _html_path(app, build_root, docname)
        markdown_path = _canonical_markdown_path(html_path, suffix_mode)
        page_directory = html_path.parent
        covering_index = max(
            (
                path
                for path in index_paths
                if _scope_contains(path.parent, page_directory)
            ),
            key=lambda path: len(path.parts),
        )
        alternate_href = posixpath.relpath(
            markdown_path.as_posix(), start=page_directory.as_posix()
        )
        describedby_href = posixpath.relpath(
            covering_index.as_posix(), start=page_directory.as_posix()
        )
        links = _discovery_links(html_file)
        assert [
            link
            for link in links
            if link.get("rel") == "alternate" and link.get("type") == "text/markdown"
        ] == [
            {
                "rel": "alternate",
                "type": "text/markdown",
                "href": alternate_href,
            }
        ]
        assert [link for link in links if link.get("rel") == "describedby"] == [
            {"rel": "describedby", "href": describedby_href}
        ]
        for href in (alternate_href, describedby_href):
            resolve_local_target(
                href,
                source=html_path,
                build_root=build_root,
            )

    for auxiliary_name in ("genindex", "search"):
        auxiliary_path = (
            build_root / f"{auxiliary_name}.html"
            if app.builder.name == "html"
            else build_root / auxiliary_name / "index.html"
        )
        assert auxiliary_path.is_file()
        assert not [
            link
            for link in _discovery_links(auxiliary_path)
            if link.get("rel") in {"alternate", "describedby"}
        ]


def audit(builder: str, suffix_mode: str, base_mode: str) -> None:
    """Build one matrix case and audit all v2 indexes, artifacts, and discovery."""
    absolute_base_url = ABSOLUTE_BASE_URL if base_mode == "absolute" else ""
    with tempfile.TemporaryDirectory(prefix="sphinx-llm-v2-") as temp_dir:
        temp_root = Path(temp_dir)
        build_root = temp_root / "build"
        app = Sphinx(
            srcdir=str(SOURCE_ROOT),
            confdir=str(SOURCE_ROOT),
            outdir=str(build_root),
            doctreedir=str(temp_root / "doctrees"),
            buildername=builder,
            confoverrides={
                "llms_txt_build_parallel": False,
                "llms_txt_description": AUDIT_DESCRIPTION,
                "llms_txt_exclude": sorted(EXCLUDED_DOCNAMES),
                "llms_txt_full_build": False,
                "llms_txt_nested_enabled": True,
                "llms_txt_suffix_mode": suffix_mode,
                "markdown_http_base": absolute_base_url,
            },
            warningiserror=True,
            freshenv=True,
            status=None,
        )
        app.build()

        expected_markdown = _expected_markdown_paths(app, build_root, suffix_mode)
        actual_markdown = {
            PurePosixPath(path.relative_to(build_root).as_posix())
            for path in build_root.rglob("*.md")
        }
        assert actual_markdown == expected_markdown
        assert all(
            build_root.joinpath(*path.parts).stat().st_size > 0
            for path in actual_markdown
        )
        assert not (build_root / "llms-full.txt").exists()

        index_paths = _expected_index_paths(app, build_root)
        case = f"builder={builder} suffix={suffix_mode} base={base_mode}"
        index_count = _audit_indexes(
            app, build_root, suffix_mode, absolute_base_url, case
        )
        _audit_discovery(app, build_root, suffix_mode, index_paths)
        print(
            f"validated {case} "
            f"indexes={index_count} pages={len(app.env.found_docs)} "
            f"artifacts={len(actual_markdown)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--builder", choices=("html", "dirhtml"), required=True)
    parser.add_argument("--suffix-mode", choices=("append", "replace"), required=True)
    parser.add_argument("--base-mode", choices=("relative", "absolute"), required=True)
    args = parser.parse_args()
    audit(args.builder, args.suffix_mode, args.base_mode)


if __name__ == "__main__":
    main()
