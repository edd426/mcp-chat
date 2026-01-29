"""MCP Chat Server implementation."""

from typing import Dict, Any
import logging
import uuid
from datetime import datetime

from fastmcp import FastMCP

from mcp_chat.history import HistoryManager
from mcp_chat.managers import RoomManager
from mcp_chat.models import Message, PersistedMessage, User

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server with SSE transport
mcp: Any = FastMCP(name="mcp-chat", version="0.1.0")

# Initialize managers
room_manager = RoomManager()
history_manager = HistoryManager()

# Store active connections (connection_id -> User)
connections: Dict[str, User] = {}


@mcp.tool()
async def join_room(room_id: str, display_name: str) -> Dict[str, Any]:
    """Join a conversation thread.

    Creates a new session with a unique client_id and adds you to the specified room.
    Messages persist even when you're not connected - you can leave and return later
    to check for new messages using get_room_status and get_history.

    Args:
        room_id: The ID of the room to join (creates room if it doesn't exist)
        display_name: Your display name in the conversation

    Returns:
        Success status with client_id, or error information
    """
    # Generate a unique client_id for this user
    connection_id = str(uuid.uuid4())

    # Create new user
    user = User(display_name=display_name, connection_id=connection_id)
    connections[connection_id] = user

    # Check if room exists
    room = await room_manager.get_room(room_id)
    if not room:
        # Create a new room with just this user
        room = await room_manager.create_room(user, user)  # Temporarily both users
        room.room_id = room_id  # Override the generated ID
        # Update the room in manager
        room_manager._rooms[room_id] = room
        room_manager._user_to_room[user.user_id] = room_id

        logger.info(f"Created new room {room_id} for {user.name}")

        return {
            "status": "room_created",
            "room_id": room_id,
            "client_id": connection_id,
            "message": "New room created, waiting for another user to join",
        }

    # Check if room is active
    if not room.active:
        return {
            "status": "error",
            "error": "Room is no longer active",
            "client_id": connection_id,
        }

    # Check if room has space (max 2 users)
    current_users = []
    active_user_ids = {u.user_id for u in connections.values()}
    if room.user1 and room.user1.user_id in active_user_ids:
        current_users.append(room.user1)
    if (
        room.user2
        and room.user2.user_id != room.user1.user_id
        and room.user2.user_id in active_user_ids
    ):
        current_users.append(room.user2)

    if len(current_users) >= 2:
        return {"status": "error", "error": "Room is full", "client_id": connection_id}

    # Add user to room
    if len(current_users) == 0:
        # First user in existing room
        room.user1 = user
    else:
        # Second user joining
        room.user2 = user

        # Persist system join message
        join_msg_id = str(uuid.uuid4())
        join_timestamp = datetime.now().isoformat()
        persisted_join = PersistedMessage(
            message_id=join_msg_id,
            room_id=room_id,
            sender_id="system",
            sender_name="System",
            content=f"[System] {user.name} has joined the chat.",
            timestamp=join_timestamp,
            is_system=True,
        )
        await history_manager.add_message(room_id, persisted_join)

    # Update user-to-room mapping
    room_manager._user_to_room[user.user_id] = room_id

    logger.info(f"User {user.name} joined room {room_id}")

    # Get partner info if exists
    partner = room.get_partner(user.user_id)

    return {
        "status": "joined",
        "room_id": room_id,
        "client_id": connection_id,
        "partner": {"display_name": partner.name} if partner else None,
        "message": "Successfully joined room"
        + (f" with {partner.name}" if partner else ", waiting for partner"),
    }


@mcp.tool()
async def send_message(room_id: str, message: str, client_id: str) -> Dict[str, Any]:
    """Post a message to a conversation thread.

    The message is stored persistently and other participants will see it when they
    check the room. Don't expect an immediate reply - this is asynchronous like email.

    To check for responses later, use get_room_status to see if message_count increased,
    then get_history to retrieve new messages.

    Args:
        room_id: The ID of the chat room
        message: The message to send
        client_id: Your client identifier (from join_room)

    Returns:
        Success status with message_id and timestamp, or error information
    """
    # Use the provided client_id
    connection_id = client_id

    # Get user
    user = connections.get(connection_id)
    if not user:
        logger.error(f"User not found for client_id: {client_id}")
        logger.debug(f"Active connections: {list(connections.keys())}")
        return {
            "success": False,
            "error": f"User not found. Invalid client_id: {client_id}",
        }

    # Get room
    room = await room_manager.get_room(room_id)
    if not room:
        return {"success": False, "error": "Room not found"}

    if not room.active:
        return {"success": False, "error": "Chat has ended"}

    # Verify user is in the room
    if not room.has_user(user.user_id):
        return {"success": False, "error": "You are not in this room"}

    # Get partner
    partner = room.get_partner(user.user_id)
    if not partner:
        return {"success": False, "error": "Partner not found"}

    # Create message
    msg = Message(room_id=room_id, sender_id=user.user_id, content=message)

    # Log message
    logger.info(f"Message from {user.name} to {partner.name}: {message[:50]}...")

    # Persist the message
    persisted_msg = PersistedMessage(
        message_id=msg.message_id,
        room_id=room_id,
        sender_id=user.user_id,
        sender_name=user.name,
        content=message,
        timestamp=msg.timestamp.isoformat(),
        is_system=False,
    )
    await history_manager.add_message(room_id, persisted_msg)

    # Send notification for future notification support
    await send_notification(
        partner.connection_id,
        "message.received",
        {
            "room_id": room_id,
            "message": message,
            "sender": {"user_id": user.user_id, "display_name": user.name},
            "timestamp": msg.timestamp.isoformat(),
        },
    )

    return {
        "success": True,
        "message_id": msg.message_id,
        "timestamp": msg.timestamp.isoformat(),
    }


@mcp.tool()
async def leave_chat(room_id: str, client_id: str) -> Dict[str, Any]:
    """Leave a conversation thread.

    Your messages remain in the room history. A system message noting your
    departure will be recorded.

    Args:
        room_id: The ID of the chat room to leave
        client_id: Your client identifier (from join_room)

    Returns:
        Success status
    """
    # Use the provided client_id
    connection_id = client_id

    # Get user
    user = connections.get(connection_id)
    if not user:
        return {"success": False, "error": "User not found"}

    # Get room
    room = await room_manager.get_room(room_id)
    if not room:
        return {"success": False, "error": "Room not found"}

    # Verify user is in the room
    if not room.has_user(user.user_id):
        return {"success": False, "error": "You are not in this room"}

    # Get partner before closing room
    partner = room.get_partner(user.user_id)

    # Close the room
    await room_manager.close_room(room_id)

    # Log
    logger.info(f"User {user.name} left room {room_id}")

    # Persist system leave message
    leave_msg_id = str(uuid.uuid4())
    leave_timestamp = datetime.now().isoformat()
    persisted_leave = PersistedMessage(
        message_id=leave_msg_id,
        room_id=room_id,
        sender_id="system",
        sender_name="System",
        content=f"[System] {user.name} has left the conversation.",
        timestamp=leave_timestamp,
        is_system=True,
    )
    await history_manager.add_message(room_id, persisted_leave)

    # Notify partner if they exist
    if partner:
        await send_notification(
            partner.connection_id,
            "partner.disconnected",
            {"room_id": room_id, "reason": "left"},
        )

    return {"success": True, "message": "Successfully left the chat"}


@mcp.tool()
async def get_history(room_id: str, limit: int | None = None) -> Dict[str, Any]:
    """Retrieve messages from a conversation thread.

    Returns messages in chronological order. Use the limit parameter to fetch
    only recent messages and avoid filling your context with old history.

    Typical polling pattern:
    1. Call get_room_status to check message_count
    2. If count increased since last check, call get_history(limit=N) for new messages

    Args:
        room_id: The ID of the room to get history for
        limit: Maximum number of messages to return (most recent). Recommended
               to use a limit to avoid context overflow.

    Returns:
        room_id, messages list, and total_count
    """
    messages = await history_manager.get_history(room_id, limit)
    total_count = await history_manager.get_message_count(room_id)

    return {
        "room_id": room_id,
        "messages": [
            {
                "sender": m.sender_name,
                "content": m.content,
                "timestamp": m.timestamp,
                "message_id": m.message_id,
                "is_system": m.is_system,
            }
            for m in messages
        ],
        "total_count": total_count,
    }


@mcp.tool()
async def get_room_status(room_id: str) -> Dict[str, Any]:
    """Lightweight status check for a conversation thread.

    Returns message_count - compare this to your last known count to detect
    new messages without fetching full history. Use this to poll for new
    messages before calling get_history.

    Example polling flow:
    1. After sending a message, note the message_count
    2. Later, call get_room_status and compare message_count
    3. If count increased, call get_history(limit=N) to fetch new messages

    Args:
        room_id: The ID of the room to check

    Returns:
        Room metadata including exists, active, participants, message_count,
        created_at, and last_activity timestamps
    """
    # Check in-memory room first (for active status)
    room = await room_manager.get_room(room_id)

    # Get persisted metadata
    metadata = await history_manager.get_room_metadata(room_id)

    if not room and not metadata:
        return {
            "room_id": room_id,
            "exists": False,
            "error": "Room not found",
        }

    # Merge live room data with persisted metadata
    participants: list[str] = []
    if room:
        if room.user1:
            participants.append(room.user1.name)
        if room.user2 and room.user2.user_id != room.user1.user_id:
            participants.append(room.user2.name)
    elif metadata:
        participants = metadata.participants

    return {
        "room_id": room_id,
        "exists": True,
        "active": room.active if room else False,
        "participants": participants,
        "message_count": metadata.message_count if metadata else 0,
        "created_at": (
            metadata.created_at
            if metadata
            else (room.created_at.isoformat() if room else None)
        ),
        "last_activity": metadata.last_activity if metadata else None,
    }


async def send_notification(
    connection_id: str, method: str, params: Dict[str, Any]
) -> None:
    """Send a notification to a specific client connection.

    This is a placeholder for the actual notification mechanism.
    In a real implementation, this would use the SSE transport
    to push notifications to the client.
    """
    # Log notification for now
    logger.info(f"Notification to {connection_id}: {method} - {params}")

    # In actual implementation, this would use the transport layer
    # to send the notification to the specific connection


async def handle_disconnect(connection_id: str) -> None:
    """Handle user disconnection."""
    user = connections.get(connection_id)
    if not user:
        return

    # Handle room cleanup if in a room
    room = await room_manager.remove_user(user.user_id)
    if room and room.active:
        # Notify partner
        partner = room.get_partner(user.user_id)
        if partner:
            await send_notification(
                partner.connection_id,
                "partner.disconnected",
                {"room_id": room.room_id, "reason": "disconnected"},
            )

    # Remove from connections
    connections.pop(connection_id, None)
    logger.info(f"User {user.name} disconnected")


# Expose ASGI app for uvicorn
app = mcp.http_app()


def main() -> None:
    """Main entry point for the server."""
    import uvicorn

    uvicorn.run("mcp_chat.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
