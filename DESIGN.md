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
2. Proxy-Client connects to Proxy-Server with session_id=0 (outbound)
3. Proxy-Server connects to target server
4. On failure, Proxy-Server sends 0 to Proxy-Client and closes socket
   - Proxy-Client MUST delete the session and close the client connection
5. Proxy-Server creates session, generates ID (e.g., 42)
6. Proxy-Server sends session_id=42 to Proxy-Client
7. Proxy-Client stores session_id=42 for current session and socket is used for outbound data
8. Proxy-Client connects to Proxy-Server with session_id=-42 (inbound)
9. Proxy-Server finds session with id 42, then sends -42 back to Proxy-Client
10. If session is not found, Proxy-Server sends 0 to Proxy-Client and closes socket
    - Proxy-Client MUST delete the session and close the client connection
11. Socket with negative session ID is attached to session and used for inbound data
12. Data transfer is started
13. Proxy-Client use session_id=42 for futher reconnections of inbound and outbound sockets
14. Outbound and inbound sockets are reconnected, reconnect conditions are described below
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

#### Error Cases

```
PROXY-CLIENT                          PROXY-SERVER
     |                                     |
     |---- session_id=0 (new session) ---->|
     |                                     | (server connection fails)
     |                                     | (sends session_id=0 back)
     |<--- session_id=0 (ERROR) -----------|
     | (delete session, close client)      |
     |                                     |
     |---- session_id=-42 (inbound) ------>| 
     |                                     | (session not found)
     |                                     | (sends session_id=0 back)
     |<--- session_id=0 (ERROR) -----------|
     | (delete session, close client)      |
```

## Data Transfer Algorithm

### Outbound Data (Proxy-Client → Proxy-Server)

1. Proxy-client establishes outbound socket to proxy-server with `session_id=0` (new session)
2. Proxy-client waits for response from proxy-server
3. If proxy-server responds with `session_id=0`, the session establishment failed:
   - Proxy-client MUST delete the session
   - Proxy-client MUST close the client connection
   - No further data transfer occurs
4. If proxy-server responds with positive `session_id` (1-127), the session is established
5. Data is sent from proxy-client to proxy-server in chunks with size not more than `CHUNK_SIZE`
6. **Only the sender closes the socket**: Proxy-client closes outbound socket after sending `MAX_SIZE` bytes total (triggers reconnection)
7. **Only the sender closes the socket**: Proxy-client closes outbound socket after `MAX_TIME` seconds (triggers reconnection)
8. Proxy-server keeps inbound socket open to receive any remaining buffered data from the closed socket

### Inbound Data (Proxy-Server → Proxy-Client)

1. Proxy-client establishes inbound socket to proxy-server with `session_id=-session_id` (negative)
2. Proxy-client waits for response from proxy-server
3. If proxy-server responds with `session_id=0`, the session was not found:
   - Proxy-client MUST delete the session
   - Proxy-client MUST close the client connection
   - No further data transfer occurs
4. If proxy-server responds with negative `session_id`, the session is attached
5. Data is sent from proxy-server to proxy-client in chunks with size not more than `CHUNK_SIZE`
6. **Only the sender closes the socket**: Proxy-server closes inbound socket after sending `MAX_SIZE` bytes total (triggers reconnection)
7. **Only the sender closes the socket**: Proxy-server closes inbound socket after `MAX_TIME` seconds (triggers reconnection)
8. Proxy-client keeps outbound socket open to receive any remaining buffered data from the closed socket

### Socket Closing Behavior

**Key Principle**: Only the side that sends data closes its socket when limits are reached. The receiving side keeps its socket open to prevent data loss.

| Direction | Sender | Socket Closed By | Reason |
|-----------|--------|------------------|--------|
| Client → Server | Proxy-Client | Proxy-client on MAX_SIZE/MAX_TIME | Proxy-client sends data to proxy-server |
| Server → Client | Proxy-Server | Proxy-server on MAX_SIZE/MAX_TIME | Proxy-server sends data to proxy-client |

**Data Loss Prevention**:
- When a socket is closed by the sender, the receiver keeps its socket open
- This allows any buffered data in the network to be received
- Session persists until both directions have completed data transfer
- Only when client or server disconnects is the session fully terminated

### Parameters

| Parameter | Description | Default               |
|-----------|-------------|-----------------------|
| CHUNK_SIZE | Maximum size of data chunks for transfer | 16 bytes              |
| MAX_SIZE | Maximum total bytes to transfer before reconnection | 256 bytes      |
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

#### Session Persistence During Socket Reconnection

When a socket is closed by **MAX_SIZE** or **MAX_TIME** limits, the session is **NOT deleted** and both proxy-client and proxy-server maintain their session state:

**Proxy-Client Behavior:**
- Session remains active with stored session ID
- Client connection remains alive
- Proxy-client automatically reconnects to proxy-server using the existing session ID
- Outbound socket reconnects with positive session ID (e.g., `session_id=42`)
- Inbound socket reconnects with negative session ID (e.g., `session_id=-42`)

**Proxy-Server Behavior:**
- Session remains active with stored session ID
- Server connection remains alive
- Proxy-server accepts reconnection with existing session ID
- Session state transitions to ACTIVE when both sockets are reconnected

**Data Transfer Continuation:**
- After reconnection, data transfer continues with fresh byte/time counters
- The session continues until client or server disconnects
- Session is only deleted when client or server closes the connection

**Example Flow:**
```
PROXY-CLIENT                          PROXY-SERVER
     |                                     |
     |---- session_id=42 (outbound) ----->|  (MAX_SIZE or MAX_TIME reached)
     |<--- socket closed ------------------|
     | (session persists)                  |
     |                                     |
     |---- session_id=42 (reconnect) ----->|  (outbound)
     |                                     | (session found, ACTIVE)
     |<--- session_id=42 ------------------|
     |                                     |
     |---- session_id=-42 (inbound) ------>|  (MAX_SIZE or MAX_TIME reached)
     |<--- socket closed ------------------|
     | (session persists)                  |
     |                                     |
     |---- session_id=-42 (reconnect) ----->| (inbound)
     |                                     | (session found, ACTIVE)
     |<--- session_id=-42 -----------------|
     |                                     |
     |<========== DATA TRANSFER ==========>|  (continues)
```

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

#### Outbound Socket Failure (New Session)
- Proxy-server fails to connect to target server
- Proxy-server sends `session_id=0` to Proxy-Client and closes socket
- Proxy-Client MUST:
  1. Delete the session (if any was partially created)
  2. Close the client connection
  3. No reconnection attempt should be made

#### Inbound Socket Failure (Session Not Found)
- Proxy-server receives inbound socket request with unknown session ID
- Proxy-server sends `session_id=0` to Proxy-Client and closes socket
- Proxy-Client MUST:
  1. Delete the session (if any was partially created)
  2. Close the client connection
  3. No reconnection attempt should be made

#### Error Response Semantics
- `session_id=0` is a special error indicator
- It means the session establishment failed
- Proxy-Client MUST NOT attempt to use a session with `session_id=0`
- Proxy-Client MUST clean up all session resources and close the client connection

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