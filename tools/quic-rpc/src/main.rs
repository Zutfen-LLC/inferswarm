//! Isolated synthetic SEW1 transport experiment. No inference or production integration.
use quinn::{
    crypto::rustls::{QuicClientConfig, QuicServerConfig},
    Endpoint,
};
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use serde_json::{json, Value};
use std::{
    error::Error,
    ffi::{c_void, CString},
    fs::File,
    io::BufReader,
    net::{IpAddr, SocketAddr, TcpListener, TcpStream},
    os::fd::AsRawFd,
    sync::Arc,
    time::{Duration, Instant},
};
type Result<T> = std::result::Result<T, Box<dyn Error>>;
const DEADLINE: Duration = Duration::from_secs(10);
const ALPN: &[u8] = b"inferswarm-synthetic-rpc-v1";
extern "C" {
    fn bench_tls_verify_failure() -> i32;
    fn bench_validate(ca: *const i8, cert: *const i8, key: *const i8, peer: *const i8) -> bool;
    fn bench_tls(
        fd: i32,
        ca: *const i8,
        cert: *const i8,
        key: *const i8,
        peer: *const i8,
        server: bool,
        ms: i32,
    ) -> *mut c_void;
    fn bench_send(s: *mut c_void, p: *const u8, n: usize, ms: i32) -> bool;
    fn bench_recv(s: *mut c_void, p: *mut u8, n: usize, ms: i32) -> bool;
    fn bench_free(s: *mut c_void);
    fn bench_san(der: *const u8, n: usize, peer: *const i8) -> bool;
}

fn mono_ns() -> u64 {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    assert_eq!(
        unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) },
        0
    );
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
}
fn stage(event: &str, server: bool, name: &str) {
    eprintln!(
        "{}",
        json!({"event":event,"role":if server{"server"}else{"client"},"stage":name,"mono_ns":mono_ns()})
    );
}
fn rejection(server: bool, kind: &str) {
    eprintln!(
        "{}",
        json!({"event":"peer_verification_rejected","role":if server{"server"}else{"client"},"kind":kind,"mono_ns":mono_ns()})
    );
}
fn quic_certificate_failure(e: &quinn::ConnectionError) -> Option<&'static str> {
    if let quinn::ConnectionError::TransportError(t) = e {
        // Only locally detected certificate-related TLS alerts. A remote
        // ConnectionClosed alert, setup error or timeout does not qualify.
        return match u64::from(t.code) {
            0x174 => Some("missing_certificate"),
            0x12a..=0x12e | 0x130 | 0x131 => Some("invalid_certificate"),
            _ => None,
        };
    }
    None
}
fn quic_handshake_error(e: quinn::ConnectionError, server: bool) -> quinn::ConnectionError {
    if let Some(kind) = quic_certificate_failure(&e) {
        rejection(server, kind);
    }
    e
}
fn is_timeout(e: &(dyn Error + 'static)) -> bool {
    if e.is::<tokio::time::error::Elapsed>() {
        return true;
    }
    if let Some(io) = e.downcast_ref::<std::io::Error>() {
        if let Some(q) = io
            .get_ref()
            .and_then(|inner| inner.downcast_ref::<quinn::ReadError>())
        {
            return matches!(
                q,
                quinn::ReadError::ConnectionLost(quinn::ConnectionError::TimedOut)
            );
        }
    }
    false
}

struct Config {
    server: bool,
    quic: bool,
    address: SocketAddr,
    local: SocketAddr,
    peer_ip: IpAddr,
    ca: String,
    cert: String,
    key: String,
    peer: String,
    tokens: usize,
    rows: usize,
    chains: usize,
    warmup: usize,
    nodelay: bool,
}
impl Config {
    fn parse() -> Result<Self> {
        let args: Vec<_> = std::env::args().skip(1).collect();
        if args.len() != 15 {
            return Err("usage: inferswarm-quic-rpc server|client tcp|quic ADDRESS LOCAL_BIND PEER_IP CA CERT KEY PEER_DNS T ROWS CHAINS WARMUP_CHAINS ACCEPTED_NODELAY(0|1) (15 arguments including final reserved version=1)".into());
        }
        let c = Self {
            server: match args[0].as_str() {
                "server" => true,
                "client" => false,
                _ => return Err("role".into()),
            },
            quic: match args[1].as_str() {
                "quic" => true,
                "tcp" => false,
                _ => return Err("transport".into()),
            },
            address: args[2].parse()?,
            local: args[3].parse()?,
            peer_ip: args[4].parse()?,
            ca: args[5].clone(),
            cert: args[6].clone(),
            key: args[7].clone(),
            peer: args[8].clone(),
            tokens: args[9].parse()?,
            rows: args[10].parse()?,
            chains: args[11].parse()?,
            warmup: args[12].parse()?,
            nodelay: match args[13].as_str() {
                "0" => false,
                "1" => true,
                _ => return Err("nodelay".into()),
            },
        };
        if args[14] != "1"
            || !c.address.is_ipv4()
            || !c.local.is_ipv4()
            || !c.peer_ip.is_ipv4()
            || c.address.ip().is_unspecified()
            || c.address.ip().is_multicast()
            || c.address.port() == 0
            || c.local.ip().is_unspecified()
            || c.local.ip().is_multicast()
            || c.peer_ip.is_unspecified()
            || c.peer_ip.is_multicast()
            || !(1..=8).contains(&c.tokens)
            || c.rows > c.tokens * 10
            || c.chains == 0
            || c.chains > 256
            || c.warmup > 16
            || c.peer.is_empty()
            || !c
                .peer
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
            || (c.server && c.address != c.local)
            || (!c.server && c.address.ip() != c.peer_ip)
        {
            return Err("invalid bounded configuration; require numeric unicast IPv4 and exact DNS identity".into());
        }
        Ok(c)
    }
}

// Stable synthetic finite F32 values, including signs and nontrivial mantissas.
// No compression, quantization, model payloads, prompt or private trace data.
fn floats(out: &mut Vec<u8>, n: usize, salt: u32) {
    for i in 0..n {
        let x = (i as u32)
            .wrapping_mul(1664525)
            .wrapping_add(1013904223 ^ salt);
        out.extend_from_slice(&((x & 0x807fffff) | 0x3f000000).to_le_bytes());
    }
}
fn frame(msg: u16, p: Vec<u8>) -> Vec<u8> {
    let mut out = b"SEW1".to_vec();
    out.extend_from_slice(&msg.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&(p.len() as u64).to_le_bytes());
    out.extend(p);
    out
}
fn request(t: usize, rows: usize) -> Vec<u8> {
    let mut p = Vec::new();
    for x in [1u64, 2, 3, 0] {
        p.extend_from_slice(&x.to_le_bytes());
    }
    p.extend_from_slice(&0u16.to_le_bytes());
    p.extend([t as u8, 10]);
    for i in 0..t * 10 {
        p.push(u8::from(rows == 0 || i < rows));
    }
    for i in 0..t * 10 {
        p.extend_from_slice(&(i as u16).to_le_bytes());
    }
    for _ in 0..t * 10 {
        p.extend_from_slice(&0.1f32.to_le_bytes());
    }
    floats(&mut p, t * 2560, 17);
    frame(if rows == 0 { 7 } else { 20 }, p)
}
fn reply(t: usize, rows: usize) -> Vec<u8> {
    let mut p = Vec::new();
    for x in [1u64, 0] {
        p.extend_from_slice(&x.to_le_bytes());
    }
    if rows == 0 {
        floats(&mut p, t * 2560, 29);
    } else {
        p.extend_from_slice(&1u16.to_le_bytes());
        p.extend_from_slice(&(rows as u16).to_le_bytes());
        for i in 0..rows {
            p.extend_from_slice(&(i as u16).to_le_bytes());
            floats(&mut p, 2560, 29 + i as u32);
        }
    }
    frame(if rows == 0 { 8 } else { 21 }, p)
}
fn sequence(req: &mut [u8], rep: &mut [u8], seq: u64) {
    req[40..48].copy_from_slice(&seq.to_le_bytes());
    rep[24..32].copy_from_slice(&seq.to_le_bytes());
}
fn check_header(head: &[u8], expected: &[u8]) -> Result<()> {
    if head != &expected[..16] {
        return Err("frame magic/type/status/length mismatch".into());
    }
    Ok(())
}
fn integrity(got: &[u8], expected: &[u8]) -> Result<()> {
    if got != expected {
        return Err("payload/session/sequence integrity mismatch".into());
    }
    Ok(())
}

struct Tcp {
    tls: *mut c_void,
    _socket: TcpStream,
}
impl Drop for Tcp {
    fn drop(&mut self) {
        unsafe {
            bench_free(self.tls);
        }
    }
}
impl Tcp {
    fn establish(c: &Config) -> Result<Self> {
        let ca = CString::new(c.ca.as_str())?;
        let cert = CString::new(c.cert.as_str())?;
        let key = CString::new(c.key.as_str())?;
        let peer = CString::new(c.peer.as_str())?;
        if !unsafe { bench_validate(ca.as_ptr(), cert.as_ptr(), key.as_ptr(), peer.as_ptr()) } {
            return Err("production TLS configuration rejected before bind".into());
        }
        let socket = if c.server {
            let listener = TcpListener::bind(c.local)?;
            listener.set_nonblocking(true)?;
            eprintln!("{}", json!({"event":"listening","transport":"tcp"}));
            let start = Instant::now();
            loop {
                match listener.accept() {
                    Ok((s, a)) => {
                        if a.ip() != c.peer_ip {
                            return Err("unexpected TCP peer".into());
                        }
                        break s;
                    }
                    Err(e)
                        if e.kind() == std::io::ErrorKind::WouldBlock
                            && start.elapsed() < DEADLINE =>
                    {
                        std::thread::sleep(Duration::from_millis(1))
                    }
                    Err(e) => return Err(e.into()),
                }
            }
        } else {
            // Bind the selected local interface, then use Strata's production TLS I/O.
            socket2_connect(c.local, c.address)?
        };
        socket.set_nodelay(!c.server || c.nodelay)?;
        stage("handshake_attempt", c.server, "handshake");
        let handshake_start = Instant::now();
        let tls = unsafe {
            bench_tls(
                socket.as_raw_fd(),
                ca.as_ptr(),
                cert.as_ptr(),
                key.as_ptr(),
                peer.as_ptr(),
                c.server,
                10000,
            )
        };
        if tls.is_null() {
            match unsafe { bench_tls_verify_failure() } {
                1 => rejection(c.server, "invalid_certificate"),
                2 => rejection(c.server, "missing_certificate"),
                _ => {
                    if handshake_start.elapsed() >= DEADLINE {
                        stage("stage_timeout", c.server, "handshake");
                    }
                }
            }
            return Err("production Strata mTLS handshake rejected".into());
        }
        Ok(Self {
            tls,
            _socket: socket,
        })
    }
    fn send(&self, buf: &[u8]) -> Result<()> {
        if unsafe { bench_send(self.tls, buf.as_ptr(), buf.len(), 10000) } {
            Ok(())
        } else {
            Err("TCP send failed".into())
        }
    }
    fn recv(&self, buf: &mut [u8], expected: &[u8]) -> Result<()> {
        if !unsafe { bench_recv(self.tls, buf.as_mut_ptr(), 16, 10000) } {
            return Err("TCP header short/deadline".into());
        }
        check_header(&buf[..16], expected)?;
        if !unsafe { bench_recv(self.tls, buf[16..].as_mut_ptr(), buf.len() - 16, 10000) } {
            return Err("TCP payload short/deadline".into());
        }
        Ok(())
    }
}
fn socket2_connect(local: SocketAddr, remote: SocketAddr) -> Result<TcpStream> {
    let s = socket2::Socket::new(socket2::Domain::IPV4, socket2::Type::STREAM, None)?;
    s.bind(&local.into())?;
    s.connect_timeout(&remote.into(), DEADLINE)?;
    Ok(s.into())
}
fn certs(path: &str) -> Result<Vec<CertificateDer<'static>>> {
    let v = rustls_pemfile::certs(&mut BufReader::new(File::open(path)?))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if v.is_empty() {
        return Err("empty certificates".into());
    }
    Ok(v)
}
fn key(path: &str) -> Result<PrivateKeyDer<'static>> {
    rustls_pemfile::private_key(&mut BufReader::new(File::open(path)?))?
        .ok_or("missing private key".into())
}
struct Quic {
    endpoint: Endpoint,
    connection: quinn::Connection,
    send: quinn::SendStream,
    recv: quinn::RecvStream,
}
impl Quic {
    async fn establish(c: &Config) -> Result<Self> {
        let mut roots = rustls::RootCertStore::empty();
        for cert in certs(&c.ca)? {
            roots.add(cert)?;
        }
        let mut transport = quinn::TransportConfig::default();
        transport
            .max_concurrent_uni_streams(0u32.into())
            .max_concurrent_bidi_streams(1u32.into())
            .max_idle_timeout(Some(DEADLINE.try_into()?))
            .datagram_receive_buffer_size(None);
        let (endpoint, connection) = if c.server {
            let verifier =
                rustls::server::WebPkiClientVerifier::builder(Arc::new(roots)).build()?;
            let mut tls = rustls::ServerConfig::builder()
                .with_client_cert_verifier(verifier)
                .with_single_cert(certs(&c.cert)?, key(&c.key)?)?;
            tls.alpn_protocols = vec![ALPN.to_vec()];
            tls.send_tls13_tickets = 0;
            tls.max_early_data_size = 0;
            let mut cfg =
                quinn::ServerConfig::with_crypto(Arc::new(QuicServerConfig::try_from(tls)?));
            cfg.transport_config(Arc::new(transport));
            cfg.migration(false);
            let ep = Endpoint::server(cfg, c.local)?;
            eprintln!("{}", json!({"event":"listening","transport":"quic"}));
            let incoming = ep.accept().await.ok_or("QUIC listener closed")?;
            if incoming.remote_address().ip() != c.peer_ip {
                incoming.refuse();
                return Err("unexpected QUIC peer".into());
            }
            stage("handshake_attempt", true, "handshake");
            let conn = incoming.await.map_err(|e| quic_handshake_error(e, true))?;
            (ep, conn)
        } else {
            let mut tls = rustls::ClientConfig::builder()
                .with_root_certificates(roots)
                .with_client_auth_cert(certs(&c.cert)?, key(&c.key)?)?;
            tls.alpn_protocols = vec![ALPN.to_vec()];
            tls.enable_early_data = false;
            tls.resumption = rustls::client::Resumption::disabled();
            let mut cfg = quinn::ClientConfig::new(Arc::new(QuicClientConfig::try_from(tls)?));
            cfg.transport_config(Arc::new(transport));
            let mut ep = Endpoint::client(c.local)?;
            ep.set_default_client_config(cfg);
            let connecting = ep.connect(c.address, &c.peer)?;
            stage("handshake_attempt", false, "handshake");
            let conn = connecting
                .await
                .map_err(|e| quic_handshake_error(e, false))?;
            (ep, conn)
        };
        let identity = connection
            .peer_identity()
            .ok_or("missing QUIC peer certificate")?;
        let chain = identity
            .downcast::<Vec<CertificateDer<'static>>>()
            .map_err(|_| "QUIC certificate type")?;
        let leaf = chain.first().ok_or("empty peer chain")?;
        let name = CString::new(c.peer.as_str())?;
        if !unsafe { bench_san(leaf.as_ptr(), leaf.len(), name.as_ptr()) } {
            rejection(c.server, "exact_san");
            connection.close(1u32.into(), b"identity");
            return Err("QUIC exact peer SAN rejected".into());
        }
        // Opening a stream becomes visible only on its first write. Use one authenticated
        // ready byte outside the timed section, in both transports (see run).
        let (send, recv) = if c.server {
            connection.accept_bi().await?
        } else {
            connection.open_bi().await?
        };
        Ok(Self {
            endpoint,
            connection,
            send,
            recv,
        })
    }
    async fn send(&mut self, buf: &[u8]) -> Result<()> {
        self.send.write_all(buf).await?;
        Ok(())
    }
    async fn recv(&mut self, buf: &mut [u8], expected: &[u8]) -> Result<()> {
        read_frame(&mut self.recv, buf, expected).await
    }
}
async fn read_frame<R: tokio::io::AsyncRead + Unpin>(
    r: &mut R,
    buf: &mut [u8],
    expected: &[u8],
) -> Result<()> {
    use tokio::io::AsyncReadExt;
    r.read_exact(&mut buf[..16]).await?;
    check_header(&buf[..16], expected)?;
    r.read_exact(&mut buf[16..]).await?;
    Ok(())
}
enum Transport {
    Tcp(Tcp),
    Quic(Quic),
}
impl Transport {
    async fn send(&mut self, b: &[u8]) -> Result<()> {
        match self {
            Self::Tcp(s) => s.send(b),
            Self::Quic(s) => tokio::time::timeout(DEADLINE, s.send(b)).await?,
        }
    }
    async fn recv(&mut self, b: &mut [u8], expected: &[u8]) -> Result<()> {
        match self {
            Self::Tcp(s) => s.recv(b, expected),
            Self::Quic(s) => tokio::time::timeout(DEADLINE, s.recv(b, expected)).await?,
        }
    }
    async fn ready(&mut self, server: bool) -> Result<()> {
        let mut b = [0u8];
        match self {
            Self::Tcp(s) => {
                if server {
                    if !unsafe { bench_recv(s.tls, b.as_mut_ptr(), 1, 10000) } {
                        return Err("ready".into());
                    }
                    s.send(&[42])?;
                } else {
                    s.send(&[42])?;
                    if !unsafe { bench_recv(s.tls, b.as_mut_ptr(), 1, 10000) } {
                        return Err("ready".into());
                    }
                }
            }
            Self::Quic(s) => {
                if server {
                    s.recv.read_exact(&mut b).await?;
                    s.send(&[42]).await?;
                } else {
                    s.send(&[42]).await?;
                    s.recv.read_exact(&mut b).await?;
                }
            }
        }
        if b != [42] {
            return Err("ready byte mismatch".into());
        }
        Ok(())
    }
}
fn cpu() -> (f64, f64) {
    let mut r = std::mem::MaybeUninit::<libc::rusage>::uninit();
    assert_eq!(
        unsafe { libc::getrusage(libc::RUSAGE_SELF, r.as_mut_ptr()) },
        0
    );
    let r = unsafe { r.assume_init() };
    (
        r.ru_utime.tv_sec as f64 + r.ru_utime.tv_usec as f64 / 1e6,
        r.ru_stime.tv_sec as f64 + r.ru_stime.tv_usec as f64 / 1e6,
    )
}
fn summary(v: &[u64]) -> Value {
    let mut sorted = v.to_vec();
    sorted.sort_unstable();
    let p = |percent: usize| sorted[(sorted.len() * percent).div_ceil(100).saturating_sub(1)];
    json!({"count":v.len(),"p50_ns":p(50),"p95_ns":p(95),"p99_ns":p(99),"max_ns":sorted.last(),"total_ns":v.iter().sum::<u64>()})
}
async fn run(c: Config) -> Result<()> {
    let setup = Instant::now();
    let mut tr = if c.quic {
        Transport::Quic(tokio::time::timeout(DEADLINE, Quic::establish(&c)).await??)
    } else {
        Transport::Tcp(Tcp::establish(&c)?)
    };
    tokio::time::timeout(DEADLINE, tr.ready(c.server)).await??;
    stage("authenticated_ready", c.server, "frame_read");
    let setup_ns = setup.elapsed().as_nanos() as u64;
    let mut req = request(c.tokens, c.rows);
    let mut rep = reply(c.tokens, c.rows);
    let mut received = vec![0u8; if c.server { req.len() } else { rep.len() }];
    let mut rpc = Vec::with_capacity(c.chains * 52);
    let mut chains = Vec::with_capacity(c.chains);
    let mut start_cpu = (0., 0.);
    let mut wall = Instant::now();
    let mut before_stats = None;
    for chain in 0..c.warmup + c.chains {
        if chain == c.warmup {
            start_cpu = cpu();
            wall = Instant::now();
            if let Transport::Quic(q) = &tr {
                before_stats = Some(q.connection.stats());
            }
        }
        let chain_start = Instant::now();
        for layer in 0..52 {
            sequence(&mut req, &mut rep, (chain * 52 + layer) as u64);
            if c.server && chain == 0 && layer == 0 {
                stage("frame_read_start", true, "frame_read");
            }
            let start = Instant::now();
            let exchange = async {
                if c.server {
                    tr.recv(&mut received, &req).await?;
                    integrity(&received, &req)?;
                    tr.send(&rep).await?;
                } else {
                    tr.send(&req).await?;
                    tr.recv(&mut received, &rep).await?;
                    integrity(&received, &rep)?;
                }
                Ok::<(), Box<dyn Error>>(())
            }
            .await;
            if let Err(e) = exchange {
                if c.server
                    && (is_timeout(e.as_ref())
                        || (!c.quic
                            && e.to_string() == "TCP header short/deadline"
                            && start.elapsed() >= DEADLINE))
                {
                    stage("stage_timeout", true, "frame_read");
                }
                eprintln!(
                    "{}",
                    json!({"status":"STOP","completed_warm_rpcs":rpc.len(),"completed_all_rpcs":chain*52+layer,
                    "failed_chain":chain,"failed_exchange":layer,"error":e.to_string()})
                );
                return Err(e);
            }
            if chain >= c.warmup {
                rpc.push(start.elapsed().as_nanos() as u64);
            }
        }
        if chain >= c.warmup {
            chains.push(chain_start.elapsed().as_nanos() as u64);
        }
    }
    let elapsed = wall.elapsed().as_nanos() as u64;
    let end_cpu = cpu();
    let quic_stats = if let Transport::Quic(q) = &tr {
        let a = before_stats.unwrap();
        let b = q.connection.stats();
        json!({"udp_tx_bytes":b.udp_tx.bytes-a.udp_tx.bytes,"udp_rx_bytes":b.udp_rx.bytes-a.udp_rx.bytes,
            "lost_packets":b.path.lost_packets-a.path.lost_packets,"lost_bytes":b.path.lost_bytes-a.path.lost_bytes,
            "scope":"local warm snapshot; UDP payload only, excludes IP/Ethernet; last ACKs may follow snapshot"})
    } else {
        Value::Null
    };
    let report = json!({"schema":1,"role":if c.server{"server"}else{"client"},"transport":if c.quic{"quinn"}else{"strata-openssl"},
        "strata_sha":"45d0493640b43e6264bd6d52da02a0ae5bf061cf","setup_ready_ns":setup_ns,
        "tokens":c.tokens,"rows":c.rows,"request_frame_bytes":req.len(),"reply_frame_bytes":rep.len(),
        "chains":c.chains,"exchanges_per_chain":52,"warmup_chains":c.warmup,"connections":1,"streams":1,"outstanding":1,
        "accepted_nodelay":c.nodelay,"completed":rpc.len(),"errors":0,"application_retries":0,"integrity":"all bytes exact",
        "cpu_user_seconds":end_cpu.0-start_cpu.0,"cpu_system_seconds":end_cpu.1-start_cpu.1,"warm_wall_ns":elapsed,
        "rpc_scope":if c.server{"wait for full request + validate + send"}else{"send + full receive + validate"},
        "rpc":summary(&rpc),"chain":summary(&chains),"rpc_samples_ns":rpc,"chain_samples_ns":chains,
        "completed_application_frame_bytes":(req.len()+rep.len())*c.chains*52,
        "tcp_wire_bytes":Value::Null,"tcp_retransmits":Value::Null,"quic_stats":quic_stats});
    // The client has validated the last reply. One final authenticated acknowledgment
    // lets the server close without discarding queued QUIC data; excluded from metrics.
    tokio::time::timeout(DEADLINE, tr.ready(c.server)).await??;
    if let Transport::Quic(mut q) = tr {
        q.send.finish()?;
        // Deliver the final ready byte and FIN before closing the connection.
        let mut extra = [0u8];
        if tokio::time::timeout(DEADLINE, q.recv.read(&mut extra))
            .await??
            .is_some()
        {
            return Err("unexpected bytes after final ack".into());
        }
        tokio::time::timeout(DEADLINE, q.send.stopped()).await??;
        q.connection.close(0u32.into(), b"done");
        tokio::time::timeout(DEADLINE, q.endpoint.wait_idle()).await?;
    }
    println!("{report}");
    Ok(())
}
fn main() {
    let result = (|| -> Result<()> {
        rustls::crypto::ring::default_provider()
            .install_default()
            .map_err(|_| "crypto provider")?;
        let c = Config::parse()?;
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?
            .block_on(run(c))
    })();
    if let Err(e) = result {
        eprintln!(
            "{}",
            json!({"errors":1,"status":"STOP","error":e.to_string(),"application_retries":0})
        );
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn certificate_failure_is_local_and_typed() {
        let local =
            quinn::ConnectionError::TransportError(quinn::TransportErrorCode::crypto(48).into());
        assert_eq!(
            quic_certificate_failure(&local),
            Some("invalid_certificate")
        );
        assert_eq!(
            quic_certificate_failure(&quinn::ConnectionError::TimedOut),
            None
        );
        let absent =
            quinn::ConnectionError::TransportError(quinn::TransportErrorCode::crypto(116).into());
        assert_eq!(
            quic_certificate_failure(&absent),
            Some("missing_certificate")
        );
        let io = std::io::Error::from(quinn::ReadError::ConnectionLost(
            quinn::ConnectionError::TimedOut,
        ));
        assert!(is_timeout(&io));
        let io = std::io::Error::from(quinn::ReadError::ConnectionLost(
            quinn::ConnectionError::Reset,
        ));
        assert!(!is_timeout(&io));
    }
    #[test]
    fn shapes_and_sequence() {
        for t in 1..=8 {
            for rows in [0, 1, 5, t * 10] {
                let mut q = request(t, rows);
                let mut r = reply(t, rows);
                sequence(&mut q, &mut r, 123456);
                assert_eq!(q.len(), 16 + 36 + t * 10 * 7 + t * 2560 * 4);
                assert_eq!(
                    r.len(),
                    if rows == 0 {
                        32 + t * 2560 * 4
                    } else {
                        36 + rows * (2 + 2560 * 4)
                    }
                );
                assert_eq!(&q[40..48], &123456u64.to_le_bytes());
                assert_eq!(&r[24..32], &123456u64.to_le_bytes());
                assert!(integrity(&q, &q).is_ok());
                let mut bad = q.clone();
                *bad.last_mut().unwrap() ^= 1;
                assert!(integrity(&bad, &q).is_err());
                for offset in [0, 4, 6, 8] {
                    let mut h = q[..16].to_vec();
                    h[offset] ^= 1;
                    assert!(check_header(&h, &q).is_err());
                }
            }
        }
        assert_eq!(request(1, 5).len(), 10362);
        assert_eq!(reply(1, 5).len(), 51246);
    }
    #[test]
    fn finite_float_payload() {
        let mut b = vec![];
        floats(&mut b, 10000, 7);
        for x in b.chunks_exact(4) {
            assert!(f32::from_le_bytes(x.try_into().unwrap()).is_finite());
        }
    }
    #[test]
    fn nearest_rank() {
        let s = summary(&[1, 2, 3, 4]);
        assert_eq!(s["p50_ns"], 2);
        assert_eq!(s["p99_ns"], 4);
    }
    #[test]
    fn fragmented_short_malformed_and_timeout() {
        use tokio::io::AsyncWriteExt;
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async {
                let expected = reply(1, 5);
                let (mut tx, mut rx) = tokio::io::duplex(7);
                let copy = expected.clone();
                let writer = async move {
                    for byte in copy {
                        tx.write_all(&[byte]).await.unwrap();
                    }
                };
                let reader = async {
                    let mut buf = vec![0; expected.len()];
                    read_frame(&mut rx, &mut buf, &expected).await.unwrap();
                    integrity(&buf, &expected).unwrap();
                };
                let task = tokio::spawn(writer);
                reader.await;
                task.await.unwrap();
                for bytes in [
                    expected[..15].to_vec(),
                    expected[..expected.len() - 1].to_vec(),
                    vec![0; 16],
                ] {
                    let (mut tx, mut rx) = tokio::io::duplex(expected.len());
                    tx.write_all(&bytes).await.unwrap();
                    drop(tx);
                    assert!(read_frame(&mut rx, &mut vec![0; expected.len()], &expected)
                        .await
                        .is_err());
                }
                let (_tx, mut rx) = tokio::io::duplex(16);
                assert!(tokio::time::timeout(
                    Duration::from_millis(5),
                    read_frame(&mut rx, &mut vec![0; expected.len()], &expected)
                )
                .await
                .is_err());
            });
    }
}
