# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "sphinx-llm"
copyright = "2024, Jacob Tomlinson"
author = "Jacob Tomlinson"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx_llm.docref",
    "sphinx_llm.txt",
]

llms_txt_summary_enabled = False
llms_txt_summary_model = "qwen3.5:2b"
llms_txt_description = """A collection of Sphinx extensions for working with LLMs in your documentation.
This includes:
- Generating a rich `llms.txt` index and individual page markdown context files.
- A directive for summarising and referencing other pages in your documentation.
"""

# llms.txt v2 supports "append" and "replace" Markdown URL forms. The default
# "auto" is a sphinx-llm compatibility convenience that publishes both.
llms_txt_suffix_mode = "auto"
llms_txt_nested_enabled = True

# llms-full.txt is a non-standard sphinx-llm convenience, not part of v2.
llms_txt_full_build = False

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"
html_static_path = ["_static"]
