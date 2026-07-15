import os
from fastapi import Header, HTTPException

ICU_API_KEY = os.getenv("ICU_API_KEY")

def verify_api_key(x_icu_key: str = Header(...)):
    if not ICU_API_KEY or x_icu_key != ICU_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")