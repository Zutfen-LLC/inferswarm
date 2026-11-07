# Local authenticated smoke on the selected build host

A bounded local run on producer head `6e3cd19460f86a6a7420334d8d7dabd4119512be` plus the
fault-adapter patch observed all 36 selected pairs passing; receipts remain private. This is a finite
loopback test, not the LAN ABBA arm, an inference run or transport qualification. Run only within an
authorized local test setup; do not change the clock, firewall/NIC, models or off-host connections.

## Inputs Hermes supplies privately

* The exact parent-reviewed candidate commit and any reviewed local patch, recorded with the run.
  Historical provenance: `496a066060cb57b9a9cfcd43145a4ba76739b4d7` was the initial producer
  base, not a sufficient source pin for this smoke helper or the TCP_INFO diagnostic. The prepared
  checkout's initial head was `6e3cd19460f86a6a7420334d8d7dabd4119512be`; do not substitute it
  for a later reviewed candidate.
* Verified retained Strata source `45d0493640b43e6264bd6d52da02a0ae5bf061cf`; build.rs verifies its
  actual TLS/socket inputs. Existing Rust/C++/OpenSSL dependencies compatible with Cargo.lock.
* The approved short-lived test CA PEM, and **locally authorized** server and client certificate-chain
  PEM/key paths, exact SAN DNS names, validity/issuer/purpose receipts. Both leaf keys must match their
  certificates. Positive leaves must currently verify for serverAuth/clientAuth respectively.
* If the approved host-local test certificate has both EKUs, the same on-host identity may be used in
  both roles for this loopback smoke; label that fact. **Do not transfer another host's private key**
  to manufacture a second identity. If no approved client identity is available locally, report that
  missing input before running. The later two-host arm uses each host's own key in its own role.
* Fresh private output directories, an inherited reserved CPU/resource envelope (no competing
  benchmark), 256 MiB memory per child/no swap, and the existing health/ownership supervisor.
  The runner uses at most one server/client pair at a time; no GPU or model.
* Approved test-only negative certificate/key inputs below. Do not reuse unrelated credentials.
  Positive certificates do not by themselves provide expired/EKU/chain negative fixtures.

Positive identities are checked with `openssl verify -purpose sslserver|sslclient -verify_hostname`,
dedicated CA trust and the unchanged current clock. Public-key DER is compared without emitting the
private key. For intermediate chains, `cert` is the actual leaf-first presented chain file; optional
`intermediates` supplies the existing chain file used by the read-only preflight verifier.

## Build and pure tests — no listeners

```sh
cd "$SRC/tools/quic-rpc"
export STRATA_SOURCE="$VERIFIED_STRATA_SOURCE"
export CARGO_TARGET_DIR="$PRIVATE_BUILD_DIR"
cargo test --offline --locked
cargo clippy --offline --locked --all-targets -- -D warnings
cargo fmt --check
python3 -m unittest -v test_smoke.py
cargo build --offline --locked --release --bins -j "$BUILD_JOBS"
sha256sum "$CARGO_TARGET_DIR/release/inferswarm-quic-rpc" "$CARGO_TARGET_DIR/release/smoke_peer" Cargo.lock
```

Resolve `SRC` to the exact approved candidate source and preserve the hashes privately. Choose and
record `BUILD_JOBS` for the host's current load, memory and concurrent work. Missing dependencies are
a STOP; this command does not fetch or install them. The Python tests only inspect
command construction/result classification; they do not launch listeners or prove authentication.

## Manifest

Create this small JSON file privately using existing absolute paths. It contains paths, not certificate
or key contents. `openssl` is the verified existing OpenSSL executable. All endpoints are hardcoded
loopback inside the runner; there is no manifest address/route override.

```json
{
  "benchmark": "/approved/build/target/release/inferswarm-quic-rpc",
  "peer": "/approved/build/target/release/smoke_peer",
  "openssl": "/usr/bin/openssl",
  "ca": "/approved/test-material/ca.pem",
  "server": {
    "cert": "/approved/test-material/local-server-chain.pem",
    "key": "/approved/test-material/local-server.key",
    "dns": "server.test.invalid"
  },
  "client": {
    "cert": "/approved/test-material/local-client-chain.pem",
    "key": "/approved/test-material/local-client.key",
    "dns": "client.test.invalid"
  },
  "cases": [
    "positive", "wrong-server-san", "wrong-client-san", "missing-client-cert",
    "header-cut", "payload-cut", "disconnect", "stall-frame", "stall-handshake-tcp"
  ],
  "negative": {}
}
```

The initial selection above runs **17 pairs**: eight cases on both TCP and QUIC, plus the TCP
stalled-handshake case. To select the full **36 pairs**, append `stall-handshake-quic` and `block-write`
to `cases`, and add and select all eight `(kind, role)` negative declarations described below. The
additional fault cases contribute three pairs; the eight negative declarations contribute 16. Every
positive pair performs exactly 52 exchanges (T1/R5, one chain, zero warmups), validating full payload
bytes and final acknowledgment/close. There are no latency acceptance gates or retries. Wrong expected
SAN is exercised separately at client and server.

The missing-client case is real:

* TCP: the runner invokes OpenSSL `s_client` with CA/server verification and TLS 1.3, deliberately
  omitting `-cert`/`-key`; it must reach the peer and receive a certificate-required alert.
* QUIC: `smoke_peer` builds rustls with `with_no_client_auth()`, while retaining required server CA,
  chain and exact SAN verification. It must attempt the handshake, fail before application-ready,
  and leave a server certificate-rejection receipt. It never reads a client cert/key in this mode.

`header-cut` and `payload-cut` authenticate first, exchange the ready byte, then send a partial SEW1
header or partial payload and close. `disconnect` drops after authenticated-ready. `stall-frame`
authenticates and holds without progress for 11.5 seconds; the benchmark's 10-second read/idle bound
must fail first. The TCP stalled-handshake peer connects and holds without sending TLS for 11.5
seconds. These failures must return within the per-pair limit, without a success receipt. The runner
does not classify a pre-listener error, missing-file rejection, or outer kill as a passing negative case.

## Optional negative inputs — only select available approved fixtures

Add a declaration such as the following under `negative` and append its name to `cases`, keeping
`positive` first. Each added declaration runs once per transport. Maximum 24 selected case names;
the whole runner still stops at 600 seconds. The `role` selects which peer presents the supplied
certificate, and the counterpart retains normal verification. Keep the correct expected SAN and
matching key; isolate the intended defect. Save the fixture's pre-existing provenance/issuer/validity
and purpose verification receipt alongside the run. Generic rejection alone does not establish which
of multiple fixture defects caused it.

```json
"untrusted-client": {
  "role": "client", "kind": "untrusted",
  "cert": "/approved/negative/untrusted-client-chain.pem",
  "key": "/approved/negative/untrusted-client.key"
}
```

Use separate entries for each available `(kind, role)` pair:

| Kind | Required additional existing inputs |
|---|---|
| `untrusted` | A matching-key peer with the correct SAN and role EKU, signed by a CA absent from the dedicated verifier trust. |
| `expired` | An approved matching-key peer expired at the unchanged current clock, with the correct SAN/purpose. Certificate issuance requires explicit authorization; never manipulate the clock. |
| `wrong-eku` | A matching-key peer with the correct SAN/trusted chain but unsuitable serverAuth/clientAuth purpose for its role. |
| `incomplete-chain` | A trusted-chain peer requiring an intermediate omitted from its presented chain; the verifier trust must contain only the authorized root, not the missing intermediate. Omitting the root alone is not this test. Retain the complete chain's successful reference verification receipt. |

Missing inputs stay **PENDING** in the final summary; they are not waived or claimed as tested.
Certificate presentation failures before listener readiness are STOP, not passing negative handshakes.
This helper is not a general PKI test framework. `stall-handshake-quic` forwards one genuine client
Initial datagram through an owned loopback relay and suppresses subsequent traffic. `block-write` uses
an authenticated non-consuming client and finite pipelined T8/R80 exact requests, with a constrained
TCP receive buffer or QUIC receive credit and keepalive. It is fault injection, **not** the serial
performance workload. Its opt-in server diagnostics require an independently timed frame-write
failure, not a read timeout or outer kill. The `stall-frame` case separately tests read/idle failure;
final close is exercised by the positive pair. Local observations do not qualify a different build or
environment.

## Commands

Preflight-only does not open sockets; use a fresh output directory:

```sh
python3 "$SRC/tools/quic-rpc/smoke.py" --manifest "$PRIVATE_MANIFEST" \
  --out "$PRIVATE_PREFLIGHT_OUT" --preflight-only
```

Within the authorized local-smoke scope, use the inherited health/resource supervisor and
an additional **660-second outer bound** for the runner (600 internal plus owned cleanup):

```sh
timeout --signal=TERM --kill-after=5s 660s \
  python3 "$SRC/tools/quic-rpc/smoke.py" --manifest "$PRIVATE_MANIFEST" \
  --out "$PRIVATE_SMOKE_OUT"
```

The supervisor must retain the recorded process groups for exact-owned cleanup if its outer bound
or health control fires; do not kill unrelated processes. The runner starts each server, passively
waits for its `listening` event (no probe connection), then launches exactly one client without a
connect retry. Each pair has a 40-second bound. Unexpected outcomes stop the remaining selection.
It reaps its children and checks Linux socket tables for no remaining selected listener/UDP socket;
TCP TIME_WAIT is allowed. An occupied-port race fails the case rather than choosing a replacement
and retrying. Partial stdout/stderr and per-case process argv/PIDs remain private even on STOP.

Authentication negatives require structured handshake-attempt events from actual connections and a
local `peer_verification_rejected` event at the expected verifying endpoint. Generic error words such
as "certificate" or "handshake", remote alerts alone, and setup-stage failures cannot pass a case.
OpenSSL diagnostics read its local failure queue after the unchanged production handshake; Quinn
diagnostics distinguish locally detected certificate TLS errors from remote connection-close alerts.
If the installed stack supplies no unambiguous local rejection diagnostic, preserve the case as STOP
rather than inferring verification from a timeout. No verification policy is relaxed for these events.

The runner polls both children independently and retains their first observed exit timestamps. Stall
cases require the server's explicit timeout event at the intended handshake, frame-read or frame-write
stage, with 9.5..20 seconds from its handshake-start, authenticated-ready or most recent write-start
event to both timeout and independently observed server exit (same-host CLOCK_MONOTONIC). The helper's 11.5-second hold and total
pair duration cannot satisfy this check if the server fails immediately. Those wide observation bounds
do not extend any 10-second internal deadline or the existing pair/whole-run budget.

Report the source/patch and both binary hashes, approved certificate identities, selected cases,
every actual exit/receipt, and `summary.json` pending list. `SELECTED_CASES_PASS` only means the selected
local cases passed; it is not full interoperability, LAN readiness, TPS or performance qualification.
Preserve the source applicability/measurement caveats in README. Do not publish private receipts.
