import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from src.db.session import async_session_factory
from src.db.models import ApiKey
from src.services.auth import generate_api_key
from src.config import settings

async def create_key(email: str, plan: str, billing_cycle: str):
    valid_plans = ("free", "starter", "pro", "enterprise")
    if plan not in valid_plans:
        print(f"Error: Invalid plan '{plan}'. Must be one of: {', '.join(valid_plans)}")
        return

    if billing_cycle not in ("monthly", "annual"):
        print("Error: billing_cycle must be 'monthly' or 'annual'.")
        return

    expires_at = None
    if billing_cycle == "monthly":
        expires_at = datetime.now(timezone.utc) + timedelta(days=31)
    elif billing_cycle == "annual":
        expires_at = datetime.now(timezone.utc) + timedelta(days=365)

    raw_key, key_prefix, key_hash = generate_api_key()
    monthly_quota = settings.get_monthly_quota(plan)

    async with async_session_factory() as session:
        api_key = ApiKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner_email=email,
            plan=plan,
            monthly_quota=monthly_quota,
            is_active=True,
            expires_at=expires_at,
        )
        session.add(api_key)
        await session.commit()

        print("=== API Key Created Successfully ===")
        print(f"Owner Email:    {email}")
        print(f"Plan:           {plan}")
        print(f"Billing Cycle:  {billing_cycle}")
        print(f"Expires At:     {expires_at}")
        print(f"Monthly Quota:  {monthly_quota}")
        print("-" * 34)
        print(f"API Key (Save this now!): {raw_key}")
        print("-" * 34)
        print("NOTE: You will only see the full API key this one time.")

def main():
    parser = argparse.ArgumentParser(description="Manage API Keys for Price API")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create-key command
    create_parser = subparsers.add_parser("create-key", help="Create a new API key")
    create_parser.add_argument("--email", required=True, help="Owner's email address")
    create_parser.add_argument("--plan", required=True, choices=["free", "starter", "pro", "enterprise"], help="Subscription plan")
    create_parser.add_argument("--cycle", required=True, choices=["monthly", "annual"], help="Billing cycle (monthly or annual)")

    args = parser.parse_args()

    if args.command == "create-key":
        asyncio.run(create_key(args.email, args.plan, args.cycle))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
