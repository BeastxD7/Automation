import asyncio
import sys
from linkedin import send_invite, get_linkedin_context
from linkedin.login import do_login


async def cmd_login():
    await do_login()


async def cmd_invite(profile_url: str, force_llm: bool = False):
    async with get_linkedin_context(headless=False) as (browser, page):
        status = await send_invite(page, profile_url, force_llm=force_llm)
        print(f"Result: {status}")


def usage():
    print("Usage:")
    print("  python main.py login                                       # one-time login")
    print("  python main.py invite <linkedin-profile-url>               # send invite")
    print("  python main.py invite <linkedin-profile-url> --force-llm  # skip hardcoded selectors, use LLM only")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "login":
        asyncio.run(cmd_login())
    elif args[0] == "invite" and len(args) >= 2:
        force_llm = "--force-llm" in args
        asyncio.run(cmd_invite(args[1], force_llm=force_llm))
    else:
        usage()
