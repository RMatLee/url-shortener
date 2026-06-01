import math

# 62 characters: 0-9, a-z, A-Z
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(BASE62_CHARS)

def encode(num: int) -> str:
    """
    Convert a positive integer (DB row ID) to a Base62 String

    Note: 6 characters in Base62 gives 62^6 unique codes. 
    """
    if num == 0:
        return BASE62_CHARS[0]
    
    result = []

    while num > 0:
        result.append(BASE62_CHARS[num % BASE])

        num //= BASE

    return "".join(reversed(result))

def decode(code: str) -> int:
    """
    Convert a Base62 string back to its integer ID.
    """
    result = 0

    for char in code:
        result = result * BASE + BASE62_CHARS.index(char)
    
    return result

def min_code_length_for(n_urls: int) -> int:
    """
    Helper to reason about capacity
    """
    return math.ceil(math.log(n_urls, BASE))