"""Proxy-Client entry point for ReconnectProxy."""

import argparse
import logging
import socket
import sys
from typing import Dict, Optional

from session import ProxyClientSession
from protocol import (
    SESSION_ID_NEW,
    SESSION_ID_ERROR,
    encode_session_id,
    decode_session_id,
    is_error_response,
    is_new_session_response,
    is_inbound_session_response,
)

# Configure logging
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="ReconnectProxy Client - TCP proxy client component"
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        required=True,
        help="Port to listen for client connections",
    )
    parser.add_argument(
        "--listen-host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to for listening (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        required=True,
        help="Port of proxy-server to connect to",
    )
    parser.add_argument(
        "--proxy-host",
        type=str,
        default="127.0.0.1",
        help="Host of proxy-server to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=16,
        help="Maximum size of data chunks for transfer (default: 16)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=256,
        help="Maximum total bytes to transfer before reconnection (default: 256)",
    )
    parser.add_argument(
        "--max-time",
        type=int,
        default=5,
        help="Maximum time in seconds before reconnection (default: 5)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    return parser.parse_args()


class ProxyClient:
    """Proxy-Client component implementation."""
    
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        proxy_host: str,
        proxy_port: int,
        chunk_size: int = 16,
        max_size: int = 256,
        max_time: int = 5,
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.chunk_size = chunk_size
        self.max_size = max_size
        self.max_time = max_time
        
        self.logger = logging.getLogger("proxy-client")
        self.sessions: Dict[int, ProxyClientSession] = {}
        
        self.listen_socket: Optional[socket.socket] = None
    
    def _connect_to_proxy_server(self) -> Optional[socket.socket]:
        """Connect to the proxy-server."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.proxy_host, self.proxy_port))
            self.logger.info(f"Connected to proxy-server {self.proxy_host}:{self.proxy_port}")
            return sock
        except Exception as e:
            self.logger.error(f"Failed to connect to proxy-server: {e}")
            return None
    
    def _create_session(self, client_sock: socket.socket) -> Optional[ProxyClientSession]:
        """Create a new session with the proxy-server."""
        # Connect to proxy-server with session_id=0 (new session)
        proxy_sock = self._connect_to_proxy_server()
        if proxy_sock is None:
            self.logger.error("Failed to connect to proxy-server")
            client_sock.close()
            return None
        
        # Send session_id=0 for new session
        try:
            proxy_sock.sendall(encode_session_id(SESSION_ID_NEW))
            self.logger.debug("Sent session_id=0 for new session")
        except Exception as e:
            self.logger.error(f"Error sending session request: {e}")
            client_sock.close()
            proxy_sock.close()
            return None
        
        # Wait for response
        try:
            data = proxy_sock.recv(1)
            if len(data) < 1:
                self.logger.warning("Incomplete session response")
                client_sock.close()
                proxy_sock.close()
                return None
            session_id = decode_session_id(data)
        except Exception as e:
            self.logger.error(f"Error reading session response: {e}")
            client_sock.close()
            proxy_sock.close()
            return None
        
        # Check for error response
        if session_id == SESSION_ID_ERROR:
            self.logger.error("Proxy-server returned error (session_id=0)")
            client_sock.close()
            proxy_sock.close()
            return None
        
        # Verify positive session ID
        if session_id <= 0:
            self.logger.error(f"Invalid session ID {session_id} from proxy-server")
            client_sock.close()
            proxy_sock.close()
            return None
        
        self.logger.info(f"Session {session_id} established with proxy-server")
        
        # Create session
        session = ProxyClientSession(id=session_id)
        session.outbound_socket = proxy_sock
        session.client_socket = client_sock
        self.sessions[session_id] = session
        
        return session
    
    def _reconnect_outbound(self, session: ProxyClientSession) -> bool:
        """Reconnect outbound socket to existing session."""
        proxy_sock = self._connect_to_proxy_server()
        if proxy_sock is None:
            self.logger.error("Failed to connect to proxy-server for outbound reconnection")
            return False
        
        # Send positive session ID for outbound reconnection
        try:
            proxy_sock.sendall(encode_session_id(session.id))
            self.logger.debug(f"Sent session_id={session.id} for outbound reconnection")
        except Exception as e:
            self.logger.error(f"Error sending session request: {e}")
            proxy_sock.close()
            return False
        
        # Wait for response
        try:
            data = proxy_sock.recv(1)
            if len(data) < 1:
                self.logger.warning("Incomplete session response")
                proxy_sock.close()
                return False
            response_id = decode_session_id(data)
        except Exception as e:
            self.logger.error(f"Error reading session response: {e}")
            proxy_sock.close()
            return False
        
        # Check for error response
        if response_id == SESSION_ID_ERROR:
            self.logger.error("Proxy-server returned error for outbound reconnection")
            proxy_sock.close()
            return False
        
        # Verify matching session ID
        if response_id != session.id:
            self.logger.error(f"Session ID mismatch: expected {session.id}, got {response_id}")
            proxy_sock.close()
            return False
        
        session.outbound_socket = proxy_sock
        session.reset_counters()
        self.logger.info(f"Session {session.id} outbound socket reconnected")
        
        return True
    
    def _reconnect_inbound(self, session: ProxyClientSession) -> bool:
        """Reconnect inbound socket to existing session."""
        proxy_sock = self._connect_to_proxy_server()
        if proxy_sock is None:
            self.logger.error("Failed to connect to proxy-server for inbound reconnection")
            return False
        
        inbound_session_id = -session.id
        
        # Send negative session ID for inbound reconnection
        try:
            proxy_sock.sendall(encode_session_id(inbound_session_id))
            self.logger.debug(f"Sent session_id={inbound_session_id} for inbound reconnection")
        except Exception as e:
            self.logger.error(f"Error sending session request: {e}")
            proxy_sock.close()
            return False
        
        # Wait for response
        try:
            data = proxy_sock.recv(1)
            if len(data) < 1:
                self.logger.warning("Incomplete session response")
                proxy_sock.close()
                return False
            response_id = decode_session_id(data)
        except Exception as e:
            self.logger.error(f"Error reading session response: {e}")
            proxy_sock.close()
            return False
        
        # Check for error response
        if response_id == SESSION_ID_ERROR:
            self.logger.error("Proxy-server returned error for inbound reconnection")
            proxy_sock.close()
            return False
        
        # Verify matching session ID
        if response_id != inbound_session_id:
            self.logger.error(f"Session ID mismatch: expected {inbound_session_id}, got {response_id}")
            proxy_sock.close()
            return False
        
        session.inbound_socket = proxy_sock
        session.reset_counters()
        self.logger.info(f"Session {session.id} inbound socket reconnected")
        
        return True
    
    def _attach_inbound(self, session: ProxyClientSession) -> bool:
        """Attach inbound socket to new session."""
        return self._reconnect_inbound(session)
    
    def _handle_client_connection(self, client_sock: socket.socket, addr) -> None:
        """Handle a connection from a client."""
        self.logger.info(f"Client connected from {addr}")
        
        # Create new session with proxy-server
        session = self._create_session(client_sock)
        if session is None:
            self.logger.error("Failed to create session")
            return
        
        # Attach inbound socket
        if not self._attach_inbound(session):
            self.logger.error("Failed to attach inbound socket")
            session.close_all_sockets()
            del self.sessions[session.id]
            return
        
        self.logger.info(f"Session {session.id} fully established, data transfer ready")
    
    def run(self) -> None:
        """Run the proxy client."""
        # Create listen socket
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_socket.bind((self.listen_host, self.listen_port))
        self.listen_socket.listen(5)
        
        self.logger.info(
            f"Proxy-Client listening on {self.listen_host}:{self.listen_port}"
        )
        self.logger.info(f"Proxy-Server: {self.proxy_host}:{self.proxy_port}")
        
        try:
            while True:
                client_sock, addr = self.listen_socket.accept()
                self._handle_client_connection(client_sock, addr)
        except KeyboardInterrupt:
            self.logger.info("Shutting down proxy-client")
        finally:
            if self.listen_socket:
                self.listen_socket.close()
            for session in self.sessions.values():
                session.close_all_sockets()


def main() -> int:
    """Main entry point for proxy-client."""
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=LOG_LEVELS.get(args.log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    client = ProxyClient(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        chunk_size=args.chunk_size,
        max_size=args.max_size,
        max_time=args.max_time,
    )
    
    try:
        client.run()
    except Exception as e:
        logging.error(f"Proxy-client error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())