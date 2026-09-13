"""Add stripe_customer_id and stripe_subscription_id to api_keys

Revision ID: 001
Revises:
Create Date: 2026-09-13

These columns link each API key to its Stripe subscription so that
subscription lifecycle events (cancellation, plan changes) can automatically
activate/deactivate/upgrade the corresponding API key.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add stripe_customer_id column with an index for fast lookup in webhooks
    op.add_column(
        "api_keys",
        sa.Column(
            "stripe_customer_id",
            sa.String(64),
            nullable=True,
            comment="Stripe customer ID (cus_...) for subscription lifecycle events",
        ),
    )
    op.create_index(
        "ix_api_keys_stripe_customer_id",
        "api_keys",
        ["stripe_customer_id"],
        unique=False,
    )

    # Add stripe_subscription_id column
    op.add_column(
        "api_keys",
        sa.Column(
            "stripe_subscription_id",
            sa.String(64),
            nullable=True,
            comment="Stripe subscription ID (sub_...) for plan change tracking",
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_stripe_customer_id", table_name="api_keys")
    op.drop_column("api_keys", "stripe_customer_id")
    op.drop_column("api_keys", "stripe_subscription_id")
