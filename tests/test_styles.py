"""Tests for backend.styles — style CRUD operations."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.styles import (
    StyleStore,
    StyleRecord,
    StyleCreateRequest,
    list_styles,
    create_style,
    delete_style,
    get_style,
    load_style_store,
    save_style_store,
    _default_store,
    _style_defaults,
    utc_slug,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def styles_dir(tmp_path):
    """Patch STYLES_PATH and DATA_DIR to use a temp directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    styles_path = data_dir / "styles.json"
    with patch("backend.styles.DATA_DIR", data_dir), \
         patch("backend.styles.STYLES_PATH", styles_path):
        yield styles_path


# ─── utc_slug ─────────────────────────────────────────────────────────────────


class TestUtcSlug:
    def test_basic_conversion(self):
        assert utc_slug("Hello World") == "hello_world"

    def test_chinese_characters(self):
        result = utc_slug("日系动画")
        assert result  # Should produce something non-empty

    def test_special_characters_replaced(self):
        result = utc_slug("test@#$%style")
        assert "@" not in result
        assert "#" not in result

    def test_empty_string_returns_style(self):
        assert utc_slug("") == "style"

    def test_whitespace_only_returns_style(self):
        assert utc_slug("   ") == "style"


# ─── list_styles ──────────────────────────────────────────────────────────────


class TestListStyles:
    def test_returns_default_styles_when_no_file(self, styles_dir):
        store = list_styles()
        assert isinstance(store, StyleStore)
        assert len(store.styles) > 0

    def test_default_styles_include_anime_standard(self, styles_dir):
        store = list_styles()
        ids = [s.id for s in store.styles]
        assert "anime_standard" in ids

    def test_default_style_id_is_set(self, styles_dir):
        store = list_styles()
        assert store.default_style_id != ""

    def test_all_default_styles_are_system_category(self, styles_dir):
        store = list_styles()
        for style in store.styles:
            if style.id in {s["id"] for s in _style_defaults()}:
                assert style.category == "system"


# ─── create_style ─────────────────────────────────────────────────────────────


class TestCreateStyle:
    def test_creates_user_style(self, styles_dir):
        request = StyleCreateRequest(
            name="自定义风格",
            positive_suffix="custom positive",
            negative_suffix="custom negative",
        )
        result = create_style(request)
        assert isinstance(result, StyleRecord)
        assert result.name == "自定义风格"
        assert result.category == "user"
        assert result.positive_suffix == "custom positive"

    def test_created_style_appears_in_list(self, styles_dir):
        create_style(StyleCreateRequest(name="新风格"))
        store = list_styles()
        names = [s.name for s in store.styles]
        assert "新风格" in names

    def test_duplicate_id_raises_error(self, styles_dir):
        create_style(StyleCreateRequest(id="unique_id", name="First"))
        with pytest.raises(ValueError, match="already exists"):
            create_style(StyleCreateRequest(id="unique_id", name="Second"))

    def test_custom_id_used_when_provided(self, styles_dir):
        result = create_style(StyleCreateRequest(id="my_custom_id", name="Custom"))
        assert result.id == "my_custom_id"

    def test_id_auto_generated_from_name(self, styles_dir):
        result = create_style(StyleCreateRequest(name="Test Style"))
        assert result.id == "test_style"


# ─── delete_style ─────────────────────────────────────────────────────────────


class TestDeleteStyle:
    def test_deletes_user_style(self, styles_dir):
        create_style(StyleCreateRequest(id="to_delete", name="Delete Me"))
        store = delete_style("to_delete")
        ids = [s.id for s in store.styles]
        assert "to_delete" not in ids

    def test_cannot_delete_system_style(self, styles_dir):
        # Ensure default styles are loaded
        list_styles()
        with pytest.raises(ValueError, match="System styles cannot be deleted"):
            delete_style("anime_standard")

    def test_deleting_nonexistent_style_raises_key_error(self, styles_dir):
        list_styles()  # Initialize
        with pytest.raises(KeyError):
            delete_style("nonexistent_id")

    def test_deleting_empty_id_raises_key_error(self, styles_dir):
        with pytest.raises(KeyError):
            delete_style("")

    def test_delete_updates_default_if_needed(self, styles_dir):
        # Create a user style and set it as default
        create_style(StyleCreateRequest(id="temp_default", name="Temp"))
        store = load_style_store()
        store.default_style_id = "temp_default"
        save_style_store(store)

        result = delete_style("temp_default")
        # Default should be reassigned
        assert result.default_style_id != "temp_default"
        assert result.default_style_id != ""


# ─── get_style ────────────────────────────────────────────────────────────────


class TestGetStyle:
    def test_get_existing_style(self, styles_dir):
        list_styles()  # Initialize
        style = get_style("anime_standard")
        assert style.id == "anime_standard"
        assert style.name == "日系动画"

    def test_get_nonexistent_style_raises_key_error(self, styles_dir):
        list_styles()  # Initialize
        with pytest.raises(KeyError):
            get_style("nonexistent")

    def test_get_empty_id_raises_key_error(self, styles_dir):
        with pytest.raises(KeyError):
            get_style("")

    def test_get_user_created_style(self, styles_dir):
        create_style(StyleCreateRequest(id="user_style", name="User Style", positive_suffix="test"))
        style = get_style("user_style")
        assert style.name == "User Style"
        assert style.positive_suffix == "test"
        assert style.category == "user"
