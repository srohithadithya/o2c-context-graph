# O2C Schema Knowledge Base (`o2c_context.db`)

Source: SQLite built from `api/ingest_sqlite.py` over `data/raw/**`. Column names preserve flattened JSON (camelCase). **Date/time values are stored as ISO 8601 text** after ingestion (e.g. `2025-03-31T00:00:00.000Z`, `2025-03-31T06:42:38.786Z`). Use string comparison or SQLite `datetime()` with these literals in `WHERE` clauses.

---

## Tables and columns (exact names)

**billing_document_cancellations** — billingDocument, billingDocumentType, creationDate, lastChangeDateTime, billingDocumentDate, billingDocumentIsCancelled, cancelledBillingDocument, totalNetAmount, transactionCurrency, companyCode, fiscalYear, accountingDocument, soldToParty, creationTime_hours, creationTime_minutes, creationTime_seconds

**billing_document_headers** — billingDocument, billingDocumentType, creationDate, lastChangeDateTime, billingDocumentDate, billingDocumentIsCancelled, cancelledBillingDocument, totalNetAmount, transactionCurrency, companyCode, fiscalYear, accountingDocument, soldToParty, creationTime_hours, creationTime_minutes, creationTime_seconds

**billing_document_items** — billingDocument, billingDocumentItem, material, billingQuantity, billingQuantityUnit, netAmount, transactionCurrency, referenceSdDocument, referenceSdDocumentItem

**business_partner_addresses** — businessPartner, addressId, validityStartDate, validityEndDate, addressUuid, addressTimeZone, cityName, country, poBox, poBoxDeviatingCityName, poBoxDeviatingCountry, poBoxDeviatingRegion, poBoxIsWithoutNumber, poBoxLobbyName, poBoxPostalCode, postalCode, region, streetName, taxJurisdiction, transportZone

**business_partners** — businessPartner, customer, businessPartnerCategory, businessPartnerFullName, businessPartnerGrouping, businessPartnerName, correspondenceLanguage, createdByUser, creationDate, firstName, formOfAddress, industry, lastChangeDate, lastName, organizationBpName1, organizationBpName2, businessPartnerIsBlocked, isMarkedForArchiving, creationTime_hours, creationTime_minutes, creationTime_seconds

**customer_company_assignments** — customer, companyCode, accountingClerk, accountingClerkFaxNumber, accountingClerkInternetAddress, accountingClerkPhoneNumber, alternativePayerAccount, paymentBlockingReason, paymentMethodsList, paymentTerms, reconciliationAccount, deletionIndicator, customerAccountGroup

**customer_sales_area_assignments** — customer, salesOrganization, distributionChannel, division, billingIsBlockedForCustomer, completeDeliveryIsDefined, creditControlArea, currency, customerPaymentTerms, deliveryPriority, incotermsClassification, incotermsLocation1, salesGroup, salesOffice, shippingCondition, slsUnlmtdOvrdelivIsAllwd, supplyingPlant, salesDistrict, exchangeRateType

**journal_entry_items_accounts_receivable** — companyCode, fiscalYear, accountingDocument, glAccount, referenceDocument, costCenter, profitCenter, transactionCurrency, amountInTransactionCurrency, companyCodeCurrency, amountInCompanyCodeCurrency, postingDate, documentDate, accountingDocumentType, accountingDocumentItem, assignmentReference, lastChangeDateTime, customer, financialAccountType, clearingDate, clearingAccountingDocument, clearingDocFiscalYear

**outbound_delivery_headers** — actualGoodsMovementDate, creationDate, deliveryBlockReason, deliveryDocument, hdrGeneralIncompletionStatus, headerBillingBlockReason, lastChangeDate, overallGoodsMovementStatus, overallPickingStatus, overallProofOfDeliveryStatus, shippingPoint, actualGoodsMovementTime_hours, actualGoodsMovementTime_minutes, actualGoodsMovementTime_seconds, creationTime_hours, creationTime_minutes, creationTime_seconds

**outbound_delivery_items** — actualDeliveryQuantity, batch, deliveryDocument, deliveryDocumentItem, deliveryQuantityUnit, itemBillingBlockReason, lastChangeDate, plant, referenceSdDocument, referenceSdDocumentItem, storageLocation

**payments_accounts_receivable** — companyCode, fiscalYear, accountingDocument, accountingDocumentItem, clearingDate, clearingAccountingDocument, clearingDocFiscalYear, amountInTransactionCurrency, transactionCurrency, amountInCompanyCodeCurrency, companyCodeCurrency, customer, invoiceReference, invoiceReferenceFiscalYear, salesDocument, salesDocumentItem, postingDate, documentDate, assignmentReference, glAccount, financialAccountType, profitCenter, costCenter

**plants** — plant, plantName, valuationArea, plantCustomer, plantSupplier, factoryCalendar, defaultPurchasingOrganization, salesOrganization, addressId, plantCategory, distributionChannel, division, language, isMarkedForArchiving

**product_descriptions** — product, language, productDescription

**product_plants** — product, plant, countryOfOrigin, regionOfOrigin, productionInvtryManagedLoc, availabilityCheckType, fiscalYearVariant, profitCenter, mrpType

**product_storage_locations** — product, plant, storageLocation, physicalInventoryBlockInd, dateOfLastPostedCntUnRstrcdStk

**products** — product, productType, crossPlantStatus, crossPlantStatusValidityDate, creationDate, createdByUser, lastChangeDate, lastChangeDateTime, isMarkedForDeletion, productOldId, grossWeight, weightUnit, netWeight, productGroup, baseUnit, division, industrySector

**sales_order_headers** — salesOrder, salesOrderType, salesOrganization, distributionChannel, organizationDivision, salesGroup, salesOffice, soldToParty, creationDate, createdByUser, lastChangeDateTime, totalNetAmount, overallDeliveryStatus, overallOrdReltdBillgStatus, overallSdDocReferenceStatus, transactionCurrency, pricingDate, requestedDeliveryDate, headerBillingBlockReason, deliveryBlockReason, incotermsClassification, incotermsLocation1, customerPaymentTerms, totalCreditCheckStatus

**sales_order_items** — salesOrder, salesOrderItem, salesOrderItemCategory, material, requestedQuantity, requestedQuantityUnit, transactionCurrency, netAmount, materialGroup, productionPlant, storageLocation, salesDocumentRjcnReason, itemBillingBlockReason

**sales_order_schedule_lines** — salesOrder, salesOrderItem, scheduleLine, confirmedDeliveryDate, orderQuantityUnit, confdOrderQtyByMatlAvailCheck

---

## JOIN KEY RULES

- **sales_order_headers ↔ sales_order_items** (1:N): `sales_order_headers.salesOrder = sales_order_items.salesOrder`. Use **SalesOrder** to join headers and items.

- **sales_order_items ↔ sales_order_schedule_lines** (1:N): `salesOrder` **and** `salesOrderItem` on both sides. Schedule lines are per order line.

- **sales_order_headers ↔ sales_order_schedule_lines** (1:N): `salesOrder` only (all schedule lines for that order).

- **billing_document_headers ↔ billing_document_items** (1:N): `billingDocument` on both sides.

- **billing_document_headers ↔ billing_document_cancellations** (1:0..1): `billingDocument` (and same fiscal/accounting keys where present).

- **billing_document_items ↔ sales_order_items** (N:1): `billing_document_items.referenceSdDocument = sales_order_items.salesOrder` **and** `billing_document_items.referenceSdDocumentItem = sales_order_items.salesOrderItem` (SD reference = sales document + item).

- **billing_document_items ↔ sales_order_headers** (N:1): `referenceSdDocument = salesOrder` when only header-level join is needed.

- **outbound_delivery_headers ↔ outbound_delivery_items** (1:N): `deliveryDocument` on both sides.

- **outbound_delivery_items ↔ sales_order_items** (N:1): `referenceSdDocument = salesOrder` **and** `referenceSdDocumentItem = salesOrderItem`.

- **sales_order_headers ↔ business_partners** (N:1): `soldToParty = customer` (sold-to; in this extract `customer` aligns with partner keys).

- **business_partners ↔ business_partner_addresses** (1:N): `businessPartner` on both sides.

- **business_partners ↔ customer_company_assignments** (1:N): `customer` on both sides.

- **sales_order_headers ↔ customer_sales_area_assignments** (N:1): `soldToParty = customer`, **and** `salesOrganization`, **and** `distributionChannel`, **and** `organizationDivision = division`.

- **payments_accounts_receivable ↔ sales_order_headers** (N:1): `salesDocument = salesOrder` when the payment line references a sales order.

- **payments_accounts_receivable ↔ sales_order_items** (N:1): `salesDocument = salesOrder` **and** `salesDocumentItem = salesOrderItem` when item is populated.

- **payments_accounts_receivable ↔ journal_entry_items_accounts_receivable** (N:1): `companyCode`, `fiscalYear`, `accountingDocument`, and usually `customer` for line-level AR.

- **billing_document_headers ↔ journal_entry_items_accounts_receivable** (1:N): `companyCode`, `fiscalYear`, `accountingDocument`.

- **sales_order_items ↔ products** (N:1): `material = product`.

- **products ↔ product_descriptions** (1:N): `product` (add `language` filter when needed).

- **products ↔ product_plants** (1:N): `product`.

- **product_plants ↔ plants** (N:1): `plant`.

- **products ↔ product_storage_locations** (1:N): `product` (also `plant`, `storageLocation` for a specific bin).

- **sales_order_items ↔ plants** (N:1): `productionPlant = plant`.

- **outbound_delivery_items ↔ plants** (N:1): `plant = plant`.

---

## Date / time columns (ISO 8601 text in SQLite)

| Table | Date-like columns | Format |
| --- | --- | --- |
| billing_document_* | creationDate, lastChangeDateTime, billingDocumentDate | ISO 8601 UTC (`...Z`) |
| business_partner_addresses | validityStartDate, validityEndDate | ISO 8601 UTC |
| business_partners | creationDate, lastChangeDate | ISO 8601 UTC |
| journal_entry_items_accounts_receivable | postingDate, documentDate, lastChangeDateTime, clearingDate | ISO 8601 UTC |
| outbound_delivery_headers | actualGoodsMovementDate, creationDate, lastChangeDate | ISO 8601 UTC |
| outbound_delivery_items | lastChangeDate | ISO 8601 UTC |
| payments_accounts_receivable | clearingDate, postingDate, documentDate | ISO 8601 UTC |
| product_storage_locations | dateOfLastPostedCntUnRstrcdStk | ISO 8601 UTC |
| products | creationDate, lastChangeDate, lastChangeDateTime, crossPlantStatusValidityDate | ISO 8601 UTC |
| sales_order_headers | creationDate, lastChangeDateTime, pricingDate, requestedDeliveryDate | ISO 8601 UTC |
| sales_order_schedule_lines | confirmedDeliveryDate | ISO 8601 UTC |

**Note:** Nested JSON times (e.g. `creationTime` objects) were flattened to `creationTime_hours`, `creationTime_minutes`, `creationTime_seconds` on some tables; combine with `creationDate` in the app layer if a full timestamp is required.

---