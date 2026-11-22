"""Our first tool: the current time."""
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import Field

from helper.tools.registry import Tool, ToolArgs, ToolError


class TimeArgs(ToolArgs):
    timezone: str = Field(
        default="",
        description="IANA timezone such as 'Asia/Tokyo'. Leave empty for the user's local time.",
    )


async def current_time(args: TimeArgs) -> str:
    if args.timezone:
        try:
            now = datetime.now(ZoneInfo(args.timezone))
        except (KeyError, ValueError, OSError):  # unknown or malformed names
            raise ToolError(f"unknown timezone '{args.timezone}'. Use a name like 'Asia/Tokyo'.")
    else:
        now = datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %H:%M (%Z, UTC%z)")


get_current_time = Tool(
    name="get_current_time",
    description="Get the current date and time, locally or in another timezone.",
    args=TimeArgs,
    run=current_time,
)
