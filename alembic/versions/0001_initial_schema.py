"""Initial schema: customers, invoices, payments, sync_logs"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop enums first if they exist from a previous partial run, then recreate.
    # This is safe because downgrade() also drops them.
    # We use raw SQL with DO $$ blocks — works in both online and offline mode,
    # and avoids the asyncpg "IF NOT EXISTS" prepared-statement restriction.
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE invoice_status AS ENUM (
                'draft', 'issued', 'partially_paid', 'paid', 'overdue', 'voided'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE sync_status AS ENUM ('success', 'partial', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(15, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_customers_external_id", "customers", ["external_id"], unique=True)

    # --- invoices ---
    # create_type=False: type already created above via DO $$ block
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "issued", "partially_paid", "paid", "overdue", "voided",
                name="invoice_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(15, 2), nullable=False, server_default="0.00"),
        sa.Column("outstanding_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_invoices_external_id", "invoices", ["external_id"], unique=True)
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_due_date", "invoices", ["due_date"])
    op.create_index("ix_invoices_customer_status", "invoices", ["customer_id", "status"])
    op.create_index("ix_invoices_due_date_status", "invoices", ["due_date", "status"])

    # --- payments ---
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(100), nullable=True),
        sa.Column("reference_number", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_payments_external_id", "payments", ["external_id"], unique=True)
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("ix_payments_payment_date", "payments", ["payment_date"])

    # --- sync_logs ---
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sync_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "success", "partial", "failed",
                name="sync_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customers_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoices_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payments_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sync_logs")
    op.drop_table("payments")
    op.drop_table("invoices")
    op.drop_table("customers")
    op.execute(sa.text("DROP TYPE IF EXISTS invoice_status"))
    op.execute(sa.text("DROP TYPE IF EXISTS sync_status"))
