from .approval_tools import request_user_confirmation
from .calendar import create_calendar_event, get_calendar_events
from .files import read_file, search_files
from .mail import modify_email, read_email, search_emails, send_email
from .personal import get_personal_context

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
    request_user_confirmation,
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
    "request_user_confirmation",
    "ALL_TOOLS",
]
