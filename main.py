import random
import os
import sqlite3
from fastmcp import FastMCP
from typing import List, Dict , Optional

DB_PATH = os.path.join(os.path.dirname(__file__), 'expenses.db')
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), 'categories.json')

mcp =  FastMCP(name = "Expense Tracker")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                     -- Expense date (YYYY-MM-DD)
    created_at TEXT DEFAULT (datetime('now')), -- Record creation timestamp
    updated_at TEXT DEFAULT (datetime('now')), -- Last update timestamp
    amount REAL NOT NULL CHECK (amount >= 0),  -- Expense amount
    currency TEXT DEFAULT 'USD' CHECK(length(currency) = 3), -- 3-letter currency code
    category TEXT NOT NULL,                 -- Main category (Food, Travel, etc.)
    subcategory TEXT,                       -- Optional subcategory
    payment_method TEXT,                     -- Cash, Card, Online, etc.
    merchant TEXT,                           -- Optional merchant/store name
    notes TEXT                               -- Optional notes
);
""")
    conn.commit()
    conn.close()

init_db()


@mcp.tool()
def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: Optional[str] = None,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "USD"
):
    """
    Add an expense to the database.

    Args:
        date (str): Expense date in YYYY-MM-DD format
        amount (float): Expense amount
        category (str): Main category
        subcategory (str, optional): Subcategory
        payment_method (str, optional): Payment method
        merchant (str, optional): Merchant/store name
        notes (str, optional): Notes
        currency (str, optional): 3-letter currency code (default USD)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO expenses 
        (date, amount, category, subcategory, payment_method, merchant, notes, currency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (date, amount, category, subcategory, payment_method, merchant, notes, currency))
    conn.commit()
    conn.close()


@mcp.tool()
def list_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
) -> List[Dict]:
    """
    List expenses in a structured format filtered by date range.

    Args:
        start_date (str, optional): Start date in YYYY-MM-DD format.
        end_date (str, optional): End date in YYYY-MM-DD format.
        limit (int, optional): Maximum number of expenses to return. Defaults to 100.

    Returns:
        List[Dict]: List of expense records with keys:
            date, amount, currency, category, subcategory, payment_method, merchant, notes, created_at
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = """
        SELECT date, amount, currency, category, subcategory, payment_method, merchant, notes, created_at
        FROM expenses
    """
    
    # Build dynamic WHERE clause for date filtering
    filters = []
    values = []
    if start_date:
        filters.append("date >= ?")
        values.append(start_date)
    if end_date:
        filters.append("date <= ?")
        values.append(end_date)
    
    if filters:
        query += " WHERE " + " AND ".join(filters)
    
    query += " ORDER BY date DESC LIMIT ?"
    values.append(limit)
    
    c.execute(query, tuple(values))
    rows = c.fetchall()
    conn.close()
    
    # Convert rows to list of dicts
    expenses = [dict(row) for row in rows]
    
    return expenses




@mcp.tool()
def update_expense(
    id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    notes: Optional[str] = None,
    currency: Optional[str] = None
) -> dict:
    """
    Dynamically update an expense in the database.
    Only non-None fields will be updated.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Build dynamic update query
        fields = []
        values = []

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

        if not fields:
            return {"success": False, "message": "No fields provided to update."}

        # Always update updated_at
        fields.append("updated_at = datetime('now')")

        query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"
        values.append(id)

        c.execute(query, values)
        conn.commit()

        if c.rowcount == 0:
            return {"success": False, "message": f"Expense with ID {id} not found."}

        return {"success": True, "updated_id": id}

    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}

    finally:
        conn.close()



@mcp.tool()
def delete_expense(id: int) -> Dict:
    """
    Delete an expense from the database.
    
    Args:
        id (int): Expense ID to delete.

    Returns:
        dict: Status of the operation and deleted expense id.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM expenses WHERE id = ?", (id,))
        conn.commit()
        
        if c.rowcount == 0:
            return {"success": False, "message": f"Expense with ID {id} not found."}
        return {"success": True, "deleted_id": id}
    
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}
    
    finally:
        conn.close()


@mcp.tool()
def get_expense_summary() -> Dict:
    """
    Get a summary of expenses by category and subcategory, including totals.

    Returns:
        dict: {
            "total": float,                  # Total of all expenses
            "by_category": List[Dict]        # List of category summaries
        }
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT SUM(amount) as total FROM expenses")
        total = c.fetchone()["total"] or 0.0

        c.execute("""
            SELECT category, subcategory, SUM(amount) as total
            FROM expenses
            GROUP BY category, subcategory
            ORDER BY category, subcategory
        """)
        rows = c.fetchall()

        by_category = []
        for row in rows:
            by_category.append({
                "category": row["category"],
                "subcategory": row["subcategory"] if row["subcategory"] else "",
                "total": row["total"]
            })

        return {
            "total": total,
            "by_category": by_category
        }

    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}

    finally:
        conn.close()

@mcp.resource("expenses://categories", mime_type="application/json")
def categories():
    with open(CATEGORIES_PATH, 'r', encoding='utf-8') as f:
        return f.read()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000 )




































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