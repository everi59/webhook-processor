from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import sqlite3
from models import init_db, get_connection, DB_PATH

app = FastAPI()

init_db(DB_PATH)


class WebhookPayload(BaseModel):
    event_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    payload: dict = Field(default_factory=dict)


@app.post("/webhook", status_code=200)
def receive_webhook(webhook: WebhookPayload):
    with get_connection() as conn:
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT id FROM events WHERE event_id = ?", (webhook.event_id,))
            existing = cursor.fetchone()

            if existing:
                return {"status": "duplicate", "event_id": webhook.event_id}

            cursor.execute(
                "INSERT INTO events (event_id, type, payload) VALUES (?, ?, ?)",
                (webhook.event_id, webhook.type, str(webhook.payload))
            )

            cursor.execute(
                "INSERT INTO tasks (event_id, type, status) VALUES (?, ?, 'pending')",
                (webhook.event_id, webhook.type)
            )

            conn.commit()

            return {"status": "accepted", "event_id": webhook.event_id}

        except sqlite3.IntegrityError:
            return {"status": "duplicate", "event_id": webhook.event_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def get_stats():
    with get_connection() as conn:
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT type, COUNT(*) as count FROM events GROUP BY type")
            events_by_type = {row["type"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT status, COUNT(*) as count FROM tasks GROUP BY status")
            tasks_by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

            return {
                "events_by_type": events_by_type,
                "tasks_by_status": tasks_by_status
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
