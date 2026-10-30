import pytest
from fastapi.testclient import TestClient
from models import init_db, get_connection
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = "test_app.db"


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except PermissionError:
            pass

    init_db(TEST_DB)

    yield

    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except PermissionError:
            pass


@pytest.fixture
def client(setup_and_teardown_db):
    from app import app
    from models import DB_PATH

    import models
    models.DB_PATH = TEST_DB

    init_db(TEST_DB)

    return TestClient(app)


def test_webhook_creates_event_and_task(client):
    payload = {
        "event_id": "test-001",
        "type": "payment_succeeded",
        "payload": {"amount": 100, "currency": "RUB"}
    }

    response = client.post("/webhook", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["event_id"] == "test-001"

    with get_connection(TEST_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE event_id = ?", ("test-001",))
        event = cursor.fetchone()
        assert event is not None
        assert event["type"] == "payment_succeeded"

        cursor.execute("SELECT * FROM tasks WHERE event_id = ?", ("test-001",))
        task = cursor.fetchone()
        assert task is not None
        assert task["status"] == "pending"
        assert task["attempts"] == 0


def test_duplicate_webhook_returns_200(client):
    payload = {
        "event_id": "test-duplicate",
        "type": "payment_succeeded",
        "payload": {"amount": 200}
    }

    response1 = client.post("/webhook", json=payload)
    assert response1.status_code == 200
    assert response1.json()["status"] == "accepted"

    response2 = client.post("/webhook", json=payload)
    assert response2.status_code == 200
    assert response2.json()["status"] == "duplicate"

    with get_connection(TEST_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM events WHERE event_id = ?", ("test-duplicate",))
        count = cursor.fetchone()["count"]
        assert count == 1

        cursor.execute("SELECT COUNT(*) as count FROM tasks WHERE event_id = ?", ("test-duplicate",))
        task_count = cursor.fetchone()["count"]
        assert task_count == 1


def test_invalid_webhook_returns_4xx(client):
    response1 = client.post("/webhook", json={})
    assert response1.status_code == 422

    response2 = client.post("/webhook", json={"event_id": "test"})
    assert response2.status_code == 422

    response3 = client.post("/webhook", json={"event_id": 123, "type": "test", "payload": {}})
    assert response3.status_code == 422


def test_stats_endpoint(client):
    events = [
        {"event_id": "stat-001", "type": "payment_succeeded", "payload": {}},
        {"event_id": "stat-002", "type": "payment_succeeded", "payload": {}},
        {"event_id": "stat-003", "type": "payment_failed", "payload": {}},
    ]

    for event in events:
        client.post("/webhook", json=event)

    response = client.get("/stats")
    assert response.status_code == 200

    data = response.json()
    assert "events_by_type" in data
    assert "tasks_by_status" in data

    assert data["events_by_type"]["payment_succeeded"] == 2
    assert data["events_by_type"]["payment_failed"] == 1

    assert data["tasks_by_status"]["pending"] == 3


def test_queue_worker_processes_tasks():
    from queue_worker import process_pending_tasks

    with get_connection(TEST_DB) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO events (event_id, type, payload) VALUES (?, ?, ?)",
            ("worker-test-001", "payment_succeeded", "{}")
        )
        cursor.execute(
            "INSERT INTO tasks (event_id, type, status) VALUES (?, ?, 'pending')",
            ("worker-test-001", "payment_succeeded")
        )
        conn.commit()

    for _ in range(5):
        process_pending_tasks(max_retries=3, base_delay=0.1, db_path=TEST_DB)

    with get_connection(TEST_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempts FROM tasks WHERE event_id = ?", ("worker-test-001",))
        task = cursor.fetchone()

        assert task["status"] in ["success", "failed"]
        assert task["attempts"] >= 1
