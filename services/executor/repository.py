# services\executor\repository.py
import uuid
from pydantic import BaseModel
import oracledb
import json


class OCICycleRepository:
    """
    Manages data persistence for trading cycles directly in the OCI database.
    This repository uses raw SQL with the oracledb driver for performance,
    bypassing the main application's SQLAlchemy ORM.
    """

    def __init__(self, pool: oracledb.SessionPool):
        """
        Initializes the repository with an oracledb connection pool.

        Args:
            pool: An initialized oracledb.SessionPool instance.
        """
        self.pool = pool

    def log_activity(
        self,
        user_id: uuid.UUID,
        cycle_id: uuid.UUID,
        activity_type: str,
        activity_data: BaseModel,
    ):
        """
        Inserts a new trading activity event into the database.

        Args:
            user_id: The UUID of the user associated with the event.
            cycle_id: The UUID of the trading cycle this event belongs to.
            activity_type: The string identifier for the event type (e.g., 'CYCLE_CREATED').
            activity_data: A Pydantic model containing the event's data payload.
        """
        sql = """
            INSERT INTO trading_activities (
                id, user_id, cycle_id, activity_type, activity_data, created_at
            ) VALUES (:id, :user_id, :cycle_id, :activity_type, :activity_data, SYSTIMESTAMP)
        """
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                params = {
                    "id": uuid.uuid4().bytes,
                    "user_id": user_id.bytes,
                    "cycle_id": cycle_id.bytes,
                    "activity_type": activity_type,
                    # Serialize the Pydantic model to a JSON string for the CLOB field.
                    "activity_data": activity_data.model_dump_json(),
                }
                cursor.execute(sql, params)
                connection.commit()

    def get_events_by_cycle_id(self, cycle_id: uuid.UUID) -> list:
        """
        Retrieves all events for a specific cycle, ordered by creation time.
        This is used to reconstruct the state of a single trading cycle.

        Args:
            cycle_id: The UUID of the cycle to retrieve events for.

        Returns:
            A list of dictionaries, each representing an event.
        """
        sql = """
            SELECT activity_type, activity_data, created_at
            FROM trading_activities
            WHERE cycle_id = :cycle_id
            ORDER BY created_at ASC
        """
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, {"cycle_id": cycle_id.bytes})
                # The CLOB data is fetched as a LOB object, so we must read it.
                # The data is stored as JSON, so we parse it back.
                return [
                    {
                        "activity_type": row[0],
                        "activity_data": json.loads(row[1].read()),
                        "created_at": row[2],
                    }
                    for row in cursor.fetchall()
                ]

    def get_open_cycles_by_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """
        Finds all cycle_ids for a user that have not been closed.
        This is the critical query for state reconstruction on executor startup.

        Args:
            user_id: The UUID of the user to check for open cycles.

        Returns:
            A list of UUIDs for all open cycles.
        """
        sql = """
            SELECT cycle_id FROM trading_activities
            WHERE user_id = :user_id AND cycle_id IS NOT NULL
            GROUP BY cycle_id
            HAVING SUM(CASE WHEN activity_type = 'CYCLE_CLOSED' THEN 1 ELSE 0 END) = 0
        """
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, {"user_id": user_id.bytes})
                # The RAW(16) cycle_id is returned as bytes, convert back to UUID.
                return [uuid.UUID(bytes=row[0]) for row in cursor.fetchall()]
