"""Settings of PrivateFind.

All values come from the .env file (see .env.example). The defaults are only
meant for local development on our laptops.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Secret for hashing short codes (HMAC). Must be the same on every start,
# otherwise old deposit and pickup codes are no longer valid.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Private folder for the item photos. Never served as a public static folder.
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = PROJECT_ROOT / UPLOAD_DIR

# Item categories. The frontend shows them as a dropdown, the backend only accepts these.
CATEGORIES = [
    "wallet", "phone", "keys", "bag", "umbrella", "earphones",
    "card", "laptop", "bottle", "clothing", "other",
]

# Deposit
PHOTOS_PER_ITEM = 3                     # proposal: three photos from different sides
MAX_PHOTO_BYTES = 10 * 1024 * 1024      # 10 MB per photo
ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}
DEPOSIT_SESSION_MINUTES = int(os.getenv("DEPOSIT_SESSION_MINUTES", "15"))

# Locker codes
CODE_LENGTH = 6
DEPOSIT_CODE_MINUTES = int(os.getenv("DEPOSIT_CODE_MINUTES", "15"))
PICKUP_CODE_HOURS = int(os.getenv("PICKUP_CODE_HOURS", "48"))

# Matching (proposal 4.3)
MATCH_WEIGHTS = {
    "category": 0.25,
    "location": 0.15,
    "time": 0.15,
    "attributes": 0.25,
    "semantic": 0.20,
}
MATCH_MIN_SCORE = 60
MATCH_MAX_CANDIDATES = 3
# Semantic similarity (work package 7.2, see services/embeddings.py).
# false: the other four factors are rescaled to 0-100.
# true: the 20 % semantic part is used (set to true when the embedding API works).
SEMANTIC_ENABLED = os.getenv("SEMANTIC_ENABLED", "false").lower() == "true"

# Growing wait times after failed claims, per account and item (proposal 4.4)
CLAIM_WAIT_MINUTES = [5, 10, 20, 60]

# IP rate limit for the web API (proposal 4.4): max. requests per IP and minute.
# An IP is never blocked for good, because many students share one public IP.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

# Activity alerts for the administrator (written to the audit log as "alert_...")
ALERT_FAILED_CLAIMS_PER_ITEM = 3    # failed claims on one item within 24 hours
ALERT_WRONG_CODES_PER_LOCKER = 5    # wrong keypad codes at one locker within 10 minutes
