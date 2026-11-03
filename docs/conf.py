"""Sphinx configuration for the purplerain documentation.

Build locally with:

    pip install -e ".[docs]"
    sphinx-build -W -b html docs docs/_build/html
"""

from importlib.metadata import version as _package_version

project = "purplerain"
author = "Mark Joseph Campmier"
copyright = f"2024, {author}"
release = _package_version("purplerain")
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxarg.ext",
]
exclude_patterns = ["_build"]
# Keep "--option" intact in CLI help (no en-dash conversion); quotes still curl.
smartquotes_action = "qe"

# Markdown (MyST)
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# API reference
autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs", None),
    "requests": ("https://requests.readthedocs.io/en/latest", None),
}

# HTML
html_theme = "furo"
html_title = f"purplerain {release}"
html_theme_options = {
    "source_repository": "https://github.com/mjcampmier/purplerain",
    "source_branch": "master",
    "source_directory": "docs/",
}
