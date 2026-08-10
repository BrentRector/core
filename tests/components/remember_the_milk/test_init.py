"""Test the Remember The Milk integration."""

from unittest.mock import MagicMock

from aiortm import AioRTMError, AuthError
import pytest

from homeassistant.components.remember_the_milk.const import (
    CONF_LIST_ID,
    DOMAIN,
    SUBENTRY_TYPE_LIST,
)
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryDataWithId
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .const import CREATE_ENTRY_DATA

from tests.common import MockConfigEntry

LIST_ID = 42
SUBENTRY_ID = "test-subentry-id"

CONFIG = {
    "name": "myprofile",
    "api_key": "test-api-key",
    "shared_secret": "test-shared-secret",
}


@pytest.fixture
def config_entry_with_subentry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a mock config entry with one list subentry."""
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


@pytest.mark.usefixtures("storage")
async def test_load_unload_config_entry(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test loading and unloading a config entry."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("client", "storage")
async def test_import_creates_deprecation_issue(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test a successful YAML import creates a deprecation repair issue."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: CONFIG})
    await hass.async_block_till_done()

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert issue_registry.async_get_issue(
        HOMEASSISTANT_DOMAIN, f"deprecated_yaml_{DOMAIN}"
    )


@pytest.mark.parametrize(
    ("side_effect", "expected_state"),
    [
        pytest.param(
            AuthError("Invalid token!"), ConfigEntryState.SETUP_ERROR, id="auth_error"
        ),
        pytest.param(
            AioRTMError("Boom!"), ConfigEntryState.SETUP_RETRY, id="api_error"
        ),
    ],
)
@pytest.mark.usefixtures("storage")
async def test_coordinator_update_errors(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    side_effect: Exception,
    expected_state: ConfigEntryState,
) -> None:
    """Test config entry state when the first coordinator refresh fails."""
    client.rtm.tasks.get_list.side_effect = side_effect
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is expected_state


@pytest.mark.parametrize("ignore_missing_translations", [[]])
@pytest.mark.usefixtures("client")
async def test_import_without_token_creates_issue(
    hass: HomeAssistant,
    storage: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test YAML import without a stored token aborts and creates an issue.

    Without a token the import can't be completed, so no config entry is
    created and the user is guided to set the integration up via the UI.
    """
    storage.get_token.return_value = None

    assert await async_setup_component(hass, DOMAIN, {DOMAIN: CONFIG})
    await hass.async_block_till_done()

    assert not hass.config_entries.async_entries(DOMAIN)
    assert issue_registry.async_get_issue(
        DOMAIN, "deprecated_yaml_import_issue_invalid_auth"
    )


@pytest.mark.usefixtures("storage")
async def test_remove_subentry_deletes_list(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry_with_subentry: MockConfigEntry,
) -> None:
    """Test that removing a list sub-entry deletes the list on the RTM server."""
    await hass.config_entries.async_setup(config_entry_with_subentry.entry_id)
    await hass.async_block_till_done()
    assert config_entry_with_subentry.state is ConfigEntryState.LOADED

    hass.config_entries.async_remove_subentry(config_entry_with_subentry, SUBENTRY_ID)
    await hass.async_block_till_done()

    client.rtm.timelines.create.assert_called_once()
    client.rtm.lists.delete.assert_called_once_with(
        timeline=client.rtm.timelines.create.return_value.timeline,
        list_id=LIST_ID,
    )


@pytest.mark.usefixtures("storage")
async def test_rename_subentry_does_not_delete_list(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry_with_subentry: MockConfigEntry,
) -> None:
    """Test that renaming a sub-entry (no list removed) does not trigger deletion."""
    await hass.config_entries.async_setup(config_entry_with_subentry.entry_id)
    await hass.async_block_till_done()
    assert config_entry_with_subentry.state is ConfigEntryState.LOADED

    subentry = next(iter(config_entry_with_subentry.subentries.values()))
    hass.config_entries.async_update_subentry(
        config_entry_with_subentry, subentry, title="Grocery Shopping"
    )
    await hass.async_block_till_done()

    client.rtm.lists.delete.assert_not_called()


@pytest.mark.parametrize(
    "side_effect",
    [
        pytest.param(AuthError("Invalid token!"), id="auth_error"),
        pytest.param(AioRTMError("Boom!"), id="api_error"),
    ],
)
@pytest.mark.usefixtures("storage")
async def test_remove_subentry_delete_list_error(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry_with_subentry: MockConfigEntry,
    side_effect: Exception,
) -> None:
    """Test that a server error when deleting a list is logged and reload still runs."""
    await hass.config_entries.async_setup(config_entry_with_subentry.entry_id)
    await hass.async_block_till_done()
    assert config_entry_with_subentry.state is ConfigEntryState.LOADED

    client.rtm.lists.delete.side_effect = side_effect

    hass.config_entries.async_remove_subentry(config_entry_with_subentry, SUBENTRY_ID)
    await hass.async_block_till_done()

    client.rtm.lists.delete.assert_called_once()
    assert config_entry_with_subentry.state is ConfigEntryState.LOADED
