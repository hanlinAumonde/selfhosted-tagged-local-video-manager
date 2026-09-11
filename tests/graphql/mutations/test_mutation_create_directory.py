"""
Behaviour specification — the ``createDirectory`` mutation.

The delivery layer's share of the feature: validate the input contract, delegate, and
publish the result. Name validation lives in the Pydantic input model, so a rejected
name must never reach the service at all — each refusal below asserts that too.
"""

import pytest

from src.config import Settings
from src.errors import InputValidationError
from tests.graphql.helpers import (
    CREATE_DIRECTORY,
    assert_error_contains,
    assert_no_errors,
    make_create_directory_input,
)

pytestmark = pytest.mark.mutation

NEW_DIR_DB_PATH = "Test-category/Test-resource/new_folder"


# -----------------------------------------------------------------------
# ---------------------------- Delegation --------------------------------
# -----------------------------------------------------------------------

async def test_create_directory_delegates_to_the_browse_service(
    execute_gql, init_db, mock_browse_file_service,
):
    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name="new_folder")}
    )

    assert_no_errors(result)
    parent_path, name = mock_browse_file_service.create_directory.await_args.args
    assert parent_path.DB_format_path() == "Test-category/Test-resource"
    assert name == "new_folder"


async def test_create_directory_reports_success_and_the_created_path(
    execute_gql, init_db, mock_browse_file_service,
):
    mock_browse_file_service.create_directory.return_value = NEW_DIR_DB_PATH

    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name="new_folder")}
    )

    assert_no_errors(result)
    payload = result.data["createDirectory"]
    assert payload == {"success": True, "name": "new_folder", "path": NEW_DIR_DB_PATH}


# -----------------------------------------------------------------------
# ------------------------ Input contract --------------------------------
# -----------------------------------------------------------------------

async def test_create_directory_rejects_a_name_with_a_path_separator(
    execute_gql, init_db, mock_browse_file_service,
):
    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name="outer/inner")}
    )

    assert_error_contains(result, "CreateDirectoryInput")
    mock_browse_file_service.create_directory.assert_not_awaited()


async def test_create_directory_rejects_a_blank_name(
    execute_gql, init_db, mock_browse_file_service,
):
    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name="   ")}
    )

    assert_error_contains(result, "CreateDirectoryInput")
    mock_browse_file_service.create_directory.assert_not_awaited()


async def test_create_directory_rejects_a_name_over_the_configured_length(
    execute_gql, init_db, mock_browse_file_service, test_settings: Settings,
):
    too_long = "x" * (test_settings.validation.name_max_length + 1)

    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name=too_long)}
    )

    assert_error_contains(result, "CreateDirectoryInput")
    mock_browse_file_service.create_directory.assert_not_awaited()


async def test_create_directory_rejects_a_parent_path_escaping_its_category(
    execute_gql, init_db, mock_browse_file_service,
):
    result = await execute_gql(
        CREATE_DIRECTORY,
        {
            "input": make_create_directory_input(
                parent_relative_path="Test-category/Test-resource/../.."
            )
        },
    )

    assert_error_contains(result, "CreateDirectoryInput")
    mock_browse_file_service.create_directory.assert_not_awaited()


# -----------------------------------------------------------------------
# ---------------------- Failure surfaced from below ---------------------
# -----------------------------------------------------------------------

async def test_create_directory_surfaces_a_name_already_taken(
    execute_gql, init_db, mock_browse_file_service,
):
    mock_browse_file_service.create_directory.side_effect = InputValidationError(
        field="name", issue="'subdir' already exists in this directory"
    )

    result = await execute_gql(
        CREATE_DIRECTORY, {"input": make_create_directory_input(name="subdir")}
    )

    assert_error_contains(result, "already exists in this directory")
