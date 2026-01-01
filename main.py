import os
import json
import asyncio
import sqlite3
import aiosqlite
from typing import List, Dict, Optional, Any
from datetime import datetime
from fastmcp import FastMCP

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "expenses.db")
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")

mcp = FastMCP(name="Expense Tracker")

# ────────────────────────────────────────────────
# SYNCHRONOUS DB INITIALIZATION (safe at import time)
# ────────────────────────────────────────────────

def init_db_sync():
    """Create table if it doesn't exist - runs once when module is imported"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,               -- ISO format: YYYY-MM-DD
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now')),
            amount      REAL  NOT NULL CHECK(amount >= 0),
            currency    TEXT  DEFAULT 'USD' CHECK(length(currency) = 3),
            category    TEXT  NOT NULL,
            subcategory TEXT,
            payment_method TEXT,
            merchant    TEXT,
            notes       TEXT
        );
        """)
        conn.commit()
        # Optional: create index for faster queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON expenses(date);")
        conn.commit()

# Run initialization right away (before any async context)
init_db_sync()

# ────────────────────────────────────────────────
# TOOLS
# ────────────────────────────────────────────────

@mcp.tool()
async def add_expense(
    date: str,                    # expected format: YYYY-MM-DD
    amount: float,
    category: str,
    subcategory: Optional[str] = None,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "USD"
) -> Dict[str, Any]:
    """Add a new expense entry"""
    try:
        # Basic validation
        datetime.strptime(date, "%Y-%m-%d")  # will raise ValueError if invalid
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        if len(currency) != 3:
            raise ValueError("Currency must be 3-letter code")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO expenses 
                (date, amount, currency, category, subcategory, payment_method, merchant, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, amount, currency, category, subcategory, payment_method, merchant, notes))
            
            await db.commit()
            new_id = db.lastrowid

        return {
            "success": True,
            "message": "Expense added successfully",
            "id": new_id
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Database error: {str(e)}"}


@mcp.tool()
async def list_expenses(
    start_date: Optional[str] = None,   # YYYY-MM-DD
    end_date: Optional[str] = None,     # YYYY-MM-DD
    limit: int = 100
) -> Dict[str, Any]:
    """List recent expenses with optional date range filter"""
    query = """
        SELECT id, date, amount, currency, category, subcategory,
               payment_method, merchant, notes, created_at
        FROM expenses
    """
    params: List[Any] = []

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
    params.append(min(limit, 500))  # safety limit

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
    """Update existing expense"""
    if not any([date, amount is not None, category, subcategory, payment_method, merchant, notes, currency]):
        return {"success": False, "message": "No fields to update"}

    fields = []
    values: List[Any] = []

    if date is not None:
        fields.append("date = ?")
        values.append(date)
    if amount is not None:
        fields.append("amount = ?")
        values.append(amount)
    if category is not None:
        fields.append("category = ?")
        values.append(category)
    if subcategory is not None:
        fields.append("subcategory = ?")
        values.append(subcategory)
    if payment_method is not None:
        fields.append("payment_method = ?")
        values.append(payment_method)
    if merchant is not None:
        fields.append("merchant = ?")
        values.append(merchant)
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if currency is not None:
        fields.append("currency = ?")
        values.append(currency)

    fields.append("updated_at = datetime('now')")
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
    """Delete an expense by ID"""
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
    """Get total expenses and breakdown by category/subcategory"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            # Total
            async with db.execute("SELECT SUM(amount) AS total FROM expenses") as c:
                total = (await c.fetchone())["total"] or 0.0

            # By category/subcategory
            async with db.execute("""
                SELECT category, subcategory, SUM(amount) AS total
                FROM expenses
                GROUP BY category, subcategory
                ORDER BY total DESC
            """) as c:
                rows = await c.fetchall()

        return {
            "success": True,
            "total": round(total, 2),
            "by_category": [
                {
                    "category": r["category"],
                    "subcategory": r["subcategory"] or None,
                    "total": round(r["total"], 2)
                }
                for r in rows
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ────────────────────────────────────────────────
# RESOURCE
# ────────────────────────────────────────────────

@mcp.resource("expenses://categories", mime_type="application/json")
async def get_categories():
    """Returns list of available categories"""
    try:
        # Using asyncio.to_thread to not block event loop
        content = await asyncio.to_thread(
            lambda: open(CATEGORIES_PATH, "r", encoding="utf-8").read()
        )
        return content
    except Exception:
        return json.dumps({"error": "Categories file not found"})


# ────────────────────────────────────────────────
# START SERVER
# ────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Expense Tracker server...")
    print(f"Database: {DB_PATH}")
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
        # You can add workers=4 etc. when your version supports it
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