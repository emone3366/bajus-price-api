"""
Admin API endpoints.

Protected by ADMIN_SECRET for key management, usage viewing,
and Stripe webhook handling for subscription lifecycle events.
"""

import logging
from datetime import datetime, timedelta, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import ApiKey, ApiUsageLog
from src.db.session import get_db
from src.schemas.responses import (
    KeyCreateRequest,
    KeyCreateResponse,
    KeyInfoResponse,
)
from src.services.auth import generate_api_key, security_scheme, verify_admin
from src.utils.alerts import send_api_key_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post(
    "/keys",
    response_model=KeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new API key",
    description="Create a new API key for a subscriber. Admin access required.",
)
async def create_key(
    body: KeyCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> KeyCreateResponse:
    """Issue a new API key. The raw key is returned ONCE — save it immediately."""
    verify_admin(credentials)

    valid_plans = ("free", "starter", "pro", "enterprise")
    if body.plan not in valid_plans:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan '{body.plan}'. Must be one of: {', '.join(valid_plans)}",
        )

    if body.billing_cycle not in (None, "monthly", "annual"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="billing_cycle must be 'monthly' or 'annual'.",
        )

    expires_at = None
    if body.billing_cycle == "monthly":
        expires_at = datetime.now(timezone.utc) + timedelta(days=31)
    elif body.billing_cycle == "annual":
        expires_at = datetime.now(timezone.utc) + timedelta(days=365)

    raw_key, key_prefix, key_hash = generate_api_key()
    monthly_quota = settings.get_monthly_quota(body.plan)

    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner_email=body.owner_email,
        plan=body.plan,
        monthly_quota=monthly_quota,
        is_active=True,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()

    logger.info(
        "Created API key %s for %s (plan=%s, expires_at=%s).",
        key_prefix,
        body.owner_email,
        body.plan,
        expires_at,
    )

    return KeyCreateResponse(
        raw_key=raw_key,
        key_prefix=key_prefix,
        plan=body.plan,
        monthly_quota=monthly_quota,
        expires_at=expires_at,
    )


@router.get(
    "/keys",
    response_model=list[KeyInfoResponse],
    summary="List all API keys",
    description="List all issued API keys with their metadata. Admin access required.",
)
async def list_keys(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> list[KeyInfoResponse]:
    """List all API keys (no hashes exposed)."""
    verify_admin(credentials)

    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    keys = result.scalars().all()

    return [
        KeyInfoResponse(
            id=k.id,
            key_prefix=k.key_prefix,
            owner_email=k.owner_email,
            plan=k.plan,
            monthly_quota=k.monthly_quota,
            is_active=k.is_active,
            created_at=k.created_at,
            expires_at=k.expires_at,
            stripe_customer_id=k.stripe_customer_id,
            stripe_subscription_id=k.stripe_subscription_id,
        )
        for k in keys
    ]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description="Deactivate an API key so it can no longer be used. Admin access required.",
)
async def revoke_key(
    key_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deactivate an API key."""
    verify_admin(credentials)

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key with id {key_id} not found.",
        )

    api_key.is_active = False
    logger.info("Revoked API key %s (id=%d).", api_key.key_prefix, key_id)


@router.get(
    "/keys/{key_id}/usage",
    summary="View usage for a specific key",
    description="Get usage statistics for a specific API key. Admin access required.",
)
async def get_key_usage(
    key_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return usage stats for a specific API key."""
    verify_admin(credentials)

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key with id {key_id} not found.",
        )

    # Count total requests
    total_result = await db.execute(
        select(func.count(ApiUsageLog.id)).where(ApiUsageLog.api_key_id == key_id)
    )
    total = total_result.scalar() or 0

    # Count this month's requests
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_result = await db.execute(
        select(func.count(ApiUsageLog.id)).where(
            ApiUsageLog.api_key_id == key_id,
            ApiUsageLog.called_at >= month_start,
        )
    )
    this_month = month_result.scalar() or 0

    return {
        "key_id": key_id,
        "key_prefix": api_key.key_prefix,
        "owner_email": api_key.owner_email,
        "plan": api_key.plan,
        "total_requests": total,
        "requests_this_month": this_month,
        "monthly_quota": api_key.monthly_quota,
        "is_active": api_key.is_active,
        "stripe_customer_id": api_key.stripe_customer_id,
        "stripe_subscription_id": api_key.stripe_subscription_id,
    }


@router.post(
    "/webhook/stripe",
    status_code=status.HTTP_200_OK,
    summary="Stripe webhook handler",
    description=(
        "Handles Stripe subscription lifecycle events: "
        "issues API keys on checkout, deactivates on cancellation, "
        "updates plan on subscription change."
    ),
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Handle Stripe webhook events for full subscription lifecycle management.

    Events handled:
        - checkout.session.completed    → issue API key + email to customer
        - customer.subscription.deleted → deactivate API key
        - customer.subscription.updated → update plan tier on API key
    """
    if not settings.stripe_webhook_secret:
        logger.warning("Stripe webhook received but no secret configured. Ignoring.")
        return {"status": "ignored"}

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    logger.info("Stripe webhook received: %s", event["type"])

    # ── Checkout completed → Issue key and email it ──────────────────────────
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_details", {}).get("email")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        # Plan is passed as metadata on the Stripe Checkout Session
        plan = session.get("metadata", {}).get("plan", "starter")
        if plan not in ("free", "starter", "pro", "enterprise"):
            plan = "starter"

        if not email:
            logger.error(
                "Stripe checkout.session.completed missing customer email. session_id=%s",
                session.get("id"),
            )
            return {"status": "error", "detail": "missing email"}

        raw_key, key_prefix, key_hash = generate_api_key()
        monthly_quota = settings.get_monthly_quota(plan)

        new_api_key = ApiKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner_email=email,
            plan=plan,
            monthly_quota=monthly_quota,
            is_active=True,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        db.add(new_api_key)
        await db.commit()

        logger.info(
            "Issued API key %s for %s (plan=%s, customer=%s, sub=%s).",
            key_prefix,
            email,
            plan,
            customer_id,
            subscription_id,
        )

        # Email the key to the customer — this is the critical delivery step
        await send_api_key_email(email, raw_key, plan)

    # ── Subscription cancelled → Deactivate key ───────────────────────────────
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        result = await db.execute(
            select(ApiKey).where(ApiKey.stripe_customer_id == customer_id)
        )
        api_key = result.scalar_one_or_none()

        if api_key:
            api_key.is_active = False
            await db.commit()
            logger.info(
                "Deactivated API key %s for customer %s (subscription %s cancelled).",
                api_key.key_prefix,
                customer_id,
                subscription_id,
            )
        else:
            logger.warning(
                "Subscription deleted for customer %s but no matching API key found.",
                customer_id,
            )

    # ── Subscription updated → Sync plan tier ────────────────────────────────
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        # Map Stripe price ID → internal plan name
        price_id = None
        items = subscription.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")

        stripe_to_plan: dict[str, str] = {}
        if settings.stripe_monthly_price_id:
            stripe_to_plan[settings.stripe_monthly_price_id] = "starter"
        if settings.stripe_annual_price_id:
            stripe_to_plan[settings.stripe_annual_price_id] = "starter"

        new_plan = stripe_to_plan.get(str(price_id)) if price_id else None

        result = await db.execute(
            select(ApiKey).where(ApiKey.stripe_customer_id == customer_id)
        )
        api_key = result.scalar_one_or_none()

        if api_key:
            if new_plan and new_plan != api_key.plan:
                old_plan = api_key.plan
                api_key.plan = new_plan
                api_key.monthly_quota = settings.get_monthly_quota(new_plan)
                api_key.is_active = True  # Re-activate if it was paused
                await db.commit()
                logger.info(
                    "Updated plan for API key %s: %s → %s (customer %s).",
                    api_key.key_prefix,
                    old_plan,
                    new_plan,
                    customer_id,
                )
            else:
                # Subscription update for unknown price or same plan — just ensure active
                sub_status = subscription.get("status")
                if sub_status == "active" and not api_key.is_active:
                    api_key.is_active = True
                    await db.commit()
                    logger.info(
                        "Re-activated key %s for customer %s.",
                        api_key.key_prefix,
                        customer_id,
                    )
        else:
            logger.warning(
                "Subscription updated for customer %s but no matching API key found.",
                customer_id,
            )

    else:
        logger.debug("Unhandled Stripe event type: %s", event["type"])

    return {"status": "success"}
