from document_service.model_registry import load_metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "document"
    if type_ == "table":
        return name != "alembic_version"
    return True


def migration_comparison_options() -> dict[str, object]:
    """Shared filter/version-table settings for env.py and metadata drift tests."""
    return {
        "target_metadata": load_metadata(),
        "version_table_schema": "document",
        "include_schemas": True,
        "include_name": include_name,
    }
