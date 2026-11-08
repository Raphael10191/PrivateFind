"""Business logic of PrivateFind.

The API routes (backend/api) stay small and call these functions. Only the
services talk to the database. They never commit themselves: the caller
(API route, seed script, test) decides when to commit.
"""
