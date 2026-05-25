from agnostic.navigation.slices.data_slices import (
    DataContext,
    FilterCondition,
    build_query,
    create_slice,
    normalize_table_name,
)


def test_create_slice_deepen_inherits_previous_filters_and_parent() -> None:
    base = DataContext(
        source_table="drivers_license",
        filters=(FilterCondition(column="plate_number", operator="=", value="P24L4U"),),
    )

    child = create_slice(
        base,
        FilterCondition(column="gender", operator="=", value="female"),
        mode="deepen",
    )

    assert child.source_table == "drivers_license"
    assert child.parent_context == base
    assert tuple(item.column for item in child.filters) == ("plate_number", "gender")

    sql, params = build_query(child)
    assert sql == "SELECT * FROM drivers_license WHERE plate_number = ? AND gender = ?"
    assert params == ("P24L4U", "female")


def test_create_slice_new_base_resets_parent_and_filters() -> None:
    base = DataContext(
        source_table="person",
        filters=(FilterCondition(column="address_street_name", operator="LIKE", value="%Northwestern Dr%"),),
    )

    branch = create_slice(
        base,
        FilterCondition(column="name", operator="LIKE", value="Annabel%"),
        mode="new_base",
    )

    assert branch.parent_context is None
    assert len(branch.filters) == 1
    assert branch.filters[0].column == "name"

    sql, params = build_query(branch)
    assert sql == "SELECT * FROM person WHERE name LIKE ?"
    assert params == ("Annabel%",)


def test_build_query_supports_in_operator() -> None:
    context = DataContext(
        source_table="person",
        filters=(FilterCondition(column="id", operator="IN", value=(1, 2, 3)),),
    )

    sql, params = build_query(context)
    assert sql == "SELECT * FROM person WHERE id IN (?, ?, ?)"
    assert params == (1, 2, 3)


def test_normalize_table_name_from_csv_filename() -> None:
    assert normalize_table_name("sample-file.csv") == "sample_file"
    assert normalize_table_name("123-events.csv") == "t_123_events"
