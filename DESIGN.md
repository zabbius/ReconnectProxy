# ReconnectProxy Design Document

## Overview

ReconnectProxy is a transparent TCP proxy system with automatic reconnection capabilities. It consists of two components:
- **proxy-client**: Local endpoint that clients connect to
- **proxy-server**: Remote endpoint that connects to the target server

The system maintains session persistence across socket reconnections, enabling seamless data transfer even when network interruptions occur.

## Architecture

```
+---------+     +-------------+     +-------------+     +----------+
| Client  |<--->| Proxy-Client|<--->| Proxy-Server|<--->| Server   |
+---------+     +-------------+     +-------------+     +----------+
```

### Socket Types per Session

| Socket | Direction | Established By | Reconnection Behavior |
|--------|-----------|----------------|----------------------|
| Client ↔ Proxy-Client | Bidirectional | Proxy-Client | Never |
| Proxy-Server ↔ Server | Bidirectional | Proxy-Server | Never |
| Outbound (unidirectional) | Proxy-Client → Proxy-Server | Proxy-Client | Closed by Proxy-Client on MAX_SIZE/MAX_TIME |
| Inbound (unidirectional) | Proxy-Server → Proxy-Client | Proxy-Client | Closed by Proxy-Server on MAX_SIZE/MAX_TIME |

## Session Management

### Session ID Specification

| ID Range | Meaning | Usage |
|----------|---------|-------|
| `0` | Special value for creating new sessions | Outbound socket only |
| `1-127` | Positive session IDs | Outbound data streams |
| `-127 to -1` | Negative session IDs | Inbound data streams |

**Session ID Rules:**
1. Session ID is an 8-bit signed integer
2. Session ID `0` is reserved for new session creation only
3. Negative IDs represent inbound data streams (e.g., `-42` for session `42`)
4. Session IDs wrap around after 127 (counter resets to 1)
5. Session ID `0` received as a response indicates an error

### Session State

Each session maintains:
- `session_id`: The positive session identifier (1-127)
- `outbound_socket`: Socket for client→server data flow
- `inbound_socket`: Socket for server→client data flow
- `client_socket`: Socket connected to the original client
- `server_socket`: Socket connected to the target server
- `outbound_bytes_sent`: Bytes sent on outbound socket (reset on reconnect)
- `inbound_bytes_sent`: Bytes sent on inbound socket (reset on reconnect)
- `outbound_time_started`: Timestamp when outbound socket was created/reconnected
- `inbound_time_started`: Timestamp when inbound socket was created/reconnected

### Session Lifecycle

```
1. Client connects to Proxy-Client
2. Proxy-Client creates session with session_id=0
3. Proxy-Client connects to Proxy-Server with session_id=0 (outbound)
4. Proxy-Server connects to target server
5. Proxy-Server generates session_id (e.g., 42) and sends it to Proxy-Client
6. Proxy-Client stores session_id=42 for outbound data
7. Proxy-Client connects with session_id=-42 (inbound)
8. Proxy-Server finds session, sends -42 back
9. Session becomes ACTIVE, bidirectional data transfer begins
10. After MAX_TIME seconds or MAX_SIZE bytes, outbound socket reconnects
11. After MAX_TIME seconds or MAX_SIZE bytes, inbound socket reconnects
12. Session persists across socket reconnections
13. Session terminates when client or server disconnects
```

## Data Transfer Algorithm

### Key Principle: Sender-Closes-Only

**Only the side that sends data closes its socket when limits are reached. The receiving side keeps its socket open to prevent data loss.**

### Outbound Data Flow (Proxy-Client → Proxy-Server)

1. Proxy-client establishes socket with `session_id=0` (new session)
2. Wait for proxy-server response
3. If response is `session_id <= 0`:
   - Delete session
   - Close client connection
   - No further transfer
4. If response is positive `session_id (1-127)`:
   - Session established
   - Send data in chunks (≤ CHUNK_SIZE)
   - Track `bytes_sent` and `time_started`
   - Close socket after `MAX_SIZE` bytes OR `MAX_TIME` seconds
   - Proxy-server keeps socket open for buffered data

### Inbound Data Flow (Proxy-Server → Proxy-Client)

1. Proxy-client establishes socket with negative `session_id (-42)`
2. Wait for proxy-server response
3. If response is `session_id >= 0`:
   - Delete session
   - Close client connection
   - No further transfer
4. If response is negative `session_id`:
   - Session attached
   - Send data in chunks (≤ CHUNK_SIZE)
   - Track `bytes_sent` and `time_started`
   - Close socket after `MAX_SIZE` bytes OR `MAX_TIME` seconds
   - Proxy-client keeps socket open for buffered data

### Reconnection Behavior

When a socket is closed by **MAX_SIZE** or **MAX_TIME** limits:

| Aspect | Behavior |
|--------|----------|
| **Session State** | Persists (NOT deleted) |
| **Client Connection** | Remains alive |
| **Outbound Reconnect** | Use positive session ID (e.g., `session_id=42`) |
| **Inbound Reconnect** | Use negative session ID (e.g., `session_id=-42`) |
| **Data Counters** | Reset after reconnection for corresponding flow direction |
| **Session Termination** | Only when client/server disconnects |

## Component Specifications

### Proxy-Client

#### Command Line Arguments

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `--listen-port <port>` | Port to listen for client connections | - | Yes |
| `--listen-host <host>` | Host to bind to for listening | `127.0.0.1` | No |
| `--proxy-port <port>` | Port of proxy-server to connect to | - | Yes |
| `--proxy-host <host>` | Host of proxy-server to connect to | `127.0.0.1` | No |
| `--chunk-size <bytes>` | Maximum size of data chunks for transfer | `16` | No |
| `--max-size <bytes>` | Maximum total bytes to transfer before reconnection | `256` | No |
| `--max-time <seconds>` | Maximum time in seconds before reconnection | `5` | No |
| `--log-level <level>` | Log level: DEBUG, INFO, WARNING, ERROR | `INFO` | No |

#### Proxy-Client Algorithms

##### Session Creation (Proxy-Client)

**Trigger**: Client connects to proxy-client

1. Create new session with `session_id=0`
2. Connect to proxy-server with `session_id=0` (outbound)
3. Wait for response from proxy-server
4. If response is `session_id <= 0`:
   - Delete session
   - Close client connection
   - Return
5. Store received `session_id` in session
6. Outbound transfer begins
7. Attach inbound socket (see below)

##### Socket Reconnection (Proxy-Client)

**Trigger**: Socket closed due to MAX_SIZE/MAX_TIME limits

1. Session has closed socket to proxy-server
2. Reconnect socket with appropriate `session_id`:
   - Outbound: `session_id=<id>`
   - Inbound: `session_id=-<id>`
3. Wait for response from proxy-server
4. If `session_id` from response equals request:
   - Store socket to the session
   - Reset `bytes_sent` counter for reconnected socket
5. If `session_id` from response is NOT equal to request:
   - Clear the session and disconnect the client

##### Session Cleanup (Proxy-Client)

**Trigger**: Client closes socket (EOF received from client)

1. Receive EOF from `client_socket`
2. Close both sockets (inbound, outbound)
3. Delete session

##### Data Transfer Loop (Proxy-Client)

For each session, run two concurrent loops:

**Outbound Loop**:
```
while session exists and client_socket is open:
    data = client_socket.recv(CHUNK_SIZE)
    if data is empty:
        break
    send data on outbound_socket
    bytes_sent += len(data)
    if bytes_sent >= MAX_SIZE or time_since_start >= MAX_TIME:
        close outbound_socket
        reconnect outbound_socket with session_id
        bytes_sent = 0
        time_started = now
```

**Inbound Loop**:
```
while session exists and server_socket is open:
    data = inbound_socket.recv(CHUNK_SIZE)
    if data is empty:
        break
    send data to client_socket
    bytes_sent += len(data)
    if bytes_sent >= MAX_SIZE or time_since_start >= MAX_TIME:
        close inbound_socket
        bytes_sent = 0
        time_started = now
        # Wait for proxy-server to close its side
        # Then reconnect inbound_socket with session_id
```

### Proxy-Server

#### Command Line Arguments

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `--listen-port <port>` | Port to listen for proxy-client connections | - | Yes |
| `--listen-host <host>` | Host to bind to for listening | `127.0.0.1` | No |
| `--server-port <port>` | Port of target server to connect to | - | Yes |
| `--server-host <host>` | Host of target server to connect to | `127.0.0.1` | No |
| `--chunk-size <bytes>` | Maximum size of data chunks for transfer | `16` | No |
| `--max-size <bytes>` | Maximum total bytes to transfer before reconnection | `256` | No |
| `--max-time <seconds>` | Maximum time in seconds before reconnection | `5` | No |
| `--log-level <level>` | Log level: DEBUG, INFO, WARNING, ERROR | `INFO` | No |

#### Proxy-Server Algorithms

##### Session Creation (Proxy-Server)

**Trigger**: Outbound socket connection with `session_id=0` from proxy-client

1. Connect to target server
2. If connection fails:
   - Send `session_id=0` to proxy-client
   - Close socket
   - Return
3. Generate new session ID (1-127)
4. Create session entry
5. Send `session_id=<id>` to proxy-client
6. Store outbound socket in session

##### Socket Reconnection (Proxy-Server)

**Trigger**: Socket connection with `session_id=<id>` from proxy-client

1. Look up session in session table (look for `-<id>` if `<id> < 0`)
2. If session not found:
   - Send `session_id=0` to proxy-client
   - Close socket
   - Return
3. Attach socket to session (outbound for positive `<id>`, inbound for negative)
4. Send `session_id=<id>` back to proxy-client

##### Session Cleanup (Proxy-Server)

**Trigger**: Server closes socket (EOF received from server)

1. Receive EOF from `server_socket`
2. Close all sockets (inbound, outbound, server)
3. Delete session from session table

**Note**: Session persists when proxy-client disconnects for potential reconnection.

##### Data Transfer Loop (Proxy-Server)

For each session, run two concurrent loops:

**Outbound Loop** (receives from proxy-client, forwards to server):
```
while session exists and server_socket is open:
    data = outbound_socket.recv(CHUNK_SIZE)
    if data is empty:
        break
    send data to server_socket
    bytes_sent += len(data)
    if bytes_sent >= MAX_SIZE or time_since_start >= MAX_TIME:
        close outbound_socket
        bytes_sent = 0
        time_started = now
        # Proxy-client will reconnect outbound_socket
```

**Inbound Loop** (receives from server, forwards to proxy-client):
```
while session exists and server_socket is open:
    data = server_socket.recv(CHUNK_SIZE)
    if data is empty:
        break
    send data on inbound_socket
    bytes_sent += len(data)
    if bytes_sent >= MAX_SIZE or time_since_start >= MAX_TIME:
        close inbound_socket
        bytes_sent = 0
        time_started = now
        # Proxy-client will reconnect inbound_socket
```

## Protocol Specification

### Session Establishment Protocol

#### Outbound Socket (New Session)

```
Proxy-Client                          Proxy-Server
     |                                   |
     |------ session_id=0 (new) ------>|
     |                                   | (connects to server)
     |<----- session_id=42 (success) ---|
     |                                   |
     |--- session_id=42 (attach) ----->|
     |                                   |
     |<-- session_id=42 (confirmed) ----|
```

#### Inbound Socket (Attach to Existing Session)

```
Proxy-Client                          Proxy-Server
     |                                   |
     |--- session_id=-42 (attach) ----->|
     |                                   |
     |<-- session_id=-42 (confirmed) ----|
```

### Error Response Protocol

```
Proxy-Client                          Proxy-Server
     |                                   |
     |------ session_id=X ------------>|
     |                                   |
     |<----- session_id=0 (error) ------|
     |                                   |
     | (close socket, delete session)
```

## Configuration Parameters

| Parameter | Description | Default | Unit |
|-----------|-------------|---------|------|
| `CHUNK_SIZE` | Maximum size of data chunks for transfer | `16` | bytes |
| `MAX_SIZE` | Maximum total bytes to transfer before reconnection | `256` | bytes |
| `MAX_TIME` | Maximum time in seconds before reconnection | `5` | seconds |

## Logging

All components log to stdout with configurable log level (DEBUG, INFO, WARNING, ERROR).

### Log Format
```
[YYYY-MM-DD HH:MM:SS] [LEVEL] [Component] [Session ID] Message
```

### Log Levels

- **DEBUG**: Detailed information about socket connections, data transfers, and session operations
- **INFO**: Session creation/deletion, connection events
- **WARNING**: Unexpected but recoverable conditions
- **ERROR**: Error conditions that may affect operation

## Error Handling

### Session ID Conflicts

- Proxy-server maintains a session ID counter
- Wraps around after 127 (resets to 1)
- Skips 0 (reserved for new session creation)

### Session Failure Scenarios

#### Outbound Socket Failure

**Scenarios**:
- Proxy-server fails to connect to target server
- Target server closed connection to Proxy-server
- Specified session ID is not found on proxy-server

**Action Sequence**:
1. Proxy-client sends `session_id >= 0` to (re)attach outbound socket
2. Proxy-server sends `session_id=0` to Proxy-Client
3. Proxy-server closes socket
4. Proxy-Client MUST:
   - Delete the session (if any was partially created)
   - Close the client connection
   - No reconnection attempt should be made

#### Inbound Socket Failure (Session Not Found)

**Scenarios**:
- Target server closed connection to Proxy-server
- Specified session ID is not found on proxy-server

**Action Sequence**:
1. Proxy-client sends `session_id < 0` to (re)attach inbound socket
2. Proxy-server sends `session_id=0` to Proxy-Client
3. Proxy-server closes socket
4. Proxy-Client MUST:
   - Delete the session (if any was partially created)
   - Close the client connection
   - No reconnection attempt should be made

## Implementation Notes

### Python Version

Requires Python >= 3.13

### File Structure

```
src/
├── __init__.py
├── common/
│   ├── __init__.py
│   ├── session.py          # Session management
│   ├── protocol.py         # Protocol constants and helpers
│   └── logging.py          # Logging configuration
├── proxy_client/
│   ├── __init__.py
│   ├── main.py             # CLI entry point
│   ├── server.py           # Client listener
│   └── connector.py        # Proxy-server connections
└── proxy_server/
    ├── __init__.py
    ├── main.py             # CLI entry point
    ├── server.py           # Proxy-client listener
    └── connector.py        # Target server connections
```

### Threading Model

- Each session runs in its own thread
- Outbound and inbound data transfer run in separate threads
- Use non-blocking I/O with select/poll for efficient concurrent handling

### Error Recovery

- Socket reconnection handles transient network failures
- Session state persists across socket reconnections
- Graceful shutdown on SIGTERM/SIGINT