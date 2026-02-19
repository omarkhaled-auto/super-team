"""Tests for the breaking change detector (pure function, no DB needed)."""
import pytest

from src.contract_engine.services.breaking_change_detector import detect_breaking_changes


class TestDetectBreakingChanges:
    """Tests for detect_breaking_changes()."""

    def test_no_changes_returns_empty(self):
        """Identical specs should produce no breaking changes."""
        spec = {
            "paths": {
                "/api/users": {
                    "get": {"summary": "List users"},
                },
            },
        }
        changes = detect_breaking_changes(spec, spec)
        assert changes == []

    def test_removed_path_is_error(self):
        """Removing a path should be classified as severity=error."""
        old_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/orders": {"get": {"summary": "List orders"}},
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        removed = [c for c in changes if c.change_type == "path_removed"]
        assert len(removed) == 1
        assert removed[0].path == "/api/orders"
        assert removed[0].severity == "error"
        assert removed[0].old_value == "/api/orders"
        assert removed[0].new_value is None

    def test_added_path_is_info(self):
        """Adding a new path should be classified as severity=info."""
        old_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/products": {"get": {"summary": "List products"}},
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        added = [c for c in changes if c.change_type == "path_added"]
        assert len(added) == 1
        assert added[0].path == "/api/products"
        assert added[0].severity == "info"
        assert added[0].new_value == "/api/products"

    def test_removed_method_is_error(self):
        """Removing an HTTP method from a path should be severity=error."""
        old_spec = {
            "paths": {
                "/api/users": {
                    "get": {"summary": "List users"},
                    "post": {"summary": "Create user"},
                },
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {
                    "get": {"summary": "List users"},
                },
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        removed = [c for c in changes if c.change_type == "method_removed"]
        assert len(removed) == 1
        assert removed[0].path == "/api/users.POST"
        assert removed[0].severity == "error"
        assert removed[0].old_value == "POST"

    def test_added_method_is_info(self):
        """Adding an HTTP method to a path should be severity=info."""
        old_spec = {
            "paths": {
                "/api/users": {
                    "get": {"summary": "List users"},
                },
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {
                    "get": {"summary": "List users"},
                    "delete": {"summary": "Delete user"},
                },
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        added = [c for c in changes if c.change_type == "method_added"]
        assert len(added) == 1
        assert added[0].path == "/api/users.DELETE"
        assert added[0].severity == "info"
        assert added[0].new_value == "DELETE"

    def test_schema_type_change_is_error(self):
        """Changing a component schema's type field should be severity=error."""
        old_spec = {
            "paths": {},
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                        },
                    },
                },
            },
        }
        new_spec = {
            "paths": {},
            "components": {
                "schemas": {
                    "User": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        type_changes = [c for c in changes if c.change_type == "type_changed"]
        assert len(type_changes) == 1
        assert type_changes[0].old_value == "object"
        assert type_changes[0].new_value == "array"
        assert type_changes[0].severity == "error"

    def test_added_required_field_is_warning(self):
        """Adding a required field to a request body schema should be severity=warning."""
        old_spec = {
            "paths": {
                "/api/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                        },
                                        "required": ["name"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name", "email"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        # The new "email" property is required -> should be warning
        required_added = [c for c in changes if c.change_type == "required_property_added"]
        assert len(required_added) == 1
        assert required_added[0].new_value == "email"
        assert required_added[0].severity == "warning"

    def test_empty_to_populated(self):
        """Going from empty paths to populated paths should produce only info changes."""
        old_spec = {"paths": {}}
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/orders": {"post": {"summary": "Create order"}},
            },
        }

        changes = detect_breaking_changes(old_spec, new_spec)

        assert len(changes) >= 2
        # All changes from empty -> populated should be info (additions)
        for change in changes:
            assert change.severity == "info", (
                f"Expected severity=info for {change.change_type} at {change.path}, "
                f"got {change.severity}"
            )

    def test_both_empty_no_changes(self):
        """Two specs with empty paths should produce no changes."""
        old_spec = {"paths": {}}
        new_spec = {"paths": {}}

        changes = detect_breaking_changes(old_spec, new_spec)

        assert changes == []

    # ------------------------------------------------------------------
    # BreakingChange.is_breaking field tests
    # ------------------------------------------------------------------

    def test_added_path_is_not_breaking(self):
        """Adding a new path (info severity) should have is_breaking=False."""
        old_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/products": {"get": {"summary": "List products"}},
            },
        }
        changes = detect_breaking_changes(old_spec, new_spec)
        info_changes = [c for c in changes if c.severity == "info"]
        assert len(info_changes) >= 1
        for change in info_changes:
            assert change.is_breaking is False, (
                f"Info-severity change {change.change_type} should have is_breaking=False"
            )

    def test_removed_path_is_breaking(self):
        """Removing a path (error severity) should have is_breaking=True."""
        old_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/orders": {"get": {"summary": "List orders"}},
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
            },
        }
        changes = detect_breaking_changes(old_spec, new_spec)
        error_changes = [c for c in changes if c.severity == "error"]
        assert len(error_changes) >= 1
        for change in error_changes:
            assert change.is_breaking is True, (
                f"Error-severity change {change.change_type} should have is_breaking=True"
            )

    def test_warning_severity_is_breaking(self):
        """Warning-severity changes (e.g. added required field) should have is_breaking=True."""
        old_spec = {
            "paths": {
                "/api/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                        },
                                        "required": ["name"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name", "email"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        changes = detect_breaking_changes(old_spec, new_spec)
        warning_changes = [c for c in changes if c.severity == "warning"]
        assert len(warning_changes) >= 1
        for change in warning_changes:
            assert change.is_breaking is True, (
                f"Warning-severity change {change.change_type} should have is_breaking=True"
            )

    def test_is_breaking_field_exists_on_all_changes(self):
        """All BreakingChange objects should have the is_breaking field."""
        old_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
            },
        }
        new_spec = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/new": {"post": {"summary": "Create"}},
            },
        }
        changes = detect_breaking_changes(old_spec, new_spec)
        for change in changes:
            assert hasattr(change, "is_breaking")
            assert isinstance(change.is_breaking, bool)

    def test_schema_type_change_is_breaking_true(self):
        """Changing a component schema type (error severity) should have is_breaking=True."""
        old_spec = {
            "paths": {},
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }
        new_spec = {
            "paths": {},
            "components": {
                "schemas": {
                    "User": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        }
        changes = detect_breaking_changes(old_spec, new_spec)
        type_changes = [c for c in changes if c.change_type == "type_changed"]
        assert len(type_changes) >= 1
        for change in type_changes:
            assert change.is_breaking is True
