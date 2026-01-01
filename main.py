import os
import json
import asyncio
import sqlite3
import aiosqlite
from typing import List, Dict, Optional, Any
from datetime import datetime
from fastmcp import FastMCP

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "expenses.db")
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")

mcp = FastMCP(name="Expense Tracker")

# ────────────────────────────────────────────────
# SYNCHRONOUS DATABASE INITIALIZATION
# (The safest way with current fastmcp versions)
# ────────────────────────────────────────────────

def init_db_sync():
    """Create the expenses table if it doesn't exist"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,               -- format: YYYY-MM-DD
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime')),
            amount      REAL  NOT NULL CHECK(amount >= 0),
            currency    TEXT  DEFAULT 'USD' CHECK(length(currency) = 3),
            category    TEXT  NOT NULL,
            subcategory TEXT,
            payment_method TEXT,
            merchant    TEXT,
            notes       TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);")
        conn.commit()

# Execute initialization once when module is loaded
init_db_sync()

# ────────────────────────────────────────────────
# TOOLS
# ────────────────────────────────────────────────

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: Optional[str] = None,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "USD"
) -> Dict[str, Any]:
    """Add new expense entry. Date must be in YYYY-MM-DD format."""
    try:
        # Minimal validation
        datetime.strptime(date, "%Y-%m-%d")
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        if len(currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                INSERT INTO expenses 
                (date, amount, currency, category, subcategory, payment_method, merchant, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, amount, currency.upper(), category, subcategory, payment_method, merchant, notes)) as cursor:
                await db.commit()
                new_id = cursor.lastrowid

        return {
            "success": True,
            "message": "Expense added successfully",
            "id": new_id
        }

    except ValueError as e:
        return {"success": False, "error": f"Validation error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Database error: {str(e)}"}


@mcp.tool()
async def list_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """List expenses with optional date range filter"""
    query = """
        SELECT id, date, amount, currency, category, subcategory,
               payment_method, merchant, notes, created_at
        FROM expenses
    """
    params = []

    conditions = []
    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(min(limit, 1000))  # reasonable upper limit

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return {
                    "success": True,
                    "count": len(rows),
                    "expenses": [dict(row) for row in rows]
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def update_expense(
    id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    notes: Optional[str] = None,
    currency: Optional[str] = None
) -> Dict[str, Any]:
    """Update an existing expense"""
    if all(v is None for v in [date, amount, category, subcategory, payment_method, merchant, notes, currency]):
        return {"success": False, "message": "No fields to update provided"}

    fields = []
    values = []

    if date is not None:        fields.append("date = ?");        values.append(date)
    if amount is not None:      fields.append("amount = ?");      values.append(amount)
    if category is not None:    fields.append("category = ?");    values.append(category)
    if subcategory is not None: fields.append("subcategory = ?"); values.append(subcategory)
    if payment_method is not None: fields.append("payment_method = ?"); values.append(payment_method)
    if merchant is not None:    fields.append("merchant = ?");    values.append(merchant)
    if notes is not None:       fields.append("notes = ?");       values.append(notes)
    if currency is not None:    fields.append("currency = ?");    values.append(currency.upper())

    fields.append("updated_at = datetime('now','localtime')")
    query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"
    values.append(id)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query, values)
            await db.commit()
            if cursor.rowcount == 0:
                return {"success": False, "message": "Expense not found"}
            return {"success": True, "updated_id": id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def delete_expense(id: int) -> Dict[str, Any]:
    """Delete expense by ID"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM expenses WHERE id = ?", (id,))
            await db.commit()
            if cursor.rowcount == 0:
                return {"success": False, "message": "Expense not found"}
            return {"success": True, "deleted_id": id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_expense_summary() -> Dict[str, Any]:
    """Get total amount and breakdown by category/subcategory"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses") as c:
                total = (await c.fetchone())["total"]

            async with db.execute("""
                SELECT category, subcategory, COALESCE(SUM(amount), 0) AS total
                FROM expenses
                GROUP BY category, subcategory
                HAVING total > 0
                ORDER BY total DESC
            """) as c:
                rows = await c.fetchall()

        return {
            "success": True,
            "total": round(float(total), 2),
            "currency": "USD",  # can be made dynamic later
            "by_category": [
                {
                    "category": r["category"],
                    "subcategory": r["subcategory"] or None,
                    "total": round(float(r["total"]), 2)
                }
                for r in rows
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────
# RESOURCE - Categories
# ────────────────────────────────────────────────

@mcp.resource("expenses://categories", mime_type="application/json")
async def categories():
    try:
        async with asyncio.to_thread(open, CATEGORIES_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return json.dumps({"error": "categories.json file not found"}, indent=2)


# ────────────────────────────────────────────────
# SERVER START
# ────────────────────────────────────────────────

if __name__ == "__main__":
    print("Expense Tracker server starting...")
    print(f"Database location: {DB_PATH}")
    print(f"Categories file:    {CATEGORIES_PATH}")
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
    )
































# import os
# import json
# import random
# import asyncio
# import aiosqlite
# from typing import List, Dict, Optional
# from fastmcp import FastMCP

# BASE_DIR = os.path.dirname(__file__)
# DB_PATH = os.path.join(BASE_DIR, "expenses.db")
# CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")

# mcp = FastMCP(name="Expense Tracker")

# # -------------------- DB INIT --------------------

# async def init_db():
#     async with aiosqlite.connect(DB_PATH) as db:
#         await db.execute("""
#         CREATE TABLE IF NOT EXISTS expenses (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             date TEXT NOT NULL,
#             created_at TEXT DEFAULT (datetime('now')),
#             updated_at TEXT DEFAULT (datetime('now')),
#             amount REAL NOT NULL CHECK (amount >= 0),
#             currency TEXT DEFAULT 'USD' CHECK(length(currency) = 3),
#             category TEXT NOT NULL,
#             subcategory TEXT,
#             payment_method TEXT,
#             merchant TEXT,
#             notes TEXT
#         );
#         """)
#         await db.commit()

# # Run init on startup
# asyncio.run(init_db())

# # -------------------- TOOLS --------------------

# @mcp.tool()
# async def add_expense(
#     date: str,
#     amount: float,
#     category: str,
#     subcategory: Optional[str] = None,
#     payment_method: Optional[str] = None,
#     merchant: Optional[str] = None,
#     notes: Optional[str] = None,
#     currency: str = "USD"
# ) -> Dict:
#     async with aiosqlite.connect(DB_PATH) as db:
#         await db.execute("""
#             INSERT INTO expenses
#             (date, amount, category, subcategory, payment_method, merchant, notes, currency)
#             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
#         """, (date, amount, category, subcategory, payment_method, merchant, notes, currency))
#         await db.commit()

#     return {"success": True}


# @mcp.tool()
# async def list_expenses(
#     start_date: Optional[str] = None,
#     end_date: Optional[str] = None,
#     limit: int = 100
# ) -> List[Dict]:
#     query = """
#         SELECT id, date, amount, currency, category, subcategory,
#                payment_method, merchant, notes, created_at
#         FROM expenses
#     """
#     filters = []
#     values = []

#     if start_date:
#         filters.append("date >= ?")
#         values.append(start_date)
#     if end_date:
#         filters.append("date <= ?")
#         values.append(end_date)

#     if filters:
#         query += " WHERE " + " AND ".join(filters)

#     query += " ORDER BY date DESC LIMIT ?"
#     values.append(limit)

#     async with aiosqlite.connect(DB_PATH) as db:
#         db.row_factory = aiosqlite.Row
#         async with db.execute(query, values) as cursor:
#             rows = await cursor.fetchall()

#     return [dict(row) for row in rows]


# @mcp.tool()
# async def update_expense(
#     id: int,
#     date: Optional[str] = None,
#     amount: Optional[float] = None,
#     category: Optional[str] = None,
#     subcategory: Optional[str] = None,
#     payment_method: Optional[str] = None,
#     merchant: Optional[str] = None,
#     notes: Optional[str] = None,
#     currency: Optional[str] = None
# ) -> Dict:
#     fields = []
#     values = []

#     if date is not None:
#         fields.append("date = ?")
#         values.append(date)
#     if amount is not None:
#         fields.append("amount = ?")
#         values.append(amount)
#     if category is not None:
#         fields.append("category = ?")
#         values.append(category)
#     if subcategory is not None:
#         fields.append("subcategory = ?")
#         values.append(subcategory)
#     if payment_method is not None:
#         fields.append("payment_method = ?")
#         values.append(payment_method)
#     if merchant is not None:
#         fields.append("merchant = ?")
#         values.append(merchant)
#     if notes is not None:
#         fields.append("notes = ?")
#         values.append(notes)
#     if currency is not None:
#         fields.append("currency = ?")
#         values.append(currency)

#     if not fields:
#         return {"success": False, "message": "No fields provided"}

#     fields.append("updated_at = datetime('now')")
#     query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"
#     values.append(id)

#     async with aiosqlite.connect(DB_PATH) as db:
#         cursor = await db.execute(query, values)
#         await db.commit()

#         if cursor.rowcount == 0:
#             return {"success": False, "message": "Expense not found"}

#     return {"success": True, "updated_id": id}


# @mcp.tool()
# async def delete_expense(id: int) -> Dict:
#     async with aiosqlite.connect(DB_PATH) as db:
#         cursor = await db.execute("DELETE FROM expenses WHERE id = ?", (id,))
#         await db.commit()

#         if cursor.rowcount == 0:
#             return {"success": False, "message": "Expense not found"}

#     return {"success": True, "deleted_id": id}


# @mcp.tool()
# async def get_expense_summary() -> Dict:
#     async with aiosqlite.connect(DB_PATH) as db:
#         db.row_factory = aiosqlite.Row

#         async with db.execute("SELECT SUM(amount) AS total FROM expenses") as c:
#             row = await c.fetchone()
#             total = row["total"] or 0.0

#         async with db.execute("""
#             SELECT category, subcategory, SUM(amount) AS total
#             FROM expenses
#             GROUP BY category, subcategory
#         """) as c:
#             rows = await c.fetchall()

#     return {
#         "total": total,
#         "by_category": [
#             {
#                 "category": r["category"],
#                 "subcategory": r["subcategory"] or "",
#                 "total": r["total"]
#             }
#             for r in rows
#         ]
#     }

# # -------------------- RESOURCE --------------------

# @mcp.resource("expenses://categories", mime_type="application/json")
# async def categories():
#     async with asyncio.to_thread(open, CATEGORIES_PATH, "r", encoding="utf-8") as f:
#         return f.read()

# # -------------------- RUN SERVER --------------------

# if __name__ == "__main__":
#     mcp.run(
#         transport="http",
#         host="0.0.0.0",
#         port=8000,
#     )




























# from fastmcp import FastMCP
# import random
# import json

# mcp = FastMCP("Simple Calculator Server")

# @mcp.tool
# def add(a: float, b: float) -> float:
#     """
#     Add two number together.

#     Args:
#         a (float): The first number.
#         b (float): The second number.

#     Returns:
#         float: The sum of the two numbers.
#     """
#     return a + b

# @mcp.tool
# def random_number(min_value: int, max_value: int) -> int:
#     """
#     Generate a random integer between min_value and max_value.

#     Args:
#         min_value (int): The minimum value.
#         max_value (int): The maximum value.

#     Returns:
#         int: A random integer between min_value and max_value.
#     """
#     return random.randint(min_value, max_value)

# @mcp.resource("info://server")
# def server_info() -> str:
#     """
#     Get server information.

#     Returns:
#         str: A JSON string containing server information.
#     """
#     info = {
#         "server_name": "Simple Calculator Server",
#         "version": "1.0",
#         "description": "A server that provides simple calculator functions.",
#         "tools": ["add", "random_number"],
#         "author": "Ahmed Khan"
#     }
#     return json.dumps(info , indent=2)

# if __name__ == "__main__":
#     mcp.run(transport="http", host="0.0.0.0", port=8000 )