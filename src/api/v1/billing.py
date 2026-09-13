"""
Billing API endpoints — public, no auth required.

Provides self-serve Stripe Checkout for jewellery websites and other
subscribers to purchase an API key without admin intervention.
"""

import logging

import stripe
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

# ── Plan catalogue — single source of truth shown to customers ──────────────
PLANS = [
    {
        "plan": "free",
        "label": "Free Trial",
        "price_monthly_usd": 0,
        "price_annual_usd": 0,
        "monthly_quota": 200,
        "rate_limit_per_minute": 5,
        "features": [
            "200 API requests/month",
            "Latest gold & silver prices",
            "All karats (22k, 21k, 18k, Sanaton)",
            "No credit card required",
        ],
        "available": True,
    },
    {
        "plan": "starter",
        "label": "Starter",
        "price_monthly_usd": 6,
        "price_annual_usd": 60,
        "monthly_quota": 10_000,
        "rate_limit_per_minute": 30,
        "features": [
            "10,000 API requests/month",
            "Latest prices + unit conversion",
            "Price history endpoint",
            "30 requests/minute burst limit",
            "Email support",
        ],
        "available": True,
        "popular": True,
    },
    {
        "plan": "pro",
        "label": "Pro",
        "price_monthly_usd": 25,
        "price_annual_usd": 240,
        "monthly_quota": 100_000,
        "rate_limit_per_minute": 120,
        "features": [
            "100,000 API requests/month",
            "All Starter features",
            "Near-real-time refresh priority",
            "120 requests/minute burst limit",
            "Priority email support",
        ],
        "available": True,
    },
]


class CheckoutRequest(BaseModel):
    """Request body for creating a Stripe Checkout Session."""

    email: str = Field(
        description="Customer's email address — API key will be sent here."
    )
    plan: str = Field(
        default="starter", description="Plan to subscribe to: 'starter' or 'pro'"
    )
    billing_cycle: str = Field(
        default="monthly",
        description="Billing frequency: 'monthly' (USD 6) or 'annual' (USD 60)",
    )


class CheckoutResponse(BaseModel):
    """Response with the Stripe-hosted checkout URL."""

    checkout_url: str = Field(
        description="Redirect the customer to this URL to complete payment."
    )
    plan: str
    billing_cycle: str


@router.get(
    "/plans",
    summary="List available plans",
    description=(
        "Public endpoint — returns all available subscription plans with pricing. "
        "Use this to populate a pricing page on your jewellery website."
    ),
)
async def list_plans() -> list[dict]:
    """Return all available plans and their pricing in USD."""
    return PLANS


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Checkout Session",
    description=(
        "Creates a Stripe-hosted checkout session. Redirect your customer to "
        "`checkout_url`. On successful payment, Stripe calls the webhook which "
        "automatically issues and emails an API key."
    ),
)
async def create_checkout(body: CheckoutRequest) -> CheckoutResponse:
    """
    Create a Stripe Checkout Session for a subscription purchase.

    The API key is issued automatically via the Stripe webhook after payment.
    The key is emailed to the customer — no admin action required.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured. Please contact support.",
        )

    valid_plans = ("starter", "pro")
    if body.plan not in valid_plans:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plan '{body.plan}' is not available for checkout. Choose from: {', '.join(valid_plans)}",
        )

    if body.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="billing_cycle must be 'monthly' or 'annual'.",
        )

    # Determine the Stripe Price ID based on plan + billing cycle
    # For now we support starter plan. Pro can be added by extending the mapping.
    price_id_map: dict[tuple[str, str], str] = {}

    if settings.stripe_monthly_price_id:
        price_id_map[("starter", "monthly")] = settings.stripe_monthly_price_id
    if settings.stripe_annual_price_id:
        price_id_map[("starter", "annual")] = settings.stripe_annual_price_id

    price_id = price_id_map.get((body.plan, body.billing_cycle))

    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Payment for {body.plan}/{body.billing_cycle} is not yet configured. "
                "Please contact support."
            ),
        )

    stripe.api_key = settings.stripe_secret_key

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=body.email,
            line_items=[{"price": price_id, "quantity": 1}],
            # Pass plan name so the webhook knows which plan to assign
            metadata={"plan": body.plan},
            # Redirect URLs — customize to your actual domain
            success_url="https://api.bajusprices.com/billing/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://api.bajusprices.com/billing/cancel",
            # Automatically collect billing address and tax
            billing_address_collection="auto",
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe Checkout Session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment gateway error: {exc.user_message or str(exc)}",
        )

    logger.info(
        "Checkout session created for %s (plan=%s, cycle=%s, session=%s).",
        body.email,
        body.plan,
        body.billing_cycle,
        session.id,
    )

    return CheckoutResponse(
        checkout_url=session.url or "",
        plan=body.plan,
        billing_cycle=body.billing_cycle,
    )


@router.get(
    "/success",
    summary="Payment success landing page",
    description="Customer lands here after completing Stripe Checkout. Instructs them to check email.",
    include_in_schema=False,
)
async def checkout_success(session_id: str | None = None) -> dict:
    """Stripe redirects here after successful payment."""
    return {
        "status": "success",
        "message": (
            "Payment complete! Your API key has been emailed to you. "
            "Please check your inbox (and spam folder). "
            "If you don't receive it within 5 minutes, contact support."
        ),
    }


@router.get(
    "/cancel",
    summary="Payment cancelled landing page",
    include_in_schema=False,
)
async def checkout_cancel() -> dict:
    """Stripe redirects here if the customer cancels checkout."""
    return {
        "status": "cancelled",
        "message": "Checkout was cancelled. No charge was made. You can try again anytime.",
    }
