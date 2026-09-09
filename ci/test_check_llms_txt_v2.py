# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Security regressions for the llms.txt v2 interoperability audit."""

from pathlib import Path, PurePosixPath

import pytest

from ci.check_llms_txt_v2 import ABSOLUTE_BASE_URL, resolve_local_target


def test_resolve_local_target_accepts_in_root_relative_and_absolute_urls(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "guide" / "page.html.md"
    artifact.parent.mkdir()
    artifact.write_text("# Page\n", encoding="utf-8")

    assert (
        resolve_local_target(
            "page.html.md",
            source=PurePosixPath("guide/llms.txt"),
            build_root=tmp_path,
        )
        == artifact
    )
    assert (
        resolve_local_target(
            f"{ABSOLUTE_BASE_URL}guide/page.html.md",
            source=PurePosixPath("llms.txt"),
            build_root=tmp_path,
            absolute_base_url=ABSOLUTE_BASE_URL,
        )
        == artifact
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "/etc/passwd",
        "../../../etc/passwd",
        "%2e%2e/%2e%2e/etc/passwd",
        "https://attacker.example/page.md",
        f"{ABSOLUTE_BASE_URL}%2e%2e/secret.md",
        "page.md?download=1",
        "page.md#fragment",
        "..\\secret.md",
        "page.md\0ignored",
    ],
)
def test_resolve_local_target_rejects_unsafe_urls(tmp_path: Path, url: str) -> None:
    (tmp_path / "page.md").write_text("# Page\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        resolve_local_target(
            url,
            source=PurePosixPath("nested/llms.txt"),
            build_root=tmp_path,
            absolute_base_url=ABSOLUTE_BASE_URL,
        )


def test_resolve_local_target_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (tmp_path / "linked.md").symlink_to(outside)

    with pytest.raises(AssertionError, match="escapes the build root"):
        resolve_local_target(
            "linked.md",
            source=PurePosixPath("llms.txt"),
            build_root=tmp_path,
        )
