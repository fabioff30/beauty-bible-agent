"""
Manual trigger for the dream job.

Usage:
    python -m src.dreaming.run                    # default lookback 24h
    python -m src.dreaming.run --hours 168        # last week
    python -m src.dreaming.run --user 123456789   # one user only
"""

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()
load_dotenv('.env.local', override=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
)

from src.db.connection import init_db
from src.dreaming.job import run_consolidation, consolidate_user


async def amain(args):
    init_db()
    if args.user:
        result = await consolidate_user(args.user)
    else:
        result = await run_consolidation(lookback_hours=args.hours)
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Trigger BB dream consolidation manually.")
    parser.add_argument('--hours', type=int, default=24, help='Lookback window in hours.')
    parser.add_argument('--user', type=int, help='Run for a single user_id only.')
    args = parser.parse_args()
    asyncio.run(amain(args))


if __name__ == '__main__':
    main()
