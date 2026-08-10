"""DataUpdateCoordinator for the Remember The Milk integration."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import override

from aiortm import AioRTMClient, AioRTMError, AuthError

from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER

UPDATE_INTERVAL = timedelta(minutes=5)


@dataclass
class RtmTask:
    """An RTM task with its HA representation and note metadata."""

    uid: str
    todo_item: TodoItem
    note_id: int | None


@dataclass
class RememberTheMilkData:
    """Runtime data for a Remember The Milk config entry."""

    entity_id: str
    client: AioRTMClient
    coordinator: RtmTodoCoordinator
    known_list_ids: set[int]


type RememberTheMilkConfigEntry = ConfigEntry[RememberTheMilkData]


class RtmTodoCoordinator(DataUpdateCoordinator[dict[int, list[RtmTask]]]):
    """Coordinator for updating task data from RTM."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RememberTheMilkConfigEntry,
        client: AioRTMClient,
    ) -> None:
        """Initialize the RTM coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    @override
    async def _async_update_data(self) -> dict[int, list[RtmTask]]:
        """Fetch tasks for all lists from the RTM API."""
        try:
            response = await self.client.rtm.tasks.get_list()
        except AuthError as err:
            raise ConfigEntryAuthFailed("Invalid token") from err
        except AioRTMError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        result: dict[int, list[RtmTask]] = {}
        for task_list in response.tasks.task_list:
            rtm_tasks: list[RtmTask] = []
            for taskseries in task_list.taskseries:
                for task in taskseries.task:
                    if task.deleted is not None:
                        continue
                    uid = f"{task_list.id}_{taskseries.id}_{task.id}"
                    status = (
                        TodoItemStatus.COMPLETED
                        if task.completed is not None
                        else TodoItemStatus.NEEDS_ACTION
                    )
                    due: date | datetime | None = None
                    if task.due is not None:
                        due = task.due if task.has_due_time else task.due.date()
                    description: str | None = None
                    note_id: int | None = None
                    if taskseries.notes:
                        first_note = taskseries.notes[0]
                        description = first_note.body or None
                        note_id = first_note.id
                    rtm_tasks.append(
                        RtmTask(
                            uid=uid,
                            todo_item=TodoItem(
                                uid=uid,
                                summary=taskseries.name,
                                status=status,
                                due=due,
                                description=description,
                            ),
                            note_id=note_id,
                        )
                    )
            result[task_list.id] = rtm_tasks
        return result
