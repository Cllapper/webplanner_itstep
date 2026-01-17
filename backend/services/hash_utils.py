import hashlib

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash
