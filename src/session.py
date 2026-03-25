"""Session management module for ReconnectProxy."""

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Session:
    """Base session class with common properties."""
    session_id: int
    bytes_sent_outbound: int
    bytes_sent_inbound: int
    outbound_start_time: datetime
    inbound_start_time: datetime
    outbound_socket: Optional[socket.socket]
    inbound_socket: Optional[socket.socket]

    def __init__(self, session_id: int, outbound_socket: socket.socket):
        self.session_id = session_id
        self.bytes_sent_outbound = 0
        self.outbound_start_time = datetime.now()
        self.bytes_sent_inbound = 0
        self.inbound_start_time = datetime.now()
        self.outbound_socket = outbound_socket
        self.inbound_socket = None

    def __post_init__(self):
        """Initialize logging for the session."""
        self.logger = logging.getLogger(f"session.{self.session_id}")

    def reset_outbound_counters(self) -> None:
        """Reset outbound byte counter for reconnection."""
        self.bytes_sent_outbound = 0
        self.outbound_start_time = datetime.now()
        self.logger.debug("Session outbound counters reset")

    def reset_inbound_counters(self) -> None:
        """Reset inbound byte counter for reconnection."""
        self.bytes_sent_inbound = 0
        self.inbound_start_time = datetime.now()
        self.logger.debug("Session inbound counters reset")


class ProxyServerSession(Session):
    """Session for proxy-server component."""
    server_socket: Optional[socket.socket]

    def __init__(self, session_id: int, server_socket: socket.socket, outbound_socket: socket.socket):
        super().__init__(session_id=session_id, outbound_socket=outbound_socket)
        self.server_socket = server_socket
        self.logger = logging.getLogger(f"proxy-server.session.{session_id}")

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
        self.logger.info("Session closed, all sockets closed")


class ProxyClientSession(Session):
    """Session for proxy-client component."""
    client_socket: Optional[socket.socket]

    def __init__(self, session_id: int, client_socket: socket.socket, outbound_socket: socket.socket):
        super().__init__(session_id=session_id, outbound_socket=outbound_socket)
        self.client_socket: Optional[socket.socket] = client_socket
        self.logger = logging.getLogger(f"proxy-client.session.{session_id}")

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
        self.logger.info("Session closed, all sockets closed")
