"""Protocol module for ReconnectProxy data transfer.

Session IDs are signed 8-bit integers (-128 to 127).
"""

import struct
from typing import Tuple


# Protocol constants
HEADER_FORMAT = "!b"  # Signed 8-bit integer (1 byte) for session ID
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_SESSION_ID = 127
MIN_SESSION_ID = -127

# Special session IDs
SESSION_ID_NEW = 0  # For creating new sessions
SESSION_ID_ERROR = 0  # Error response
SESSION_ID_MIN = -128  # Minimum valid session ID (reserved)


def encode_session_id(session_id: int) -> bytes:
    """Encode a session ID into bytes for transmission.
    
    Args:
        session_id: Session ID as signed 8-bit integer (-128 to 127)
        
    Returns:
        1-byte signed integer in network byte order
    """
    return struct.pack(HEADER_FORMAT, session_id)


def decode_session_id(data: bytes) -> int:
    """Decode bytes into a session ID.
    
    Args:
        data: 1-byte signed integer in network byte order
        
    Returns:
        Session ID as signed 8-bit integer
    """
    return struct.unpack(HEADER_FORMAT, data)[0]


def create_session_request(session_id: int) -> bytes:
    """Create a session request packet."""
    return encode_session_id(session_id)


def parse_session_response(data: bytes) -> int:
    """Parse a session response packet and return the session ID."""
    return decode_session_id(data)


def is_error_response(session_id: int) -> bool:
    """Check if the session ID indicates an error response.
    
    Args:
        session_id: Session ID from response
        
    Returns:
        True if session_id == 0 (error)
    """
    return session_id == SESSION_ID_ERROR


def is_new_session_response(session_id: int) -> bool:
    """Check if the session ID indicates a new session was created.
    
    Args:
        session_id: Session ID from response
        
    Returns:
        True if 1 <= session_id <= 127
    """
    return 1 <= session_id <= MAX_SESSION_ID


def is_inbound_session_response(session_id: int) -> bool:
    """Check if the session ID indicates an inbound session was attached.
    
    Args:
        session_id: Session ID from response
        
    Returns:
        True if -127 <= session_id <= -1
    """
    return MIN_SESSION_ID <= session_id <= -1


def is_valid_session_id(session_id: int) -> bool:
    """Check if session ID is valid for use.
    
    Args:
        session_id: Session ID to validate
        
    Returns:
        True if session_id is in valid range (1-127 or -127 to -1)
    """
    return (1 <= session_id <= MAX_SESSION_ID) or (MIN_SESSION_ID <= session_id <= -1)