"""Test the Remember The Milk config flow."""

import asyncio
from collections.abc import Awaitable, Generator
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.remember_the_milk.config_flow import (
    TOKEN_TIMEOUT_SEC,
    AuthError,
    ResponseError,
)
from homeassistant.components.remember_the_milk.const import (
    CONF_LIST_ID,
    DOMAIN,
    SUBENTRY_TYPE_LIST,
)
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigSubentryDataWithId,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .const import CREATE_ENTRY_DATA, PROFILE

from tests.common import MockConfigEntry

TOKEN_DATA = {
    "token": "test-token",
    "user": {
        "fullname": PROFILE,
        "id": "test-user-id",
        "username": PROFILE,
    },
}

SUBENTRY_ID = "test-subentry-id"
LIST_ID = 99


@pytest.fixture
def mock_flow_client() -> Generator[MagicMock]:
    """Mock the AioRTMClient used in the config flow to fetch existing lists."""
    lists_response = MagicMock()
    lists_response.lists = [_make_list_mock(LIST_ID, "Shopping")]
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.AioRTMClient"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client.rtm.lists.get_list = AsyncMock(return_value=lists_response)
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def ignore_missing_translations(request: pytest.FixtureRequest) -> list[str]:
    """Ignore per-account service translations for subentry tests that do real setup."""
    for marker in request.node.iter_markers("usefixtures"):
        if "storage" in marker.args:
            return [
                f"component.{DOMAIN}.services.{PROFILE}_create_task.",
                f"component.{DOMAIN}.services.{PROFILE}_complete_task.",
            ]
    return []


def get_suggested_value(data_schema: vol.Schema, key: str) -> Any:
    """Return the suggested value for a key in a data schema."""
    for schema_key in data_schema.schema:
        if schema_key == key:
            return (schema_key.description or {}).get("suggested_value")
    return None


def _make_list_mock(list_id: int, name: str, **flags: bool) -> MagicMock:
    """Create a mock RTM list response object."""
    lst = MagicMock()
    lst.id = list_id
    lst.name = name
    lst.smart = flags.get("smart", False)
    lst.archived = flags.get("archived", False)
    lst.locked = flags.get("locked", False)
    lst.deleted = flags.get("deleted", False)
    return lst


@pytest.fixture
def config_entry_with_subentry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a loaded mock config entry with one list subentry."""
    entry = MockConfigEntry(
        data=CREATE_ENTRY_DATA,
        domain=DOMAIN,
        subentries_data=[
            ConfigSubentryDataWithId(
                data={CONF_LIST_ID: LIST_ID},
                subentry_type=SUBENTRY_TYPE_LIST,
                title="Shopping",
                unique_id=str(LIST_ID),
                subentry_id=SUBENTRY_ID,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_successful_flow(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_flow_client: MagicMock
) -> None:
    """Test successful flow creates subentries for existing lists."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == PROFILE
    assert result["data"] == CREATE_ENTRY_DATA
    assert result["result"].unique_id == "test-user-id"
    assert len(mock_setup_entry.mock_calls) == 1
    entry = result["result"]
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_LIST
    assert subentry.title == "Shopping"
    assert subentry.data[CONF_LIST_ID] == LIST_ID
    assert subentry.unique_id == str(LIST_ID)


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (AuthError, "invalid_auth"),
        (ResponseError, "cannot_connect"),
        (Exception, "unknown"),
    ],
)
async def test_form_errors(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_flow_client: MagicMock,
    exception: type[Exception],
    error: str,
) -> None:
    """Test form errors when getting the authentication URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        side_effect=exception,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": error}

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == PROFILE
    assert result["data"] == CREATE_ENTRY_DATA
    assert result["result"].unique_id == "test-user-id"
    assert len(mock_setup_entry.mock_calls) == 1
    entry = result["result"]
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert subentry.title == "Shopping"
    assert subentry.data[CONF_LIST_ID] == LIST_ID


async def mock_get_token(*args: Any) -> None:
    """Handle get token."""
    await asyncio.Future()


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("side_effect", "reason", "timeout"),
    [
        (AuthError, "invalid_auth", TOKEN_TIMEOUT_SEC),
        (ResponseError, "cannot_connect", TOKEN_TIMEOUT_SEC),
        (Exception, "unknown", TOKEN_TIMEOUT_SEC),
        (mock_get_token, "timeout_token", 0),
    ],
)
async def test_token_abort_reasons(
    hass: HomeAssistant,
    side_effect: type[Exception] | Awaitable[None],
    reason: str,
    timeout: int,
) -> None:
    """Test abort result when getting token."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )

    with (
        patch(
            "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
            side_effect=side_effect,
        ),
        patch(
            "homeassistant.components.remember_the_milk.config_flow.TOKEN_TIMEOUT_SEC",
            timeout,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_setup_entry")
async def test_abort_if_already_configured(hass: HomeAssistant) -> None:
    """Test abort if the same username is already configured."""
    mock_entry = MockConfigEntry(domain=DOMAIN, unique_id="test-user-id")
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    "source", [config_entries.SOURCE_IMPORT, config_entries.SOURCE_USER]
)
@pytest.mark.parametrize(
    ("reauth_unique_id", "abort_reason", "abort_entry_data"),
    [
        (
            "test-user-id",
            "reauth_successful",
            CREATE_ENTRY_DATA | {"token": "new-test-token"},
        ),
        ("other-user-id", "unique_id_mismatch", CREATE_ENTRY_DATA),
    ],
)
async def test_reauth(
    hass: HomeAssistant,
    source: str,
    reauth_unique_id: str,
    abort_reason: str,
    abort_entry_data: dict[str, str],
) -> None:
    """Test reauth flow."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="test-user-id", data=CREATE_ENTRY_DATA, source=source
    )
    mock_entry.add_to_hass(hass)

    result = await mock_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # The credentials form is pre-filled from the stored config entry data.
    data_schema = result["data_schema"]
    assert data_schema is not None
    assert get_suggested_value(data_schema, "api_key") == "test-api-key"
    assert get_suggested_value(data_schema, "shared_secret") == "test-secret"

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
            },
        )
    reauth_data: dict[str, Any] = deepcopy(TOKEN_DATA) | {"token": "new-test-token"}
    reauth_data["user"]["id"] = reauth_unique_id
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=reauth_data,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == abort_reason
    assert mock_entry.data == abort_entry_data
    assert mock_entry.unique_id == "test-user-id"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_change_credentials(hass: HomeAssistant) -> None:
    """Test reauth flow where the user changes the stored credentials."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="test-user-id", data=CREATE_ENTRY_DATA
    )
    mock_entry.add_to_hass(hass)

    result = await mock_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "user"

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_key": "new-api-key",
                "shared_secret": "new-secret",
            },
        )

    reauth_data = deepcopy(TOKEN_DATA) | {"token": "new-test-token"}
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=reauth_data,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data == {
        "api_key": "new-api-key",
        "shared_secret": "new-secret",
        "token": "new-test-token",
        "username": PROFILE,
    }
    assert mock_entry.unique_id == "test-user-id"


async def test_import_flow(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_flow_client: MagicMock
) -> None:
    """Test import flow with a valid stored token creates subentries for existing lists."""
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.check_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
                "name": PROFILE,
                "token": "test-token",
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == PROFILE
    assert result["data"] == {
        "api_key": "test-api-key",
        "shared_secret": "test-secret",
        "token": "test-token",
        "username": PROFILE,
    }
    assert result["result"].unique_id == "test-user-id"
    assert len(mock_setup_entry.mock_calls) == 1
    entry = result["result"]
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_LIST
    assert subentry.title == "Shopping"
    assert subentry.data[CONF_LIST_ID] == LIST_ID
    assert subentry.unique_id == str(LIST_ID)


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("token", "side_effect", "reason"),
    [
        (None, None, "invalid_auth"),
        ("test-token", AuthError, "invalid_auth"),
        ("test-token", ResponseError, "cannot_connect"),
        ("test-token", Exception, "unknown"),
    ],
)
async def test_import_flow_abort(
    hass: HomeAssistant,
    token: str | None,
    side_effect: type[Exception] | None,
    reason: str,
) -> None:
    """Test import flow aborts without a valid token."""
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.check_token",
        side_effect=side_effect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
                "name": "test-name",
                "token": token,
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_setup_entry")
async def test_import_flow_username_mismatch(hass: HomeAssistant) -> None:
    """Test import flow aborts when the token username doesn't match the name."""
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.check_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
                "name": "other-name",
                "token": "test-token",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_import_flow_already_configured(hass: HomeAssistant) -> None:
    """Test import flow aborts when the account name is already configured."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "api_key": "new-api-key",
            "shared_secret": "new-secret",
            "token": "test-token",
            "username": PROFILE,
        },
        unique_id=PROFILE,
    )
    mock_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.check_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
                "name": PROFILE,
                "token": "test-token",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize("exception", [AuthError, ResponseError])
async def test_flow_list_fetch_failure(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    exception: type[Exception],
) -> None:
    """Test that a list fetch failure during entry creation aborts the flow."""
    mock_flow_client.rtm.lists.get_list = AsyncMock(side_effect=exception("error"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "test-api-key", "shared_secret": "test-secret"},
        )
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize("exception", [AuthError, ResponseError])
async def test_import_flow_list_fetch_failure(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    exception: type[Exception],
) -> None:
    """Test that a list fetch failure during import aborts the flow."""
    mock_flow_client.rtm.lists.get_list = AsyncMock(side_effect=exception("error"))

    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.check_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "api_key": "test-api-key",
                "shared_secret": "test-secret",
                "name": PROFILE,
                "token": "test-token",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_flow_filters_special_lists(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """Test that smart, archived, locked, and deleted lists are not created as subentries."""
    lists_response = MagicMock()
    lists_response.lists = [
        _make_list_mock(1, "Normal List"),
        _make_list_mock(2, "Smart List", smart=True),
        _make_list_mock(3, "Archived List", archived=True),
        _make_list_mock(4, "Locked List", locked=True),
        _make_list_mock(5, "Deleted List", deleted=True),
    ]
    mock_flow_client.rtm.lists.get_list = AsyncMock(return_value=lists_response)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.authenticate_desktop",
        return_value=("https://test-url.com", "test-frob"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "test-api-key", "shared_secret": "test-secret"},
        )
    with patch(
        "homeassistant.components.remember_the_milk.config_flow.Auth.get_token",
        return_value=TOKEN_DATA,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert subentry.title == "Normal List"
    assert subentry.data[CONF_LIST_ID] == 1


@pytest.mark.usefixtures("storage")
async def test_create_new_list(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test creating a new RTM list creates a subentry."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "Work Tasks"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Work Tasks"
    assert result["data"] == {CONF_LIST_ID: 42}

    client.rtm.lists.add.assert_called_once_with(
        timeline=1234,
        name="Work Tasks",
    )
    assert len(config_entry.subentries) == 1


@pytest.mark.usefixtures("storage")
async def test_create_cannot_connect(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test that an API error in the create step shows an error."""
    client.rtm.lists.add = AsyncMock(side_effect=ResponseError(500, "server error"))

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input={CONF_NAME: "Failing List"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_entry_not_loaded(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test abort when the parent config entry is not loaded."""
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def test_reconfigure_entry_not_loaded(
    hass: HomeAssistant,
    config_entry_with_subentry: MockConfigEntry,
) -> None:
    """Test abort in reconfigure when the parent config entry is not loaded."""
    subentry = next(iter(config_entry_with_subentry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (config_entry_with_subentry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


@pytest.mark.usefixtures("storage")
async def test_reconfigure_subentry(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry_with_subentry: MockConfigEntry,
) -> None:
    """Test renaming a subentry via reconfigure."""
    await hass.config_entries.async_setup(config_entry_with_subentry.entry_id)
    await hass.async_block_till_done()

    subentry = next(iter(config_entry_with_subentry.subentries.values()))
    assert subentry.title == "Shopping"

    result = await hass.config_entries.subentries.async_init(
        (config_entry_with_subentry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "Grocery Shopping"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = next(iter(config_entry_with_subentry.subentries.values()))
    assert subentry.title == "Grocery Shopping"
    assert subentry.data[CONF_LIST_ID] == LIST_ID
    client.rtm.lists.set_name.assert_called_once_with(
        timeline=1234, list_id=LIST_ID, name="Grocery Shopping"
    )


@pytest.mark.usefixtures("storage")
async def test_reconfigure_cannot_connect(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry_with_subentry: MockConfigEntry,
) -> None:
    """Test that an API error in the reconfigure step shows an error."""
    client.rtm.lists.set_name = AsyncMock(
        side_effect=ResponseError(500, "server error")
    )

    await hass.config_entries.async_setup(config_entry_with_subentry.entry_id)
    await hass.async_block_till_done()

    subentry = next(iter(config_entry_with_subentry.subentries.values()))

    result = await hass.config_entries.subentries.async_init(
        (config_entry_with_subentry.entry_id, SUBENTRY_TYPE_LIST),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "Grocery Shopping"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
