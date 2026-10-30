from .calendar import create_calendar_event, get_calendar_events
from .feedback import (
    check_cursor_fix,
    fix_friction_with_cursor,
    list_friction,
    note_friction,
    note_mistake,
    preview_pending_ship,
    resolve_friction,
    ship_pending_fix,
)
from .files import read_file, search_files
from .mail import modify_email, read_email, search_emails, send_email
from .memory import forget_fact, remember_fact, search_memory
from .personal import get_personal_context
from .reminders import cancel_reminder, remind_me
from .tasks import add_task, complete_task

# 待办接入了才给模型：没接入时它连「待办」这个词都不该提
TASK_TOOLS = [add_task, complete_task]

ALL_TOOLS = [
    get_calendar_events,
    create_calendar_event,
    search_files,
    read_file,
    search_emails,
    read_email,
    send_email,
    modify_email,
    get_personal_context,
    remind_me,
    cancel_reminder,
    remember_fact,
    search_memory,
    forget_fact,
    note_friction,
    note_mistake,
    list_friction,
    resolve_friction,
    fix_friction_with_cursor,
    check_cursor_fix,
    preview_pending_ship,
    ship_pending_fix,
]

__all__ = [
    "get_calendar_events",
    "create_calendar_event",
    "search_files",
    "read_file",
    "search_emails",
    "read_email",
    "send_email",
    "modify_email",
    "get_personal_context",
    "remind_me",
    "cancel_reminder",
    "remember_fact",
    "search_memory",
    "forget_fact",
    "note_friction",
    "note_mistake",
    "list_friction",
    "resolve_friction",
    "fix_friction_with_cursor",
    "check_cursor_fix",
    "preview_pending_ship",
    "ship_pending_fix",
    "add_task",
    "complete_task",
    "ALL_TOOLS",
    "TASK_TOOLS",
]
