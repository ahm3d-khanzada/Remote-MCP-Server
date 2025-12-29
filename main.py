from fastmcp import FastMCP
import random
import json

mcp = FastMCP("Simple Calculator Server")

@mcp.tool
def add(a: float, b: float) -> float:
    """
    Add two number together.

    Args:
        a (float): The first number.
        b (float): The second number.

    Returns:
        float: The sum of the two numbers.
    """
    return a + b

@mcp.tool
def random_number(min_value: int, max_value: int) -> int:
    """
    Generate a random integer between min_value and max_value.

    Args:
        min_value (int): The minimum value.
        max_value (int): The maximum value.

    Returns:
        int: A random integer between min_value and max_value.
    """
    return random.randint(min_value, max_value)

@mcp.resource("info://server")
def server_info() -> str:
    """
    Get server information.

    Returns:
        str: A JSON string containing server information.
    """
    info = {
        "server_name": "Simple Calculator Server",
        "version": "1.0",
        "description": "A server that provides simple calculator functions.",
        "tools": ["add", "random_number"],
        "author": "Ahmed Khan"
    }
    return json.dumps(info , indent=2)

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000 )