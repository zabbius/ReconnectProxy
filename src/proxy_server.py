"""Proxy-Server entry point for ReconnectProxy."""

import argparse
import logging
import socket
import sys
from typing import Dict, Optional

from protocol import (
    SESSION_ID_NEW,
    SESSION_ID_ERROR,
    encode_session_id,
    decode_session_id,
)
from session import ProxyServerSession

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
        description="ReconnectProxy Server - TCP proxy server component"
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        required=True,
        help="Port to listen for proxy-client connections",
    )
    parser.add_argument(
        "--listen-host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to for listening (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        required=True,
        help="Port of target server to connect to",
    )
    parser.add_argument(
        "--server-host",
        type=str,
        default="127.0.0.1",
        help="Host of target server to connect to (default: 127.0.0.1)",
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


class ProxyServer:
    """Proxy-Server component implementation."""
    
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        server_host: str,
        server_port: int,
        chunk_size: int = 16,
        max_size: int = 256,
        max_time: int = 5,
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.server_host = server_host
        self.server_port = server_port
        self.chunk_size = chunk_size
        self.max_size = max_size
        self.max_time = max_time
        
        self.logger = logging.getLogger("proxy-server")
        self.sessions: Dict[int, ProxyServerSession] = {}
        self.session_id_counter = 1
        
        self.listen_socket: Optional[socket.socket] = None
    
    def _generate_session_id(self) -> int:
        """Generate a new session ID."""
        session_id = self.session_id_counter
        self.session_id_counter = (self.session_id_counter % 127) + 1
        return session_id

    def _connect_to_server(self) -> Optional[socket.socket]:
        """Connect to the target server."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.server_host, self.server_port))
            self.logger.info(f"Connected to server {self.server_host}:{self.server_port}")
            return sock
        except Exception as e:
            self.logger.error(f"Failed to connect to server: {e}")
            return None

    def _handle_client_connection(self, client_sock: socket.socket, addr) -> None:
        """Handle a connection from proxy-client."""
        self.logger.info(f"Connection from proxy-client {addr}")
        
        # Read session ID once
        try:
            data = client_sock.recv(1)
            if len(data) < 1:
                self.logger.warning("Incomplete session request")
                client_sock.close()
                return
            session_id = decode_session_id(data)
        except Exception as e:
            self.logger.error(f"Error reading session request: {e}")
            client_sock.close()
            return
        
        if session_id == SESSION_ID_NEW:
            # Connect to target server
            server_sock = self._connect_to_server()
            if server_sock is None:
                # Send error response
                client_sock.sendall(encode_session_id(SESSION_ID_ERROR))
                client_sock.close()
                return

            # Generate new session ID
            session_id = self._generate_session_id()
            self.logger.info(f"Created new session {session_id}")

            # Create session
            self.sessions[session_id] = ProxyServerSession(session_id=session_id, server_socket=server_sock)

        session = self.sessions.get(session_id if session_id > 0 else -session_id)

        if session is None:
            self.logger.warning(f"Session {session_id} not found")
            client_sock.sendall(encode_session_id(SESSION_ID_ERROR))
            client_sock.close()
            return

        if session_id < 0:
            # Attach inbound socket
            session.inbound_socket = client_sock
            session.reset_inbound_counters()
            self.logger.info(f"Session {session_id} attached inbound socket")
        else:
            # Attach outbound socket
            session.outbound_socket = client_sock
            session.reset_outbound_counters()
            self.logger.info(f"Session {session_id} attached outbound socket")

        # Send session ID back to proxy-client
        try:
            client_sock.sendall(encode_session_id(session_id))
            self.logger.info(f"Sent session_id={session_id} to proxy-client")
        except Exception as e:
            self.logger.error(f"Error sending session ID: {e}")
            session.close_all_sockets()
            del self.sessions[session_id]
            return



    def run(self) -> None:
        """Run the proxy server."""
        # Create listen socket
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_socket.bind((self.listen_host, self.listen_port))
        self.listen_socket.listen(5)
        
        self.logger.info(
            f"Proxy-Server listening on {self.listen_host}:{self.listen_port}"
        )
        self.logger.info(f"Target server: {self.server_host}:{self.server_port}")
        
        try:
            while True:
                client_sock, addr = self.listen_socket.accept()
                self._handle_client_connection(client_sock, addr)
        except KeyboardInterrupt:
            self.logger.info("Shutting down proxy-server")
        finally:
            if self.listen_socket:
                self.listen_socket.close()
            for session in self.sessions.values():
                session.close_all_sockets()


def main() -> int:
    """Main entry point for proxy-server."""
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=LOG_LEVELS.get(args.log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    server = ProxyServer(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        server_host=args.server_host,
        server_port=args.server_port,
        chunk_size=args.chunk_size,
        max_size=args.max_size,
        max_time=args.max_time,
    )
    
    try:
        server.run()
    except Exception as e:
        logging.error(f"Proxy-server error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())