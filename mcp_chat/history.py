"""History manager for persistent message storage."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_chat.models import PersistedMessage, RoomMetadata

logger = logging.getLogger(__name__)


class HistoryManager:
    """Manages persistent message history using JSON files.

    Storage location: ~/.mcp-chat/history/{room_id}.json
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize the history manager.

        Args:
            base_path: Base directory for history files.
                      Defaults to ~/.mcp-chat/history/
        """
        if base_path is None:
            base_path = Path.home() / ".mcp-chat" / "history"

        self._base_path = base_path
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Per-room locks for thread-safe file access
        self._locks: dict[str, asyncio.Lock] = {}

        logger.info(f"HistoryManager initialized with path: {self._base_path}")

    def _get_lock(self, room_id: str) -> asyncio.Lock:
        """Get or create a lock for a room."""
        if room_id not in self._locks:
            self._locks[room_id] = asyncio.Lock()
        return self._locks[room_id]

    def _get_room_file_path(self, room_id: str) -> Path:
        """Get the JSON file path for a room."""
        # Sanitize room_id to be filesystem-safe
        safe_room_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in room_id)
        return self._base_path / f"{safe_room_id}.json"

    async def _load_room_data(self, room_id: str) -> dict[str, Any]:
        """Load room data from JSON file.

        Returns empty structure if file doesn't exist or is corrupted.
        """
        file_path = self._get_room_file_path(room_id)

        if not file_path.exists():
            return {
                "room_id": room_id,
                "created_at": datetime.now().isoformat(),
                "participants": [],
                "messages": [],
            }

        try:
            content = file_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(content)
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"Corrupted history file for room {room_id}: {e}")
            # Rename corrupted file for potential recovery
            corrupted_path = file_path.with_suffix(
                f".corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            file_path.rename(corrupted_path)
            logger.info(f"Renamed corrupted file to {corrupted_path}")
            return {
                "room_id": room_id,
                "created_at": datetime.now().isoformat(),
                "participants": [],
                "messages": [],
            }
        except Exception as e:
            logger.error(f"Error loading history for room {room_id}: {e}")
            return {
                "room_id": room_id,
                "created_at": datetime.now().isoformat(),
                "participants": [],
                "messages": [],
            }

    async def _save_room_data(self, room_id: str, data: dict[str, Any]) -> None:
        """Save room data to JSON file with atomic write."""
        file_path = self._get_room_file_path(room_id)
        temp_path = file_path.with_suffix(".tmp")

        try:
            # Write to temp file first
            temp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            # Atomic rename
            temp_path.rename(file_path)
        except Exception as e:
            logger.error(f"Error saving history for room {room_id}: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            raise

    async def add_message(self, room_id: str, message: PersistedMessage) -> None:
        """Append a message to room history.

        Args:
            room_id: The room ID
            message: The message to persist
        """
        lock = self._get_lock(room_id)
        async with lock:
            data = await self._load_room_data(room_id)

            # Update participants if not already present
            if message.sender_name not in data["participants"]:
                data["participants"].append(message.sender_name)

            # Append message
            data["messages"].append(message.to_dict())

            # Save
            await self._save_room_data(room_id, data)
            logger.debug(f"Persisted message {message.message_id} in room {room_id}")

    async def get_history(
        self, room_id: str, limit: int | None = None
    ) -> list[PersistedMessage]:
        """Get message history for a room.

        Args:
            room_id: The room ID
            limit: Optional maximum number of messages to return (most recent)

        Returns:
            List of messages, ordered chronologically
        """
        lock = self._get_lock(room_id)
        async with lock:
            data = await self._load_room_data(room_id)

        messages = [PersistedMessage.from_dict(m) for m in data.get("messages", [])]

        if limit is not None and limit > 0:
            messages = messages[-limit:]

        return messages

    async def get_message_count(self, room_id: str) -> int:
        """Get total message count for a room."""
        lock = self._get_lock(room_id)
        async with lock:
            data = await self._load_room_data(room_id)
        return len(data.get("messages", []))

    async def get_room_metadata(self, room_id: str) -> RoomMetadata | None:
        """Get metadata about a room from its history file.

        Returns None if no history exists for the room.
        """
        file_path = self._get_room_file_path(room_id)
        if not file_path.exists():
            return None

        lock = self._get_lock(room_id)
        async with lock:
            data = await self._load_room_data(room_id)

        messages = data.get("messages", [])
        last_activity = (
            messages[-1]["timestamp"] if messages else data.get("created_at", "")
        )

        return RoomMetadata(
            room_id=room_id,
            created_at=data.get("created_at", ""),
            last_activity=last_activity,
            message_count=len(messages),
            participants=data.get("participants", []),
            active=True,  # Will be overridden by live room data
        )
