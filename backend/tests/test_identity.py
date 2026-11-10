async def test_register_login_logout(client):
    r = await client.post(
        "/api/auth/register", json={"email": "Ana@Example.com", "password": "secret123"}
    )
    assert r.status_code == 201
    assert r.json()["email"] == "ana@example.com"
    assert r.json()["role"] == "owner"

    assert (await client.get("/api/auth/me")).status_code == 200

    assert (await client.post("/api/auth/logout")).status_code == 204
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"

    r = await client.post(
        "/api/auth/login", json={"email": "ana@example.com", "password": "secret123"}
    )
    assert r.status_code == 200


async def test_duplicate_email(client):
    body = {"email": "a@b.co", "password": "secret123"}
    await client.post("/api/auth/register", json=body)
    r = await client.post("/api/auth/register", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_wrong_password(client):
    await client.post("/api/auth/register", json={"email": "a@b.co", "password": "secret123"})
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login", json={"email": "a@b.co", "password": "wrongpass"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


async def test_validation_error_shape(client):
    r = await client.post("/api/auth/register", json={"email": "nope", "password": "short"})
    assert r.status_code == 422
    fields = {f["field"] for f in r.json()["error"]["fields"]}
    assert fields == {"email", "password"}
