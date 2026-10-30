import time
import random
from datetime import datetime, timedelta, timezone
from models import get_connection, DB_PATH


def simulate_processing(task_type: str) -> bool:
    if random.random() < 0.3:
        raise Exception(f"Simulated error processing {task_type}")
    return True


def process_pending_tasks(max_retries: int = 3, base_delay: float = 1.0, db_path: str = None):
    if db_path is None:
        db_path = DB_PATH

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            SELECT id, event_id, type, status, attempts 
            FROM tasks 
            WHERE status IN ('pending', 'failed')
            AND (next_retry_at IS NULL OR next_retry_at <= ?)
            AND attempts < ?
            ORDER BY created_at ASC
            LIMIT 10
        """, (now, max_retries))

        tasks = cursor.fetchall()

        for task in tasks:
            task_id = task["id"]
            event_id = task["event_id"]
            task_type = task["type"]
            attempts = task["attempts"]

            try:
                simulate_processing(task_type)

                cursor.execute("""
                    UPDATE tasks 
                    SET status = 'success', 
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE id = ?
                """, (now, task_id))

                print(f"Task {task_id} processed successfully")

            except Exception as e:
                new_attempts = attempts + 1

                if new_attempts >= max_retries:
                    cursor.execute("""
                        UPDATE tasks 
                        SET status = 'failed', 
                            attempts = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (new_attempts, now, task_id))

                    print(f"Task {task_id} failed after {new_attempts} attempts: {e}")
                else:
                    delay = base_delay * (2 ** attempts)
                    next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")

                    cursor.execute("""
                        UPDATE tasks 
                        SET status = 'pending',
                            attempts = ?,
                            next_retry_at = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (new_attempts, next_retry, now, task_id))

                    print(f"Task {task_id} scheduled for retry at {next_retry}")

        conn.commit()


def run_worker(interval: float = 5.0, max_retries: int = 3):
    print("Starting worker")
    while True:
        try:
            process_pending_tasks(max_retries=max_retries)
        except Exception as e:
            print(f"Worker error: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    run_worker()
