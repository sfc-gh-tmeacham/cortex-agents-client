"""Unit tests for _markdown_column_config dtype selection.

The original implementation used ``df.select_dtypes(include="object")``, which
emits a ``Pandas4Warning``: under pandas 3 the ``"object"`` selector no longer
implies the new ``"str"`` dtype, so string columns would silently stop being
configured as Markdown columns. The warning was found by running the real
render pipeline against a live Analyst answer (tests/live/test_streamlit_live.py);
no mock-based test touched this code path.
"""
from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from streamlit_cortex_agents.chat.render import _markdown_column_config


@pytest.fixture(autouse=True)
def _fake_streamlit():
    """Stubs streamlit so column_config does not need a real runtime."""
    fake_st = MagicMock()
    fake_st.column_config.MarkdownColumn = lambda col: f"markdown:{col}"
    with patch.dict("sys.modules", {"streamlit": fake_st}):
        yield fake_st


class TestTextColumnSelection:
    """String columns must be configured as Markdown columns."""

    def test_object_dtype_column_selected(self):
        df = pd.DataFrame({"name": ["a", "b"]})
        cfg = _markdown_column_config(df)
        assert cfg is not None
        assert "name" in cfg

    def test_explicit_string_dtype_column_selected(self):
        """A pandas StringDtype column is selected too.

        This is the case that breaks under pandas 3 with the old
        select_dtypes(include="object") call.
        """
        df = pd.DataFrame({"name": pd.array(["a", "b"], dtype="string")})
        cfg = _markdown_column_config(df)
        assert cfg is not None, "StringDtype column was not selected"
        assert "name" in cfg

    def test_numeric_columns_not_selected(self):
        df = pd.DataFrame({"n": [1, 2], "f": [1.5, 2.5]})
        assert _markdown_column_config(df) is None

    def test_mixed_frame_selects_only_text(self):
        df = pd.DataFrame(
            {
                "label": ["x", "y"],
                "count": [1, 2],
                "note": pd.array(["p", "q"], dtype="string"),
            }
        )
        cfg = _markdown_column_config(df)
        assert set(cfg) == {"label", "note"}, f"Selected {set(cfg)}"

    def test_empty_frame_returns_none(self):
        assert _markdown_column_config(pd.DataFrame()) is None


class TestNoDeprecationWarning:
    """The helper must not emit pandas deprecation warnings."""

    def test_no_warning_for_object_columns(self):
        """Reproduces the exact warning seen in the live AppTest run."""
        df = pd.DataFrame({"label": ["x", "y"], "count": [1, 2]})
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            warnings.simplefilter("error", FutureWarning)
            _markdown_column_config(df)

    def test_no_warning_for_string_dtype_columns(self):
        df = pd.DataFrame({"label": pd.array(["x", "y"], dtype="string")})
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            warnings.simplefilter("error", FutureWarning)
            _markdown_column_config(df)
