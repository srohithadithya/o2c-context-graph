"""
O2C SQLite — explicit join graph for the 19 ingested entity tables.

Use these rules in LLM prompts and application SQL to avoid Cartesian products
and wrong joins. Column names match flattened JSONL → SQLite (camelCase).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JoinPredicate:
    """One equality predicate between two tables."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str


@dataclass(frozen=True)
class JoinPath:
    """A documented way to relate two tables (often 1:N)."""

    id: str
    left_table: str
    right_table: str
    predicates: tuple[JoinPredicate, ...]
    cardinality: str
    notes: str


# All 19 entity table names (must match ingest_sqlite ENTITY_FOLDERS / SQLite names).
O2C_TABLE_NAMES: tuple[str, ...] = (
    "billing_document_cancellations",
    "billing_document_headers",
    "billing_document_items",
    "business_partners",
    "business_partner_addresses",
    "customer_company_assignments",
    "customer_sales_area_assignments",
    "journal_entry_items_accounts_receivable",
    "outbound_delivery_headers",
    "outbound_delivery_items",
    "payments_accounts_receivable",
    "plants",
    "products",
    "product_descriptions",
    "product_plants",
    "product_storage_locations",
    "sales_order_headers",
    "sales_order_items",
    "sales_order_schedule_lines",
)


def P(
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
) -> JoinPredicate:
    return JoinPredicate(left_table, left_column, right_table, right_column)


# Primary documented join paths (SAP O2C semantics + actual column names in o2c_context.db).
O2C_JOIN_PATHS: tuple[JoinPath, ...] = (
    JoinPath(
        "so_header_item",
        "sales_order_headers",
        "sales_order_items",
        (P("sales_order_headers", "salesOrder", "sales_order_items", "salesOrder"),),
        "1:N",
        "Use SalesOrder to join sales_order_headers and sales_order_items.",
    ),
    JoinPath(
        "so_item_schedule",
        "sales_order_items",
        "sales_order_schedule_lines",
        (
            P("sales_order_items", "salesOrder", "sales_order_schedule_lines", "salesOrder"),
            P("sales_order_items", "salesOrderItem", "sales_order_schedule_lines", "salesOrderItem"),
        ),
        "1:N",
        "Schedule lines are per order item: join on SalesOrder + SalesOrderItem.",
    ),
    JoinPath(
        "so_header_schedule",
        "sales_order_headers",
        "sales_order_schedule_lines",
        (P("sales_order_headers", "salesOrder", "sales_order_schedule_lines", "salesOrder"),),
        "1:N",
        "Header to all schedule lines for the order (only SalesOrder).",
    ),
    JoinPath(
        "bd_header_item",
        "billing_document_headers",
        "billing_document_items",
        (P("billing_document_headers", "billingDocument", "billing_document_items", "billingDocument"),),
        "1:N",
        "Use BillingDocument to join billing_document_headers and billing_document_items.",
    ),
    JoinPath(
        "bd_header_cancellation",
        "billing_document_headers",
        "billing_document_cancellations",
        (
            P("billing_document_headers", "billingDocument", "billing_document_cancellations", "billingDocument"),
        ),
        "1:0..1",
        "Cancellations share the same billing document key.",
    ),
    JoinPath(
        "bd_item_to_so",
        "billing_document_items",
        "sales_order_items",
        (
            P("billing_document_items", "referenceSdDocument", "sales_order_items", "salesOrder"),
            P(
                "billing_document_items",
                "referenceSdDocumentItem",
                "sales_order_items",
                "salesOrderItem",
            ),
        ),
        "N:1",
        "Billing line references SD document: ReferenceSdDocument = SalesOrder, ReferenceSdDocumentItem = SalesOrderItem.",
    ),
    JoinPath(
        "bd_item_to_so_header",
        "billing_document_items",
        "sales_order_headers",
        (P("billing_document_items", "referenceSdDocument", "sales_order_headers", "salesOrder"),),
        "N:1",
        "When only header-level link is needed: ReferenceSdDocument = SalesOrder.",
    ),
    JoinPath(
        "od_header_item",
        "outbound_delivery_headers",
        "outbound_delivery_items",
        (P("outbound_delivery_headers", "deliveryDocument", "outbound_delivery_items", "deliveryDocument"),),
        "1:N",
        "Use DeliveryDocument to join outbound_delivery_headers and outbound_delivery_items.",
    ),
    JoinPath(
        "od_item_to_so",
        "outbound_delivery_items",
        "sales_order_items",
        (
            P("outbound_delivery_items", "referenceSdDocument", "sales_order_items", "salesOrder"),
            P(
                "outbound_delivery_items",
                "referenceSdDocumentItem",
                "sales_order_items",
                "salesOrderItem",
            ),
        ),
        "N:1",
        "Delivery item references sales order line via ReferenceSdDocument / ReferenceSdDocumentItem.",
    ),
    JoinPath(
        "sold_to_partner",
        "sales_order_headers",
        "business_partners",
        (P("sales_order_headers", "soldToParty", "business_partners", "customer"),),
        "N:1",
        "Sold-to party: SoldToParty = Customer (and typically BusinessPartner in this extract).",
    ),
    JoinPath(
        "partner_address",
        "business_partners",
        "business_partner_addresses",
        (P("business_partners", "businessPartner", "business_partner_addresses", "businessPartner"),),
        "1:N",
        "Addresses are keyed by BusinessPartner.",
    ),
    JoinPath(
        "customer_company",
        "business_partners",
        "customer_company_assignments",
        (P("business_partners", "customer", "customer_company_assignments", "customer"),),
        "1:N",
        "Company assignments use Customer.",
    ),
    JoinPath(
        "customer_sales_area",
        "sales_order_headers",
        "customer_sales_area_assignments",
        (
            P("sales_order_headers", "soldToParty", "customer_sales_area_assignments", "customer"),
            P(
                "sales_order_headers",
                "salesOrganization",
                "customer_sales_area_assignments",
                "salesOrganization",
            ),
            P(
                "sales_order_headers",
                "distributionChannel",
                "customer_sales_area_assignments",
                "distributionChannel",
            ),
            P(
                "sales_order_headers",
                "organizationDivision",
                "customer_sales_area_assignments",
                "division",
            ),
        ),
        "N:1",
        "Sales-area data: match Customer + SalesOrganization + DistributionChannel + Division (header OrganizationDivision = assignments Division).",
    ),
    JoinPath(
        "payments_to_so",
        "payments_accounts_receivable",
        "sales_order_headers",
        (P("payments_accounts_receivable", "salesDocument", "sales_order_headers", "salesOrder"),),
        "N:1",
        "AR payment lines often carry SalesDocument = Sales Order number.",
    ),
    JoinPath(
        "payments_to_so_item",
        "payments_accounts_receivable",
        "sales_order_items",
        (
            P("payments_accounts_receivable", "salesDocument", "sales_order_items", "salesOrder"),
            P("payments_accounts_receivable", "salesDocumentItem", "sales_order_items", "salesOrderItem"),
        ),
        "N:1",
        "When SalesDocumentItem is populated, join to both SalesOrder and SalesOrderItem.",
    ),
    JoinPath(
        "payments_to_journal",
        "payments_accounts_receivable",
        "journal_entry_items_accounts_receivable",
        (
            P("payments_accounts_receivable", "companyCode", "journal_entry_items_accounts_receivable", "companyCode"),
            P("payments_accounts_receivable", "fiscalYear", "journal_entry_items_accounts_receivable", "fiscalYear"),
            P(
                "payments_accounts_receivable",
                "accountingDocument",
                "journal_entry_items_accounts_receivable",
                "accountingDocument",
            ),
            P(
                "payments_accounts_receivable",
                "customer",
                "journal_entry_items_accounts_receivable",
                "customer",
            ),
        ),
        "N:1",
        "Join FI AR journal lines on CompanyCode + FiscalYear + AccountingDocument; add Customer when line-level match is required.",
    ),
    JoinPath(
        "billing_header_to_journal",
        "billing_document_headers",
        "journal_entry_items_accounts_receivable",
        (
            P("billing_document_headers", "companyCode", "journal_entry_items_accounts_receivable", "companyCode"),
            P("billing_document_headers", "fiscalYear", "journal_entry_items_accounts_receivable", "fiscalYear"),
            P(
                "billing_document_headers",
                "accountingDocument",
                "journal_entry_items_accounts_receivable",
                "accountingDocument",
            ),
        ),
        "1:N",
        "Billing posts to accounting: CompanyCode + FiscalYear + AccountingDocument.",
    ),
    JoinPath(
        "so_item_material_product",
        "sales_order_items",
        "products",
        (P("sales_order_items", "material", "products", "product"),),
        "N:1",
        "Material master: Material = Product.",
    ),
    JoinPath(
        "product_description",
        "products",
        "product_descriptions",
        (P("products", "product", "product_descriptions", "product"),),
        "1:N",
        "Descriptions are per Product (+ Language).",
    ),
    JoinPath(
        "product_plant",
        "products",
        "product_plants",
        (P("products", "product", "product_plants", "product"),),
        "1:N",
        "Plant-specific product data.",
    ),
    JoinPath(
        "product_plant_to_plant",
        "product_plants",
        "plants",
        (P("product_plants", "plant", "plants", "plant"),),
        "N:1",
        "Plant master.",
    ),
    JoinPath(
        "product_storage_loc",
        "products",
        "product_storage_locations",
        (P("products", "product", "product_storage_locations", "product"),),
        "1:N",
        "Storage location rows include Plant + StorageLocation.",
    ),
    JoinPath(
        "so_item_to_plant",
        "sales_order_items",
        "plants",
        (P("sales_order_items", "productionPlant", "plants", "plant"),),
        "N:1",
        "Production plant on item → Plant.",
    ),
    JoinPath(
        "od_item_to_plant",
        "outbound_delivery_items",
        "plants",
        (P("outbound_delivery_items", "plant", "plants", "plant"),),
        "N:1",
        "Delivery item issuing plant.",
    ),
)


def join_paths_as_dicts() -> list[dict[str, Any]]:
    """Serializable join catalog for APIs and prompts."""
    out: list[dict[str, Any]] = []
    for jp in O2C_JOIN_PATHS:
        out.append(
            {
                "id": jp.id,
                "left_table": jp.left_table,
                "right_table": jp.right_table,
                "cardinality": jp.cardinality,
                "notes": jp.notes,
                "predicates": [
                    {
                        "left_table": p.left_table,
                        "left_column": p.left_column,
                        "right_table": p.right_table,
                        "right_column": p.right_column,
                    }
                    for p in jp.predicates
                ],
            }
        )
    return out


def join_hints_markdown() -> str:
    """Dense bullet list for system prompts."""
    lines: list[str] = []
    for jp in O2C_JOIN_PATHS:
        preds = " AND ".join(
            f"{p.left_table}.{p.left_column} = {p.right_table}.{p.right_column}"
            for p in jp.predicates
        )
        lines.append(f"- **{jp.left_table}** ↔ **{jp.right_table}** ({jp.cardinality}): {preds}. {jp.notes}")
    return "\n".join(lines)
