# Bounded QUIC versus persistent TCP + mTLS experiment

**Experimental, opt-in, no performance result yet.** This tool answers whether reliable QUIC streams
reduce warm serial RPC latency for CPU-expert-sized traffic on a gigabit LAN. It does not load a model,
change a production default, or establish inference TPS. A negative result ends this investigation;
a positive result only motivates a separately authorized minimal inference integration.

## Source and transport choices

InferSwarm is the research/evidence owner, so this isolated benchmark lives here. Strata's pinned
source is an input, not copied or modified in this PR:
`Zutfen-LLC/Strata@45d0493640b43e6264bd6d52da02a0ae5bf061cf`.
`build.rs` verifies SHA-256 of its three actual TLS/socket inputs before compilation.

The TCP arm calls the unchanged `TlsSession::handshake/send_all/recv_all` in
`src/worker/wire_sock.cpp`, through a small ABI shim. It retains OpenSSL TLS 1.3 minimum,
dedicated CA trust, required peer certificates, exact SAN DNS matching (no CN or wildcard), disabled
session cache/tickets/early data, full writes and header-then-payload full reads. The client enables
TCP_NODELAY; the server's explicit 0/1 argument must match the retained baseline. Both arms send one
whole frame per write, without application buffering, compression or delayed batching.

The QUIC arm pins **Quinn 0.11.11**, rustls 0.23.43 with ring, and all transitive versions/checksums in
Cargo.lock. It uses one reused connection and one reused reliable bidirectional stream, one outstanding
request, no unreliable datagrams, no migration, no 0-RTT and no resumption. It requires the same CA and
mutual certificates, plus the same exact SAN DNS policy through OpenSSL's `X509_check_host` after rustls
chain/signature verification and before application processing. Both transports run their application
loop on one thread. Quinn's event driver runs on the same single-thread Tokio runtime. Poll versus event
driver, crypto provider, congestion/ACK policy and implementation costs are part of this comparison;
it is not a controlled estimate of UDP alone. Record OpenSSL/Rust versions and negotiated ciphers if the
existing observer exposes them; an unexplained cipher difference limits attribution.

References: [Quinn reliable stream API](https://docs.rs/quinn/0.11.11/quinn/),
[rustls client authentication](https://docs.rs/rustls/0.23.43/rustls/server/struct.WebPkiClientVerifier.html).

**Source applicability caveat:** at this Strata revision the CPU `ExpertWorkerClient` itself still calls
plain socket helpers; `TlsSession` is also used by the native network worker path. This benchmark uses
the real TLS primitive with the CPU SEW1 frames, rather than claiming that this exact CPU client already
wires it in. Before a LAN run, reconcile the retained deployed CPU transport source/configuration with
the claimed direct TCP+mTLS baseline. If it uses another adapter, tunnel, relay, cipher policy or framing,
STOP for that concrete reconciliation. Do not silently compare against plaintext or SSH.

## Source-derived traffic, not approximate averages

Read `include/strata/worker/expert_wire.hpp` and `src/worker/expert_wire.cpp` at the pinned revision:

* SEW1 header: magic 4 + type 2 + status 2 + little-endian payload length 8 = 16 bytes.
* F32 INFER payload: 36 fixed + T*K*(1 mask + 2 ID + 4 weight) + T*H*4 activation bytes.
* Reduced ACK: 16 fixed + T*H*4 bytes, plus header.
* Entry-row ACK: 20 fixed + R*(2 index + H*4 F32 row) bytes, plus header. R is the routed entry count.

This tool fixes H=2560 and K=10. T and R are explicit; R=0 selects reduced replies, R>0 entry rows.
It constructs source-shaped requests/replies with finite synthetic F32 bit patterns and deterministic
IDs/weights. Every receiver compares **every byte**, including header, session and sequence, before
continuing. The sequential chain cannot issue request N+1 until reply N has passed integrity.
No model payload, prompt, trace or private per-call record is published. No numerical loss is introduced.
The synthetic responder performs no expert computation, activation quantization or row reduction.
It tests transport/framing, not actual inference scheduling or sensitivity to data-dependent computation.

CALCULATED source-valid examples (full application frame lengths, not Ethernet wire bytes):

| T | R / format | request | reply |
|---|---|---:|---:|
| 1 | reduced | 10,362 | 10,272 |
| 2 | reduced | 20,672 | 20,512 |
| 1 | 5 entry rows | 10,362 | 51,246 |
| 1 | 9 entry rows | 10,362 | 92,214 |

The pinned historical `docs/cpu-rpc-replay/HERMES.md` retains separate T1/T2 reduced-reply populations;
those do not establish an entry-row frequency distribution. The approximately 49 KB reply description is
not a specification or per-call histogram. R=5 is a synthetic near-size screen, **not measured typical R**.
Before launch, select one source-valid shape from retained nonprivate size metadata. If it differs from
the examples, freeze it explicitly rather than averaging discrete frames. The initial run has no second
independent-stream case: it would not remove the serial layer dependency.

## Build and focused local checks

Prerequisites: retained Rust/Cargo compatible with the lockfile (tested rustc 1.97.0), C++20 compiler,
OpenSSL development libraries and the exact Strata source. No CUDA, model, credential or listener needed
for these tests. Use existing caches; no implicit download or toolchain installation.

```sh
export STRATA_SOURCE=/path/to/clean/verified/Strata
cd tools/quic-rpc
cargo test --offline --locked
cargo clippy --offline --locked --all-targets -- -D warnings
cargo fmt --check
cargo build --offline --locked --release -j2
sha256sum target/release/inferswarm-quic-rpc
```

Focused tests cover all supported T and selected R frame lengths, sequence offsets, finite F32 bytes,
single-bit corruption, malformed magic/type/status/length, fragmented reads, truncation, finite timeout
and nearest-rank percentile reduction. They do not establish TLS handshakes, QUIC interoperability or
network cleanup. Those gates require verified existing authorized test credentials; no certificate is
generated here. Missing cached dependencies or credentials are explicit prerequisites.

The prepared [local-smoke procedure](SMOKE.md) and `smoke.py`/`smoke_peer` provide a finite loopback
execution path once the parent supplies and releases the approved test setup. They are not a permission
to launch listeners; the actual authenticated cases below remain pending.

## Authenticated interoperability gate — all cases pending

Independent source review found no source blocker for a local authenticated smoke. That is not
handshake, LAN or performance qualification. **Do not launch even loopback listeners until the parent
supplies the approved certificate/test setup and bounded local-smoke dispatch.** Do not issue, renew,
modify or generate certificates, or change the system clock to manufacture an expiry test.

Before declaring the producer ready for LAN, retain the following actual socket/stream cases for
**both TCP and QUIC**. Every case below is **NOT RUN**; unit tests and missing-file CLI failures do not
satisfy any handshake or real-network failure case.

| Case | Required observation / prerequisite |
|---|---|
| Valid mutual authentication | Both roles verify the peer, complete exact-byte exchanges, finish once and exit 0; same role credentials and dedicated CA trust across transports. |
| Wrong server SAN | Client rejects the actual presented server certificate's identity; no successful exchange. |
| Wrong client SAN | Server rejects the actual presented client certificate's identity; no successful exchange. |
| Untrusted peer, each direction | Actual presented peer chains to a retained untrusted test CA; verifier rejects it. Requires approved existing negative fixtures. |
| Expired peer, each direction | Actual presented peer is expired at the unchanged current clock; verifier rejects it. Requires an approved existing expired fixture and a presenting test peer able to send it. |
| No client certificate | An actual certificate-free TLS/QUIC test client reaches the server handshake and is rejected. Passing a missing filename to this benchmark only proves CLI/configuration refusal and does not test this case. |
| Wrong EKU, each direction | Actual presented peer has an unsuitable serverAuth/clientAuth purpose and is rejected. Requires approved existing negative fixtures. |
| Incomplete chain, each direction | Required intermediate is omitted from the presented chain and is absent from dedicated verifier trust; handshake is rejected. An absent root alone is not an incomplete-chain test. |
| Disconnect / truncation | Close the owned connection/stream during a header and during a payload; observe finite failure, no accepted partial exchange and owned cleanup. |
| No progress / timeout | Stalled handshake, frame read and frame write reach their finite bounds and clean up. This requires actual peers/streams and bounded backpressure, not just the in-memory read-timeout unit test. |
| Final close | Repeated valid exchanges deliver the final full reply and final acknowledgment/FIN, then both roles exit cleanly with no lingering listener/process. |

The current benchmark intentionally requires a local certificate and key in both roles. It is therefore
not itself a certificate-free test client. Negative certificate cases may also need a dedicated existing
test peer that can present the approved invalid fixture. Those test adapters and fixtures must be
identified with the parent's setup; they are prerequisites, not implemented or silently waived here.
Expected authentication refusals count as passing negative cases only when the intended handshake was
actually reached and the verifier's rejection is retained. Missing fixtures, access or a presenting-peer
capability leave the named case pending. No fallback to plaintext or relaxed verification is allowed.

## Minimal two-host Hermes recipe — prepare now, run separately

Do not SSH to or run this on fleet hosts under this PR. Do not overlap the active CUDA/Vulkan work.
The parent must dispatch a separate finite LAN slot after that work is clean. No model unload, new
service framework, firewall/VPN/NIC/clock changes, credential issuance or production transport changes.
Use existing authorized direct-LAN test endpoints and certificate access. If those are missing, return
the exact required access/credential action for approval. Do not bypass mTLS.

1. Freeze the InferSwarm PR commit, Strata SHA, Cargo.lock SHA, exact source-file hashes and binary
   SHA-256; use the identical Release executable on both hosts. Record compiler, OpenSSL shared-library
   identities, OS/kernel, CPU, affinity, negotiated gigabit link, MTU, route and NIC offload/coalescing
   state read-only. Keep those settings fixed. Verify route is direct LAN, without SSH or a proxy.
2. Read only the existing test CA and leaf certificates: verify validity period, complete chain,
   serverAuth/clientAuth EKUs and the exact counterpart SAN DNS identities. Check each private key's
   public-key digest matches its leaf without outputting the private key. Retain local receipt paths
   privately. Both binaries must read the same CA trust; use the same role certificate in both arms.
   Check current production accepted-socket NODELAY and reconcile the CPU mTLS applicability caveat.
3. Reserve **one application CPU per role**, matched affinity and host load between arms; no busy polling.
   Retain inherited process/cgroup resource controls: memory limit 256 MiB per role, no swap, existing
   host reserve and health controls. No GPU. The process contains one connection and bounded samples
   (maximum 256 measured + 16 warmup chains, 52 exchanges each); use only the smaller counts below.
   Use the retained exact-owned supervisor with **180-second wall limit per pair** and **900-second
   whole four-pair limit**. Each setup/read/write has a 10-second internal bound (TCP header/payload are
   separate production operations). Kill only the pair's recorded PIDs on deadline/failure; retain all
   logs/exits and verify their listeners/descriptors are gone. No retries or count/timeout extensions.
4. Complete the separately dispatched authenticated interoperability gate above with the approved
   existing certificate/test setup. Use T=1/R=5, 1 measured chain and 0 warmup for the positive smoke;
   bound every negative case separately in that dispatch. No local smoke is authorized by this recipe
   alone. All required cases must have actual passing receipts before the LAN slot; missing negative
   fixtures or test-peer capability remain pending. These are correctness gates, not timings. Stop on
   an unexpected outcome. Use the same executable on both hosts; no production worker replacement.
5. Freeze one actual source-compatible T/R shape using retained size metadata. Run **TCP, QUIC, QUIC,
   TCP** in that order, same direction, shape, counts and affinity. Each pair has **2 warmup chains**
   (104 exchanges, discarded) and **16 measured chains** (832 exchanges), always 52 dependent exchanges
   per chain. Start one owned server process, then its owned client within its 10-second accept budget;
   let both exit before starting the next pair. No extra warmups. A second shape needs its own explicitly
   budgeted four-pair slot; do not silently multiply the initial run.

Generic invocation on each role (all variables resolved privately from the verified receipt):

```sh
# Server, selected non-wildcard numeric IPv4 bind + port; peer address restricted before application I/O.
# ROLE_CPU is the reserved valid CPU; OUT is a fresh private artifact directory.
timeout --signal=TERM --kill-after=5s 180s taskset -c "$ROLE_CPU" "$BIN" \
  server "$TRANSPORT" "$SERVER_ADDR" "$SERVER_ADDR" "$CLIENT_IP" \
  "$CA" "$SERVER_CERT" "$SERVER_KEY" "$CLIENT_DNS" \
  "$T" "$R" 16 2 "$ACCEPTED_NODELAY" 1 >"$OUT/server.json" 2>"$OUT/server.stderr"

# Client: LOCAL_BIND is this client's verified numeric IPv4 address with port 0.
timeout --signal=TERM --kill-after=5s 180s taskset -c "$ROLE_CPU" "$BIN" \
  client "$TRANSPORT" "$SERVER_ADDR" "$CLIENT_IP:0" "$SERVER_IP" \
  "$CA" "$CLIENT_CERT" "$CLIENT_KEY" "$SERVER_DNS" \
  "$T" "$R" 16 2 "$ACCEPTED_NODELAY" 1 >"$OUT/client.json" 2>"$OUT/client.stderr"
```

`TRANSPORT` is `tcp` or `quic`. The supervisor starts/stops only these foreground children; it must
preserve each actual exit code. Capture both stdout and stderr even after STOP. Shell `timeout` is an
additional bound and does not replace the retained resource/health/ownership supervisor. Do not start
both roles on a fleet host from an ad hoc background shell. Unrelated services remain untouched.

## Result contract and decision

Require both exits 0, exactly one success JSON each, exact matching shape/configuration, completed=832,
errors=0, application_retries=0 and integrity=`all bytes exact`. Any mismatch, deadline, refusal,
missing sensor/resource control or cleanup failure means STOP; preserve the earliest failure. There
is no reconnect/replay fallback. Partial RPC failures emit completed counts and failing chain/exchange.

Keep setup/ready duration outside warm timing; server setup includes waiting for the client and is not
handshake-only latency. Client per-RPC p50/p95/p99 includes full send, full receive and exact validation.
Each 52-exchange chain is timed directly, not estimated as 52 times a percentile. Raw bounded samples,
chain samples and CPU user/system deltas are emitted for both roles. Server RPC timing includes waiting
for the next request and must not be subtracted from client RTT across unsynchronized clocks.
OpenSSL's synchronous full write and Quinn's event-driven write acceptance have different completion
semantics: a successful Quinn write can still have queued data. Compare the client's **full-response**
timing and directly measured chains, not server send completion. CPU deltas end before the final
acknowledgment, close and endpoint drain; cleanup and late-ACK CPU work are excluded. Report that scope
explicitly rather than calling it total process CPU cost.

QUIC UDP payload byte/loss counters are warm snapshot deltas; they exclude IP/Ethernet overhead and
late ACKs. TCP wire bytes remain null. TCP now has the read-only per-socket diagnostics described below;
unavailable fields remain null. Never call application/TCP payload bytes wire bytes or lost packets
application retries. No additional packets, peer messages, sleeps or socket-option writes are used.

### TCP_INFO diagnostic snapshots (Linux)

Both TCP roles call `getsockopt(IPPROTO_TCP, TCP_INFO)` on their existing owned `TcpStream` descriptor,
through the existing C++ FFI seam. The start snapshot is taken after warmup, **before** `getrusage` and
the warm wall-clock start. The end snapshot is taken **after** the warm wall-clock and CPU counters stop,
before report generation, final acknowledgment and socket close. Snapshot/decoder/serialization CPU
and wall cost are excluded from the measured scopes. QUIC code, timing and report fields are unchanged.

`tcp_info.start` and `.end` retain availability, errno, requested/returned byte lengths, raw native-endian
hex and each decoded field's offset, width, unit, kind, support and value. TCP_INFO has no explicit
kernel ABI version: `abi_version` is null, kernel release and native byte order are recorded, and the
decoder identifies its known 248-byte Linux UAPI prefix. Every complete field must fit the actual
returned length. Older kernels' absent fields are **null**, not zero-filled observations. Newer kernel
suffix bytes are preserved raw. A returned length beyond the 1024-byte request is marked truncated.
An unsupported/failed syscall retains errno and no invented length, raw bytes or field values.

`tcp_info.cumulative_deltas` contains end minus start only for cumulative counters present at both
snapshots: total retransmitted segments, retransmitted payload bytes, segment/byte/delivery counts,
DSACK/reordering/out-of-order counters, busy/receive-window-limited/send-buffer-limited time and newer
total-RTO/recovery/time counters where available. Counter decreases or possible wraps produce null
with `counter_decreased_or_wrapped`; no wrap count is guessed. Top-level `tcp_retransmits` aliases the
supported **`tcpi_total_retrans` delta**, otherwise null. These Linux segment counts are not physical
Ethernet-frame counts; TCP byte counters include TLS records and are not application or wire bytes.

Do **not** difference snapshot gauges as event counts. In particular, `tcpi_lost` is current inferred
lost/outstanding segments; `tcpi_retrans` is retransmitted segments currently outstanding;
`tcpi_retransmits` is the current RTO-retry state, not lifetime total retransmissions. RTT/RTT variance,
RTO/ATO (microseconds), congestion window/threshold (segments), MSS/path MTU, current scaled advertised
windows, not-sent bytes, pacing/delivery estimates and state/backoff are raw start/end observations.
`tcpi_rcv_space` is a receive-space estimate, not the advertised receive window; use `tcpi_rcv_wnd`
when available. `tcpi_min_rtt` is a connection-lifetime minimum and may include setup/warmup. Rates,
sentinels and enum/bitmask values remain raw. Reference layout: Linux `include/uapi/linux/tcp.h`.

The snapshot interval slightly surrounds the local measured interval; it does not synchronize hosts
or wait for final ACKs. A server's last full write can finish before its last reply is delivered, and
retransmissions/ACK work after its end snapshot are excluded. In-flight warmup work can cross the start
boundary. These diagnostics attribute observations to this connection and local window, not a claim
that every loss/retransmission on the physical path or complete final flight was counted. Failed
fixtures retain their existing STOP output; a successful start/end pair is emitted only on completion.

Focused pure tests cover unavailable/error responses, field-length boundaries, truncated buffers,
cumulative versus instantaneous classification, decreasing counters and invalid descriptors. The
additional deterministic Linux control uses one owned ephemeral loopback TCP pair and two fixed
64-byte transfers, with one-second connect/I/O bounds and no TLS credentials. Run it separately where
local sockets are permitted:

```sh
cargo test --offline --locked --bin inferswarm-quic-rpc \
  tcp_info::tests::bounded_loopback_control_both_roles -- --ignored --exact
```

In the development sandbox, its bind was refused with EPERM before any listener opened; it is **NOT RUN
to completion here**, not a passing control. The non-socket decoder tests and build checks are separate
evidence. This diagnostic addition makes no performance or fleet-result claim.

For both matched TCP/QUIC pairs, report client RPC and full-chain distributions, setup separately,
client/server CPU, errors/retries, integrity and cleanup. Keep both repeats, including slower ones;
do not pool away ordering effects. No performance threshold is invented here: show absolute time and
paired percentage differences, compare their consistency to repeat variation, and let the maintainer
decide whether the gain merits the small inference follow-up. A synthetic win is not a TPS claim.

Public artifacts contain generic code, source identities and methodology only. Host addresses, key paths,
certificates, fleet measurements, model bytes and private traces remain in private operator receipts.
