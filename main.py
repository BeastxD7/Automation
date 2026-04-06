import asyncio
import sys
from linkedin import send_invite, get_linkedin_context
from linkedin.login import do_login


async def cmd_login():
    await do_login()


async def cmd_invite(profile_url: str):
    async with get_linkedin_context(headless=False) as (browser, page):
        success = await send_invite(page, profile_url)
        print(f"Invite sent: {success}")


def usage():
    print("Usage:")
    print("  python main.py login                          # one-time login")
    print("  python main.py invite <linkedin-profile-url> # send invite")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "login":
        asyncio.run(cmd_login())
    elif args[0] == "invite" and len(args) == 2:
        asyncio.run(cmd_invite(args[1]))
    else:
        usage()
