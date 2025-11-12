# services\executor\tests\test_repository.py
import uuid
from unittest.mock import MagicMock

import pytest

# The repository class to be tested
from services.executor.repository import OCICycleRepository

# The Pydantic models used as data contracts
from trading_engine_core.models import CycleCreatedEvent

# --- Fixtures ---


@pytest.fixture
def mock_oracle_pool():
    """Provides a mock of the oracledb.SessionPool."""
    # Create mocks for the connection and cursor objects
    mock_cursor = MagicMock()
    mock_connection = MagicMock()
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    # Create the main pool mock
    pool = MagicMock()
    pool.acquire.return_value.__enter__.return_value = mock_connection
    return pool, mock_connection, mock_cursor


@pytest.fixture
def repository(mock_oracle_pool):
    """Provides an instance of the repository with a mocked pool."""
    pool, _, _ = mock_oracle_pool
    return OCICycleRepository(pool)


# --- Test Cases ---


def test_log_activity(repository, mock_oracle_pool):
    """
    Verify that log_activity constructs the correct SQL INSERT statement and parameters,
    and commits the transaction.
    """
    _, mock_connection, mock_cursor = mock_oracle_pool

    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    activity_type = "CYCLE_CREATED"
    activity_data = CycleCreatedEvent(
        strategy_name="TestStrat",
        instrument_ticker="TEST",
        initial_parameters={"param1": "value1"},
    )

    # Act
    repository.log_activity(user_id, cycle_id, activity_type, activity_data)

    # Assert
    # 1. Verify the SQL and parameters passed to execute()
    # We use ANY for the generated UUID and check the rest of the params.
    from unittest.mock import ANY

    expected_params = {
        "id": ANY,
        "user_id": user_id.bytes,
        "cycle_id": cycle_id.bytes,
        "activity_type": activity_type,
        "activity_data": activity_data.model_dump_json(),
    }

    # Extract the SQL from the call arguments
    args, kwargs = mock_cursor.execute.call_args
    actual_sql = " ".join(args[0].split())  # Normalize whitespace for comparison
    expected_sql = " ".join(
        """
        INSERT INTO trading_activities (
            id, user_id, cycle_id, activity_type, activity_data, created_at
        ) VALUES (:id, :user_id, :cycle_id, :activity_type, :activity_data, SYSTIMESTAMP)
    """.split()
    )

    assert actual_sql == expected_sql
    assert kwargs == expected_params

    # 2. Verify the transaction was committed
    mock_connection.commit.assert_called_once()


def test_get_events_by_cycle_id(repository, mock_oracle_pool):
    """
    Verify that get_events_by_cycle_id correctly processes and deserializes
    the raw data (including CLOB) returned from the database.
    """
    _, _, mock_cursor = mock_oracle_pool
    cycle_id = uuid.uuid4()

    # Mock the CLOB object that oracledb returns
    mock_clob = MagicMock()
    mock_clob.read.return_value = '{"strategy_name": "TestStrat"}'

    # Simulate the database result set
    db_result = [
        ("CYCLE_CREATED", mock_clob, "2023-01-01T12:00:00Z"),
    ]
    mock_cursor.fetchall.return_value = db_result

    # Act
    events = repository.get_events_by_cycle_id(cycle_id)

    # Assert
    # 1. Verify the correct query was executed
    mock_cursor.execute.assert_called_once()
    args, kwargs = mock_cursor.execute.call_args
    assert "WHERE cycle_id = :cycle_id" in args[0]
    assert kwargs == {"cycle_id": cycle_id.bytes}

    # 2. Verify the CLOB was read and JSON was parsed
    mock_clob.read.assert_called_once()

    # 3. Verify the final structure of the returned data
    assert len(events) == 1
    assert events[0]["activity_type"] == "CYCLE_CREATED"
    assert events[0]["activity_data"]["strategy_name"] == "TestStrat"


def test_get_open_cycles_by_user(repository, mock_oracle_pool):
    """
    Verify that get_open_cycles_by_user correctly reconstructs UUIDs
    from the raw bytes returned by the database.
    """
    _, _, mock_cursor = mock_oracle_pool
    user_id = uuid.uuid4()

    # Simulate the database returning two cycle_ids as raw bytes
    cycle_id_1 = uuid.uuid4()
    cycle_id_2 = uuid.uuid4()
    db_result = [
        (cycle_id_1.bytes,),
        (cycle_id_2.bytes,),
    ]
    mock_cursor.fetchall.return_value = db_result

    # Act
    open_cycles = repository.get_open_cycles_by_user(user_id)

    # Assert
    # 1. Verify the correct query was executed
    mock_cursor.execute.assert_called_once()
    args, kwargs = mock_cursor.execute.call_args
    assert (
        "HAVING SUM(CASE WHEN activity_type = 'CYCLE_CLOSED' THEN 1 ELSE 0 END) = 0"
        in args[0]
    )
    assert kwargs == {"user_id": user_id.bytes}

    # 2. Verify the bytes were correctly converted back to UUID objects
    assert len(open_cycles) == 2
    assert open_cycles[0] == cycle_id_1
    assert open_cycles[1] == cycle_id_2
    assert all(isinstance(c, uuid.UUID) for c in open_cycles)
