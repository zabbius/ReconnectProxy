# ReconnectProxy Design Document

## Overview

ReconnectProxy is a TCP proxy system consisting of two components: **proxy-client** and **proxy-server**. The system enables transparent proxying of TCP connections with automatic reconnection capabilities and session management.

## Architecture

```
+-----------+     +------------------+     +------------------+     +-----------+
|           |     |                  |     |                  |     |           |
|  Client   |<--->|  Proxy-Client    |<--->|  Proxy-Server    |<--->|  Server   |
| (Local)   |     |  (Listen Port)   |     |  (Proxy Port)    |     | (Remote)  |
|           |     |                  |     |                  |     |           |
+-----------+     +------------------+     +------------------+     +-----------+
```

## Components

### 1. Proxy-Client

**Responsibilities:**
- Listen for incoming client connections on a specified address and port
- Manage sessions with proxy-server
- Handle bidirectional data transfer between client and proxy-server
- Reconnect to proxy-server when connection is lost (if session exists)

**Command Line Arguments:**
```
--listen-port <port>      Port to listen for client connections (required)
--listen-host <host>      Host to bind to for listening (default: 127.0.0.1)
--proxy-port <port>       Port of proxy-server to connect to (required)
--proxy-host <host>       Host of proxy-server to connect to (default: 127.0.0.1)
--chunk-size <bytes>      Maximum size of data chunks for transfer (default: 16)
--max-size <bytes>        Maximum total bytes to transfer before reconnection (default: 256)
--max-time <seconds>      Maximum time in seconds before reconnection (default: 5)
--log-level <level>       Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
```

### 2. Proxy-Server

**Responsibilities:**
- Listen for incoming proxy-client connections on a specified address and port
- Manage sessions (create, store, delete)
- Connect to the target server for each session
- Handle bidirectional data transfer between proxy-client and server

**Command Line Arguments:**
```
--listen-port <port>      Port to listen for proxy-client connections (required)
--listen-host <host>      Host to bind to for listening (default: 127.0.0.1)
--server-port <port>      Port of target server to connect to (required)
--server-host <host>      Host of target server to connect to (default: 127.0.0.1)
--chunk-size <bytes>      Maximum size of data chunks for transfer (default: 16)
--max-size <bytes>        Maximum total bytes to transfer before reconnection (default: 256)
--max-time <seconds>      Maximum time in seconds before reconnection (default: 5)
--log-level <level>       Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
```

## Session Management

### Session ID
- **Range**: 1 to 127 (0 < ID < 128)
- **Session ID 0**: Special value used only for creating new sessions
- **Negative IDs**: Used for inbound data streams (e.g., -42 for session 42)

### Session States
1. **NEW**: Session created, waiting for proxy-client connection
2. **ACTIVE**: Both sockets (inbound and outbound) established
3. **PARTIAL**: Only one socket established
4. **CLOSED**: Session terminated

### Session Lifecycle

```
1. Client connects to Proxy-Client
2. Proxy-Client connects to Proxy-Server with session_id=0
3. Proxy-Server connects to target server
4. On failure, Proxy-Server send 0 to client and closes socket  
5. Proxy-Server creates session, generates ID (e.g., 42)
5. Proxy-Server sends session_id=42 to Proxy-Client
6. Proxy-Client stores session_id=42 for current session and socket is used for outbound data 
7. Proxy-Client connects to Proxy-Server with session_id=-42 (inbound)
8. Proxy-Server find session with id 42, then sends -42 back to Proxy-Client 
9. If session is not found, Proxy-Server sends 0 to Proxy-Client and closes socket
10. Socket with negative session ID is attached to session and use for inbound data
11. Data transfer is started
```

## Data Transfer Protocol

### Socket Types

#### Outbound Socket (Proxy-Client → Proxy-Server)
- Used for: Creating new sessions, sending client-to-server data
- Session ID: Positive integer (1-127) or 0 (for new session)
- Data format: Raw TCP data

#### Inbound Socket (Proxy-Client → Proxy-Server)
- Used for: Sending server-to-client data
- Session ID: Negative integer (-127 to -1)
- Data format: Raw TCP data

### Session Establishment Flow

```
PROXY-CLIENT                          PROXY-SERVER
     |                                     |
     |---- session_id=0 (new session) ---->|
     |                                     | (connects to server)
     |                                     | (creates session, generates ID=42)
     |                                     | (sends session_id=42 back)
     |<--- session_id=42 ------------------|
     |                                     |
     |                                     |
     |---- session_id=-42 (inbound) ------>| 
     |                                     | (sends session_id=-42 back)
     |<--- session_id=-42 -----------------|
     |                                     |
     |<========== DATA TRANSFER ==========>|
```

## Data Transfer Algorithm

### Outbound Data (Proxy-Client → Proxy-Server)

1. Proxy-client establishes outbound socket to proxy-server
2. Data is sent from proxy-client to proxy-server in chunks with size not more than `CHUNK_SIZE`
3. After sending `MAX_SIZE` bytes total, proxy-client closes outbound socket (triggers reconnection)
4. Outbound socket is closed by proxy-client after `MAX_TIME` seconds (triggers reconnection)

### Inbound Data (Proxy-Server → Proxy-Client)

1. Proxy-client establishes inbound socket to proxy-server
2. Data is sent from proxy-server to proxy-client in chunks with size not more than `CHUNK_SIZE`
3. After sending `MAX_SIZE` bytes total, proxy-server closes inbound socket (triggers reconnection)
4. Inbound socket is closed by proxy-server after `MAX_TIME` seconds (triggers reconnection)

### Parameters

| Parameter | Description | Default               |
|-----------|-------------|-----------------------|
| CHUNK_SIZE | Maximum size of data chunks for transfer | 16 bytes              |
| MAX_SIZE | Maximum total bytes to transfer before reconnection | 256 bytes (1 MB)      |
| MAX_TIME | Maximum time in seconds before reconnection | 5 seconds  |

## Connection Handling

### Normal Termination

#### Client Disconnects
1. Proxy-client receives EOF from client
2. Proxy-client closes both sockets (inbound and outbound)
3. Proxy-client deletes session

#### Server Disconnects
1. Proxy-server receives EOF from server
2. Proxy-server closes both sockets (inbound and outbound)
3. Proxy-server deletes session

### Reconnection Scenarios

#### Proxy-Client to Proxy-Server Socket Closed
- If session exists: Reopen socket with session ID
- Outbound: Use positive session ID
- Inbound: Use negative session ID

#### Reconnection Triggers
1. **MAX_SIZE reached**: Socket closed after transferring maximum allowed bytes
2. **MAX_TIME elapsed**: Socket closed after maximum time duration
3. **Connection lost**: Network failure triggers automatic reconnection
4. **Session cleanup**: Session deleted after normal termination

## Data Flow

### Client → Server Direction
```
Client → Proxy-Client (outbound socket, +session_id)
       → Proxy-Server (outbound socket, +session_id)
       → Server
```

### Server → Client Direction
```
Server → Proxy-Server (inbound socket, -session_id)
       → Proxy-Client (inbound socket, -session_id)
       → Client
```

## Error Handling

### Session ID Conflicts
- Proxy-server maintains session ID counter
- Wraps around after 127
- Skips 0 (reserved for new session creation)

### Session Not Found
- Proxy-server receives unknown session ID
- Proxy-server sends session_id=0 and closes socket
- Proxy-client closes client connection

## Implementation Details

### Data Structures

#### Session (Proxy-Server)
```python
class Session:
    id: int              # Session ID (1-127)
    outbound_socket: socket  # Socket from proxy-client (outbound)
    inbound_socket: socket   # Socket from proxy-client (inbound)
    server_socket: socket      # Socket to target server
    state: SessionState        # NEW, ACTIVE, PARTIAL, CLOSED
    bytes_sent: int            # Total bytes sent (for MAX_SIZE tracking)
    start_time: datetime       # Session start time (for MAX_TIME tracking)
```

#### Session (Proxy-Client)
```python
class Session:
    id: int              # Session ID (1-127)
    outbound_socket: socket  # Socket to proxy-server (outbound)
    inbound_socket: socket   # Socket to proxy-server (inbound)
    client_socket: socket      # Socket to local client
    state: SessionState        # ACTIVE, CLOSED
    bytes_sent: int            # Total bytes sent (for MAX_SIZE tracking)
    start_time: datetime       # Session start time (for MAX_TIME tracking)
```

### Logging

Log levels:
- **DEBUG**: Detailed packet-level information, chunk transfer details
- **INFO**: Connection establishment/teardown events, reconnection events
- **WARNING**: Chunk size limits reached, time-based reconnections
- **ERROR**: Critical failures, session termination

## Command Line Examples

### Start Proxy-Server
```bash
python proxy_server.py \
    --listen-port 1080 \
    --listen-host 0.0.0.0 \
    --server-port 8080 \
    --server-host 192.168.1.100 \
    --chunk-size 8192 \
    --max-size 1048576 \
    --max-time 300 \
    --log-level INFO
```

### Start Proxy-Client
```bash
python proxy_client.py \
    --listen-port 8080 \
    --listen-host 127.0.0.1 \
    --proxy-port 1080 \
    --proxy-host 192.168.1.100 \
    --chunk-size 8192 \
    --max-size 1048576 \
    --max-time 300 \
    --log-level INFO
```

### Full Flow Example
```bash
# Terminal 1: Start proxy-server with custom parameters
python proxy_server.py \
    --listen-port 1080 \
    --server-port 80 \
    --chunk-size 4096 \
    --max-size 524288 \
    --max-time 60

# Terminal 2: Start proxy-client with custom parameters
python proxy_client.py \
    --listen-port 8080 \
    --proxy-port 1080 \
    --chunk-size 4096 \
    --max-size 524288 \
    --max-time 60

# Terminal 3: Connect to proxy-client
curl --proxy localhost:8080 http://example.com