"""Session management module for ReconnectProxy."""

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SessionState(Enum):
    """Session states for proxy components."""
    NEW = "NEW"
    PARTIAL = "PARTIAL"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


@dataclass
class Session:
    """Base session class with common properties."""
    id: int
    state: SessionState = SessionState.NEW
    bytes_sent_outbound: int = 0
    bytes_sent_inbound: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Initialize logging for the session."""
        self.logger = logging.getLogger(f"session.{self.id}")
    
    def reset_counters(self) -> None:
        """Reset byte counters for reconnection."""
        self.bytes_sent_outbound = 0
        self.bytes_sent_inbound = 0
        self.start_time = datetime.now()
        self.logger.debug("Session counters reset")


class ProxyServerSession(Session):
    """Session for proxy-server component."""
    
    def __init__(self, id: int):
        super().__init__(id=id)
        self.outbound_socket: Optional[socket.socket] = None
        self.inbound_socket: Optional[socket.socket] = None
        self.server_socket: Optional[socket.socket] = None
        self.logger = logging.getLogger(f"proxy-server.session.{id}")
    
    def close_all_sockets(self) -> None:
        """Close all sockets associated with this session."""
        for sock in [self.outbound_socket, self.inbound_socket, self.server_socket]:
            if sock:
                try:
                    sock.close()
                except Exception as e:
                    self.logger.error(f"Error closing socket: {e}")
        self.outbound_socket = None
        self.inbound_socket = None
        self.server_socket = None
        self.state = SessionState.CLOSED
        self.logger.info("Session closed, all sockets closed")


class ProxyClientSession(Session):
    """Session for proxy-client component."""
    
    def __init__(self, id: int):
        super().__init__(id=id)
        self.outbound_socket: Optional[socket.socket] = None
        self.inbound_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.logger = logging.getLogger(f"proxy-client.session.{id}")
    
    def close_all_sockets(self) -> None:
        """Close all sockets associated with this session."""
        for sock in [self.outbound_socket, self.inbound_socket, self.client_socket]:
            if sock:
                try:
                    sock.close()
                except Exception as e:
                    self.logger.error(f"Error closing socket: {e}")
        self.outbound_socket = None
        self.inbound_socket = None
        self.client_socket = None
        self.state = SessionState.CLOSED
        self.logger.info("Session closed, all sockets closed")