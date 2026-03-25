# ReconnectProxy Implementation Details

## Table of Contents
1. [Data Structures](#data-structures)
2. [Session States](#session-states)
3. [Logging Configuration](#logging-configuration)
4. [Proxy-Server Algorithms](#proxy-server-algorithms)
5. [Proxy-Client Algorithms](#proxy-client-algorithms)
6. [State Transition Tables](#state-transition-tables)

---

## Data Structures

### Session ID Specification

Session IDs are signed 8-bit integers (-128 to 127).

| ID Range | Meaning | Usage |
|----------|---------|-------|
| `0` | Special value for creating new sessions | Outbound socket only |
| `1-127` | Positive session IDs | Outbound data streams |
| `-127 to -1` | Negative session IDs | Inbound data streams |
| `-128` | Reserved | Not used for session IDs |

### Session (Proxy-Server)

```python
class Session:
    id: int              # Session ID (1-127, signed 8-bit)
    outbound_socket: socket  # Socket from proxy-client (outbound)
    inbound_socket: socket   # Socket from proxy-client (inbound)
    server_socket: socket      # Socket to target server
    state: SessionState        # NEW, PARTIAL, ACTIVE, CLOSED
    bytes_sent_outbound: int   # Bytes sent on outbound socket (MAX_SIZE tracking)
    bytes_sent_inbound: int    # Bytes sent on inbound socket (MAX_SIZE tracking)
    start_time: datetime       # Session start time (for MAX_TIME tracking)
```

### Session (Proxy-Client)

```python
class Session:
    id: int              # Session ID (1-127)
    outbound_socket: socket  # Socket to proxy-server (outbound)
    inbound_socket: socket   # Socket to proxy-server (inbound)
    client_socket: socket      # Socket to local client
    state: SessionState        # NEW, PARTIAL, ACTIVE, CLOSED
    bytes_sent_outbound: int   # Bytes sent on outbound socket (MAX_SIZE tracking)
    bytes_sent_inbound: int    # Bytes sent on inbound socket (MAX_SIZE tracking)
    start_time: datetime       # Session start time (for MAX_TIME tracking)
```

---

## Session States

### Proxy-Server Session States

| State | Description |
|-------|-------------|
| **NEW** | Session created, waiting for proxy-client connection |
| **PARTIAL** | Only one socket established (outbound or inbound) |
| **ACTIVE** | Both sockets (inbound and outbound) established |
| **CLOSED** | Session terminated |

### Proxy-Client Session States

| State | Description |
|-------|-------------|
| **NEW** | Session created, waiting for proxy-server connection |
| **PARTIAL** | Only one socket connected to proxy-server |
| **ACTIVE** | Both sockets (inbound and outbound) connected to proxy-server |
| **CLOSED** | Session terminated |

---

## Logging Configuration

| Level | Purpose | Example Messages |
|-------|---------|------------------|
| **DEBUG** | Detailed packet-level information | Chunk transfer details, socket state changes |
| **INFO** | Connection events | Session establishment, reconnection events |
| **WARNING** | Threshold reached | Chunk size limits, time-based reconnections |
| **ERROR** | Critical failures | Session termination, connection failures |

---

## Proxy-Server Algorithms

### Session Creation (Proxy-Server)

**Trigger**: Outbound socket connection with `session_id=0` from proxy-client

```
1. Connect to target server
2. If connection fails:
   - Send session_id=0 to proxy-client
   - Close socket
   - Return
3. Generate new session ID (1-127)
4. Create session entry with state=NEW
5. Send session_id=<id> to proxy-client
6. Store outbound socket
7. Session state: NEW → PARTIAL
```

### Session Attachment (Proxy-Server)

**Trigger**: Socket connection with `session_id=<id>` from proxy-client

```
1. Look up session in session table
2. If session not found:
   - Send session_id=0 to proxy-client
   - Close socket
   - Return
3. If socket type matches existing socket:
   - Send session_id=0 to proxy-client
   - Close socket
   - Return
4. Attach socket to session
5. Send session_id=<id> back to proxy-client
6. If both sockets connected:
   - Session state: PARTIAL → ACTIVE
```

### Socket Reconnection (Proxy-Server)

**Trigger**: Socket reconnection with `session_id=<id>` after MAX_SIZE/MAX_TIME

```
1. Look up session in session table
2. If session not found:
   - Send session_id=0 to proxy-client
   - Close socket
   - Return
3. Attach socket to session
4. Send session_id=<id> back to proxy-client
5. If both sockets connected:
   - Session state: PARTIAL → ACTIVE
6. Reset bytes_sent counter for reconnected socket
```

### Session Cleanup (Proxy-Server)

**Trigger**: Server closes socket (EOF received from server)

```
1. Receive EOF from server_socket
2. Close all sockets (inbound, outbound, server)
3. Delete session from session table
```

**Note**: Session persists when proxy-client disconnects for potential reconnection.

---

## Proxy-Client Algorithms

### Session Creation (Proxy-Client)

**Trigger**: Client connects to proxy-client

```
1. Create new session with session_id=0, state=NEW
2. Connect to proxy-server with session_id=0 (outbound)
3. Wait for response from proxy-server
4. If response is session_id=0:
   - Delete session
   - Close client connection
   - Return
5. Store session_id
6. Session state: NEW → ACTIVE (outbound connected)
7. Connect to proxy-server with session_id=-session_id (inbound)
8. Wait for response from proxy-server
9. If response is negative session_id:
   - Session state: ACTIVE (both sockets connected)
10. Data transfer begins
```

### Socket Reconnection (Proxy-Client)

**Trigger**: Socket closed by MAX_SIZE or MAX_TIME

```
1. Socket closed (MAX_SIZE/MAX_TIME reached)
2. Session state: ACTIVE → PARTIAL (one socket in reconnect state)
3. Reconnect socket with appropriate session_id:
   - Outbound: session_id=<id>
   - Inbound: session_id=-<id>
4. Wait for response from proxy-server
5. If response is valid session_id:
   - Session state: PARTIAL → ACTIVE (both sockets connected)
6. Reset bytes_sent counter for reconnected socket
```

### Session Cleanup (Proxy-Client)

**Trigger**: Client closes socket (EOF received from client)

```
1. Receive EOF from client_socket
2. Close both sockets (inbound, outbound)
3. Delete session
```

**Note**: Session persists when proxy-server disconnects for potential reconnection.

---

## State Transition Tables

### Proxy-Client State Transitions

| Current State | Event | Next State | Action |
|---------------|-------|------------|--------|
| N/A | Session created | NEW | Initialize session, connect outbound |
| NEW | Outbound socket connected | ACTIVE | Store session ID, connect inbound |
| ACTIVE | Outbound socket closed (MAX_SIZE/MAX_TIME) | PARTIAL | Reset outbound counters, reconnect outbound |
| ACTIVE | Inbound socket closed (MAX_SIZE/MAX_TIME) | PARTIAL | Reset inbound counters, reconnect inbound |
| ACTIVE | Proxy-server disconnect | ACTIVE | Attempt reconnection with session ID |
| ACTIVE | Error response (session_id=0) | CLOSED | Delete session, close client connection |
| PARTIAL | Outbound socket reconnected | ACTIVE | Both sockets connected |
| PARTIAL | Inbound socket reconnected | ACTIVE | Both sockets connected |
| PARTIAL | Client disconnects | CLOSED | Close all sockets, delete session |
| PARTIAL | Proxy-server disconnect | ACTIVE | Attempt reconnection with session ID |
| NEW | Proxy-server disconnect | ACTIVE | Attempt reconnection with session ID |

### Proxy-Server State Transitions

| Current State | Event | Next State | Action |
|---------------|-------|------------|--------|
| N/A | Session created | NEW | Initialize session, connect to server |
| NEW | Outbound socket connected | PARTIAL | Store outbound socket |
| PARTIAL | Inbound socket connected | ACTIVE | Store inbound socket |
| ACTIVE | Outbound socket closed (MAX_SIZE/MAX_TIME) | ACTIVE | Reset outbound counters |
| ACTIVE | Inbound socket closed (MAX_SIZE/MAX_TIME) | ACTIVE | Reset inbound counters |
| ACTIVE | Server disconnects | CLOSED | Close all sockets, delete session |
| ACTIVE | Proxy-client disconnects | ACTIVE | Session persists for reconnection |
| PARTIAL | Proxy-client disconnects | ACTIVE | Session persists for reconnection |
| NEW | Proxy-client disconnects | ACTIVE | Session persists for reconnection |

---

## Data Flow Summary

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

### Reconnection Behavior

| Aspect | Behavior |
|--------|----------|
| **Session State** | Persists (NOT deleted) |
| **Client Connection** | Remains alive |
| **Outbound Reconnect** | Use positive session ID (e.g., `session_id=42`) |
| **Inbound Reconnect** | Use negative session ID (e.g., `session_id=-42`) |
| **Data Counters** | Reset after reconnection |
| **Session Termination** | Only when client/server disconnects |