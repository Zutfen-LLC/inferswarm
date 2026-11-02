//! Test-only loopback client: required server verification is never disabled.
//! Used only by smoke.py, never for timings or production traffic.
use quinn::{crypto::rustls::QuicClientConfig, Endpoint};
use rustls::pki_types::CertificateDer;
use serde_json::json;
use std::{
    error::Error,
    ffi::{c_void, CString},
    fs::File,
    io::BufReader,
    net::{SocketAddr, TcpStream},
    os::fd::AsRawFd,
    sync::Arc,
    time::Duration,
};
type Result<T> = std::result::Result<T, Box<dyn Error>>;
const BOUND: Duration = Duration::from_secs(15);
extern "C" {
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
fn certs(path: &str) -> Result<Vec<CertificateDer<'static>>> {
    let c = rustls_pemfile::certs(&mut BufReader::new(File::open(path)?))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if c.is_empty() {
        return Err("empty certificate file".into());
    }
    Ok(c)
}
fn cut(mode: &str) -> Result<Vec<u8>> {
    let mut head = b"SEW1".to_vec();
    head.extend_from_slice(&20u16.to_le_bytes());
    head.extend_from_slice(&0u16.to_le_bytes());
    head.extend_from_slice(&10346u64.to_le_bytes());
    match mode {
        "header-cut" => {
            head.truncate(7);
            Ok(head)
        }
        "payload-cut" => {
            head.extend_from_slice(&[0; 7]);
            Ok(head)
        }
        "disconnect" | "stall-frame" => Ok(vec![]),
        _ => Err("unsupported fault mode".into()),
    }
}
struct Tcp {
    tls: *mut c_void,
    _fd: TcpStream,
}
impl Drop for Tcp {
    fn drop(&mut self) {
        unsafe {
            bench_free(self.tls);
        }
    }
}
fn tcp(args: &[String], addr: SocketAddr) -> Result<()> {
    let mode = &args[4];
    let fd = TcpStream::connect_timeout(&addr, Duration::from_secs(5))?;
    println!("{}", json!({"event":"connected","transport":"tcp"}));
    if mode == "stall-handshake" {
        std::thread::sleep(Duration::from_millis(11500));
        return Ok(());
    }
    let names = args[1..4]
        .iter()
        .chain(args[5..7].iter())
        .map(|s| CString::new(s.as_str()))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    // args: transport, address, CA, DNS, mode, cert, key.
    let tls = unsafe {
        bench_tls(
            fd.as_raw_fd(),
            names[1].as_ptr(),
            names[3].as_ptr(),
            names[4].as_ptr(),
            names[2].as_ptr(),
            false,
            10000,
        )
    };
    if tls.is_null() {
        return Err("test peer production TLS handshake failed".into());
    }
    let p = Tcp { tls, _fd: fd };
    let mut ready = [0];
    if !unsafe {
        bench_send(p.tls, [42].as_ptr(), 1, 10000)
            && bench_recv(p.tls, ready.as_mut_ptr(), 1, 10000)
    } || ready != [42]
    {
        return Err("ready failed".into());
    }
    println!("{}", json!({"event":"authenticated_ready"}));
    let payload = cut(mode)?;
    if !payload.is_empty() && !unsafe { bench_send(p.tls, payload.as_ptr(), payload.len(), 10000) }
    {
        return Err("fault write failed".into());
    }
    if mode == "stall-frame" {
        std::thread::sleep(Duration::from_millis(11500));
    }
    Ok(())
}
async fn quic(args: &[String], addr: SocketAddr) -> Result<()> {
    let mode = &args[4];
    let mut roots = rustls::RootCertStore::empty();
    for c in certs(&args[2])? {
        roots.add(c)?;
    }
    let builder = rustls::ClientConfig::builder().with_root_certificates(roots);
    let no_cert = mode == "no-client-cert";
    let mut tls = if no_cert {
        builder.with_no_client_auth()
    } else {
        let key = rustls_pemfile::private_key(&mut BufReader::new(File::open(&args[6])?))?
            .ok_or("missing test key")?;
        builder.with_client_auth_cert(certs(&args[5])?, key)?
    };
    tls.alpn_protocols = vec![b"inferswarm-synthetic-rpc-v1".to_vec()];
    tls.enable_early_data = false;
    tls.resumption = rustls::client::Resumption::disabled();
    let mut ep = Endpoint::client("127.0.0.1:0".parse()?)?;
    ep.set_default_client_config(quinn::ClientConfig::new(Arc::new(
        QuicClientConfig::try_from(tls)?,
    )));
    println!(
        "{}",
        json!({"event":"handshake_attempt","certificate_configured":!no_cert,"transport":"quic"})
    );
    let conn = ep.connect(addr, &args[3])?.await?;
    let identity = conn
        .peer_identity()
        .ok_or("missing server identity")?
        .downcast::<Vec<CertificateDer<'static>>>()
        .map_err(|_| "identity type")?;
    let leaf = identity.first().ok_or("empty peer chain")?;
    let name = CString::new(args[3].as_str())?;
    if !unsafe { bench_san(leaf.as_ptr(), leaf.len(), name.as_ptr()) } {
        return Err("exact server SAN rejected".into());
    }
    let (mut send, mut recv) = conn.open_bi().await?;
    send.write_all(&[42]).await?;
    let mut ready = [0];
    recv.read_exact(&mut ready).await?;
    if ready != [42] {
        return Err("ready byte".into());
    }
    println!(
        "{}",
        json!({"event":"authenticated_ready","certificate_configured":!no_cert})
    );
    if no_cert {
        return Err("BUG: certificate-free client reached application-ready state".into());
    }
    let bytes = cut(mode)?;
    if !bytes.is_empty() {
        send.write_all(&bytes).await?;
    }
    if mode == "stall-frame" {
        tokio::time::sleep(Duration::from_millis(11500)).await;
    } else if mode != "disconnect" {
        send.finish()?;
        // A rejected truncated frame can close the connection before FIN acknowledgment.
        // Keep the actual peer result in the receipt; do not retry it.
        println!(
            "{}",
            json!({"event":"truncated_stream_finished","peer_result":format!("{:?}",send.stopped().await)})
        );
    }
    conn.close(1u32.into(), b"test fault");
    tokio::time::timeout(BOUND, ep.wait_idle()).await?;
    Ok(())
}
fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = (|| -> Result<()> {
        if args.len() != 5 && args.len() != 7 {
            return Err(
                "usage: smoke_peer tcp|quic LOOPBACK_ADDR CA SERVER_DNS MODE [CERT KEY]".into(),
            );
        }
        let addr: SocketAddr = args[1].parse()?;
        if !addr.is_ipv4() || !addr.ip().is_loopback() || addr.port() == 0 {
            return Err("test helper is loopback-only".into());
        }
        let mode = &args[4];
        let no_cert = mode == "no-client-cert";
        if no_cert && (args[0] != "quic" || args.len() != 5) {
            return Err("certificate-free mode is QUIC-only; TCP uses openssl s_client".into());
        }
        if !no_cert && mode != "stall-handshake" && args.len() != 7 {
            return Err("fault peer needs supplied certificate/key".into());
        }
        if !no_cert && mode != "stall-handshake" {
            cut(mode)?;
        }
        match args[0].as_str() {
            "tcp" => tcp(&args, addr),
            "quic" => {
                if mode == "stall-handshake" {
                    return Err("QUIC handshake stall requires a separately scoped drop adapter; not implemented".into());
                }
                rustls::crypto::ring::default_provider()
                    .install_default()
                    .map_err(|_| "provider")?;
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()?
                    .block_on(async { tokio::time::timeout(BOUND, quic(&args, addr)).await? })
            }
            _ => Err("transport".into()),
        }
    })();
    if let Err(e) = result {
        eprintln!("{}", json!({"event":"peer_error","error":e.to_string()}));
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_truncation_shapes() {
        let h = cut("header-cut").unwrap();
        assert_eq!(h.len(), 7);
        let p = cut("payload-cut").unwrap();
        assert_eq!(p.len(), 23);
        assert_eq!(&p[..4], b"SEW1");
        assert_eq!(u64::from_le_bytes(p[8..16].try_into().unwrap()), 10346);
        assert!(cut("bad").is_err());
    }
}
