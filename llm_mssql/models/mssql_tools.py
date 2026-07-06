import logging

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

from .mssql_client import MssqlClient

_logger = logging.getLogger(__name__)


class LlmMssqlTools(models.AbstractModel):
    _name = "llm.mssql.tools"
    _description = "MSSQL MCP Tools"

    # ─── Customers ────────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_search_customers(self, query: str, limit: int = 20) -> list:
        """Search Sage 500 customers by name or customer number.

        Returns a list of matching customers with their key details.
        Use this to find customers before retrieving full records.
        """
        client = MssqlClient(self.env)
        return client.query(
            "SELECT TOP (?) CustomerNo, CustomerName, City, State, "
            "TelephoneNo, EmailAddress, CreditLimit "
            "FROM AR_Customer "
            "WHERE CustomerName LIKE ? OR CustomerNo LIKE ? "
            "ORDER BY CustomerName",
            (limit, f"%{query}%", f"%{query}%"),
        )

    @llm_tool(read_only_hint=True)
    def mssql_list_customers(
        self,
        limit: int = 50,
        offset: int = 0,
        state: str = "",
        credit_hold: str = "",
        customer_no_gt: str = "",
    ) -> list:
        """List Sage 500 customers with pagination and optional filters.

        Returns customer headers (same shape as mssql_search_customers).
        Use mssql_get_customer for full address/terms detail.

        Pagination: increment offset by limit each call.
        Incremental sync: pass customer_no_gt=<last CustomerNo seen> to fetch
        only new records — more efficient than offset for large tables.
        A returned row count equal to limit signals more pages likely exist.
        """
        client = MssqlClient(self.env)
        where_parts = []
        params: list = []

        if state:
            where_parts.append("State = ?")
            params.append(state)
        if credit_hold:
            where_parts.append("CreditHold = ?")
            params.append(credit_hold)
        if customer_no_gt:
            where_parts.append("CustomerNo > ?")
            params.append(customer_no_gt)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        params += [offset, limit]
        return client.query(
            f"SELECT CustomerNo, CustomerName, City, State, "
            f"TelephoneNo, EmailAddress, CreditLimit "
            f"FROM AR_Customer "
            f"{where_clause} "
            f"ORDER BY CustomerNo "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            tuple(params),
        )

    @llm_tool(read_only_hint=True)
    def mssql_get_customer(self, customer_no: str) -> dict:
        """Get full details for a single Sage 500 customer by customer number.

        Returns all customer fields including address, credit terms, and limits.
        """
        client = MssqlClient(self.env)
        rows = client.query(
            "SELECT CustomerNo, CustomerName, AddressLine1, AddressLine2, "
            "City, State, ZipCode, CountryCode, TelephoneNo, FaxNo, "
            "EmailAddress, TermsCode, CreditLimit, CreditHold "
            "FROM AR_Customer WHERE CustomerNo = ?",
            (customer_no,),
        )
        return rows[0] if rows else {}

    @llm_tool(destructive_hint=False)
    def mssql_create_customer(
        self,
        customer_no: str,
        customer_name: str,
        address_line1: str,
        city: str,
        state: str,
        zip_code: str,
        telephone_no: str,
        email_address: str,
        credit_limit: float,
        terms_code: str,
    ) -> dict:
        """Create a new customer record in Sage 500 AR_Customer table.

        Note: This inserts directly into the SQL table. If the Sage 500 instance
        uses stored procedures for customer creation, coordinate with the system
        admin to use the appropriate stored procedure instead.

        Returns the number of rows affected.
        """
        client = MssqlClient(self.env)
        rows_affected = client.execute(
            "INSERT INTO AR_Customer "
            "(CustomerNo, CustomerName, AddressLine1, City, State, ZipCode, "
            "TelephoneNo, EmailAddress, CreditLimit, TermsCode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                customer_no,
                customer_name,
                address_line1,
                city,
                state,
                zip_code,
                telephone_no,
                email_address,
                credit_limit,
                terms_code,
            ),
        )
        return {"rows_affected": rows_affected, "customer_no": customer_no}

    @llm_tool(destructive_hint=False)
    def mssql_update_customer(
        self,
        customer_no: str,
        customer_name: str,
        city: str,
        state: str,
        telephone_no: str,
        email_address: str,
        credit_limit: float,
    ) -> dict:
        """Update an existing Sage 500 customer's core fields.

        Only updates the fields provided. Returns rows affected (0 = not found).
        """
        client = MssqlClient(self.env)
        rows_affected = client.execute(
            "UPDATE AR_Customer SET "
            "CustomerName=?, City=?, State=?, TelephoneNo=?, "
            "EmailAddress=?, CreditLimit=? "
            "WHERE CustomerNo=?",
            (
                customer_name,
                city,
                state,
                telephone_no,
                email_address,
                credit_limit,
                customer_no,
            ),
        )
        return {"rows_affected": rows_affected, "customer_no": customer_no}

    # ─── Vendors ──────────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_search_vendors(self, query: str, limit: int = 20) -> list:
        """Search Sage 500 vendors by name or vendor number.

        Returns matching vendors with contact and terms information.
        """
        client = MssqlClient(self.env)
        return client.query(
            "SELECT TOP (?) VendorNo, VendorName, City, State, "
            "TelephoneNo, EmailAddress, TermsCode "
            "FROM AP_Vendor "
            "WHERE VendorName LIKE ? OR VendorNo LIKE ? "
            "ORDER BY VendorName",
            (limit, f"%{query}%", f"%{query}%"),
        )

    @llm_tool(read_only_hint=True)
    def mssql_list_vendors(
        self,
        limit: int = 50,
        offset: int = 0,
        terms_code: str = "",
        vendor_no_gt: str = "",
    ) -> list:
        """List Sage 500 vendors with pagination and optional filters.

        Returns vendor headers (same shape as mssql_search_vendors).
        Use mssql_get_vendor for full address/terms detail.

        Pagination: increment offset by limit each call.
        Incremental sync: pass vendor_no_gt=<last VendorNo seen> to fetch
        only new records without re-pulling the whole table.
        A returned row count equal to limit signals more pages likely exist.
        """
        client = MssqlClient(self.env)
        where_parts = []
        params: list = []

        if terms_code:
            where_parts.append("TermsCode = ?")
            params.append(terms_code)
        if vendor_no_gt:
            where_parts.append("VendorNo > ?")
            params.append(vendor_no_gt)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        params += [offset, limit]
        return client.query(
            f"SELECT VendorNo, VendorName, City, State, "
            f"TelephoneNo, EmailAddress, TermsCode "
            f"FROM AP_Vendor "
            f"{where_clause} "
            f"ORDER BY VendorNo "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            tuple(params),
        )

    @llm_tool(read_only_hint=True)
    def mssql_get_vendor(self, vendor_no: str) -> dict:
        """Get full details for a single Sage 500 vendor by vendor number.

        Returns all vendor fields including address and payment terms.
        """
        client = MssqlClient(self.env)
        rows = client.query(
            "SELECT VendorNo, VendorName, AddressLine1, AddressLine2, "
            "City, State, ZipCode, CountryCode, TelephoneNo, FaxNo, "
            "EmailAddress, TermsCode "
            "FROM AP_Vendor WHERE VendorNo = ?",
            (vendor_no,),
        )
        return rows[0] if rows else {}

    # ─── Sales Orders ─────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_list_sales_orders(
        self, customer_no: str = "", limit: int = 50, status: str = ""
    ) -> list:
        """List Sage 500 sales orders, optionally filtered by customer or status.

        status values: 'Open', 'Closed', 'Cancelled' (leave empty for all).
        Returns order headers with totals — use mssql_get_sales_order for lines.
        """
        client = MssqlClient(self.env)
        where_parts = []
        params: list = [limit]

        if customer_no:
            where_parts.append("h.CustomerNo = ?")
            params.append(customer_no)
        if status:
            where_parts.append("h.OrderStatus = ?")
            params.append(status)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        return client.query(
            f"SELECT TOP (?) h.SalesOrderNo, h.CustomerNo, h.OrderDate, "
            f"h.OrderStatus, h.ShipToName, h.OrderTotal "
            f"FROM SO_SalesOrder h "
            f"{where_clause} "
            f"ORDER BY h.OrderDate DESC",
            tuple(params),
        )

    @llm_tool(read_only_hint=True)
    def mssql_get_sales_order(self, sales_order_no: str) -> dict:
        """Get a Sage 500 sales order with all its line items.

        Returns the order header merged with a 'lines' list containing each
        product, quantity, unit price, and extended price.
        """
        client = MssqlClient(self.env)
        headers = client.query(
            "SELECT SalesOrderNo, CustomerNo, OrderDate, OrderStatus, "
            "ShipToName, OrderTotal "
            "FROM SO_SalesOrder WHERE SalesOrderNo = ?",
            (sales_order_no,),
        )
        if not headers:
            return {}
        result = headers[0]
        result["lines"] = client.query(
            "SELECT [LineNo], ItemCode, ItemDescription, UnitOfMeasure, "
            "QuantityOrdered, UnitPrice, ExtendedPrice "
            "FROM SO_SalesOrderDetail WHERE SalesOrderNo = ? ORDER BY [LineNo]",
            (sales_order_no,),
        )
        return result

    @llm_tool(destructive_hint=False)
    def mssql_create_sales_order(
        self,
        customer_no: str,
        ship_to_name: str,
        order_date: str,
        items: list,
    ) -> dict:
        """Create a Sage 500 sales order with line items.

        items should be a list of dicts with keys:
          item_code (str), quantity (float), unit_price (float)

        order_date format: YYYY-MM-DD

        Returns the created SalesOrderNo.
        """
        client = MssqlClient(self.env)
        seq_rows = client.query(
            "SELECT ISNULL(MAX(CAST(SalesOrderNo AS INT)), 0) + 1 AS NextNo "
            "FROM SO_SalesOrder WHERE SalesOrderNo NOT LIKE '%[^0-9]%'"
        )
        sales_order_no = str(seq_rows[0]["NextNo"]).zfill(7) if seq_rows else "0000001"

        order_total = sum(
            item.get("quantity", 0) * item.get("unit_price", 0) for item in items
        )
        client.execute(
            "INSERT INTO SO_SalesOrder "
            "(SalesOrderNo, CustomerNo, OrderDate, ShipToName, OrderStatus, OrderTotal) "
            "VALUES (?, ?, ?, ?, 'Open', ?)",
            (sales_order_no, customer_no, order_date, ship_to_name, order_total),
        )
        for i, item in enumerate(items, start=1):
            extended = item.get("quantity", 0) * item.get("unit_price", 0)
            client.execute(
                "INSERT INTO SO_SalesOrderDetail "
                "(SalesOrderNo, [LineNo], ItemCode, QuantityOrdered, UnitPrice, ExtendedPrice) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sales_order_no,
                    i,
                    item.get("item_code", ""),
                    item.get("quantity", 0),
                    item.get("unit_price", 0),
                    extended,
                ),
            )
        return {"sales_order_no": sales_order_no, "order_total": order_total}

    # ─── AR Invoices ──────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_list_ar_invoices(
        self, customer_no: str = "", limit: int = 50, overdue_only: bool = False
    ) -> list:
        """List Sage 500 open AR invoices, optionally filtered by customer.

        Set overdue_only=true to return only invoices past their due date.
        Returns invoice number, amount due, due date, and days overdue.
        """
        client = MssqlClient(self.env)
        where_parts = []
        params: list = [limit]

        if customer_no:
            where_parts.append("CustomerNo = ?")
            params.append(customer_no)
        if overdue_only:
            where_parts.append("DueDate < GETDATE()")

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        return client.query(
            f"SELECT TOP (?) InvoiceNo, CustomerNo, InvoiceDate, DueDate, "
            f"InvoiceAmt, AmtDue, "
            f"DATEDIFF(day, DueDate, GETDATE()) AS DaysOverdue "
            f"FROM AR_OpenInvoice "
            f"{where_clause} "
            f"ORDER BY DueDate",
            tuple(params),
        )

    @llm_tool(read_only_hint=True)
    def mssql_get_ar_invoice(self, invoice_no: str) -> dict:
        """Get full details of a Sage 500 AR invoice by invoice number.

        Returns header fields from AR_OpenInvoice including all amounts and dates.
        """
        client = MssqlClient(self.env)
        rows = client.query(
            "SELECT InvoiceNo, CustomerNo, InvoiceDate, DueDate, "
            "InvoiceAmt, AmtDue, InvoiceType, TermsCode "
            "FROM AR_OpenInvoice WHERE InvoiceNo = ?",
            (invoice_no,),
        )
        return rows[0] if rows else {}

    # ─── Purchase Orders ──────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_list_purchase_orders(
        self, vendor_no: str = "", limit: int = 50
    ) -> list:
        """List Sage 500 purchase orders, optionally filtered by vendor.

        Returns PO headers with totals.
        Use mssql_get_purchase_order to retrieve individual line items.
        """
        client = MssqlClient(self.env)
        where_clause = "WHERE h.VendorNo = ?" if vendor_no else ""
        params: tuple = (limit, vendor_no) if vendor_no else (limit,)
        return client.query(
            f"SELECT TOP (?) h.PurchaseOrderNo, h.VendorNo, h.OrderDate, "
            f"h.OrderStatus, h.OrderTotal "
            f"FROM PO_PurchaseOrder h "
            f"{where_clause} "
            f"ORDER BY h.OrderDate DESC",
            params,
        )

    @llm_tool(read_only_hint=True)
    def mssql_get_purchase_order(self, purchase_order_no: str) -> dict:
        """Get a Sage 500 purchase order with its line items.

        Returns header and a 'lines' list with item, quantity, and price details.
        """
        client = MssqlClient(self.env)
        headers = client.query(
            "SELECT PurchaseOrderNo, VendorNo, OrderDate, OrderStatus, OrderTotal "
            "FROM PO_PurchaseOrder WHERE PurchaseOrderNo = ?",
            (purchase_order_no,),
        )
        if not headers:
            return {}
        result = headers[0]
        result["lines"] = client.query(
            "SELECT [LineNo], ItemCode, ItemDescription, UnitOfMeasure, "
            "QuantityOrdered, UnitCost, ExtendedCost "
            "FROM PO_PurchaseOrderDetail WHERE PurchaseOrderNo = ? ORDER BY [LineNo]",
            (purchase_order_no,),
        )
        return result

    # ─── Inventory ────────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_search_inventory(self, query: str, limit: int = 30) -> list:
        """Search Sage 500 inventory items by item code or description.

        Returns items with standard cost, price, and quantity on hand.
        """
        client = MssqlClient(self.env)
        return client.query(
            "SELECT TOP (?) ItemCode, ItemCodeDesc, ProductLine, "
            "StandardCost, StandardPrice, QuantityOnHand "
            "FROM CI_Item "
            "WHERE ItemCode LIKE ? OR ItemCodeDesc LIKE ? "
            "ORDER BY ItemCode",
            (limit, f"%{query}%", f"%{query}%"),
        )

    # ─── GL Accounts ──────────────────────────────────────────────────────────

    @llm_tool(read_only_hint=True)
    def mssql_list_gl_accounts(
        self, account_type: str = "", limit: int = 100
    ) -> list:
        """List Sage 500 general ledger accounts.

        account_type: 'A' (asset), 'L' (liability), 'E' (equity),
                      'R' (revenue), 'X' (expense) — leave empty for all.
        """
        client = MssqlClient(self.env)
        where_clause = "WHERE AccountType = ?" if account_type else ""
        params: tuple = (limit, account_type) if account_type else (limit,)
        return client.query(
            f"SELECT TOP (?) AccountNo, AccountDesc, AccountType, GLDivisionNo "
            f"FROM GL_Account "
            f"{where_clause} "
            f"ORDER BY AccountNo",
            params,
        )
