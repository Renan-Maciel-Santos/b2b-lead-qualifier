"""B2B Lead Qualifier core package."""

import asyncio
import sys

# On Windows, psycopg async requires SelectorEventLoop instead of ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

__version__ = "0.1.0"
