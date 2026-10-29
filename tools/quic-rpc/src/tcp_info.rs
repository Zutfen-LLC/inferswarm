//! Read-only Linux TCP_INFO snapshots. No socket options or transport state are changed.
use serde_json::{json, Map, Value};
use std::os::fd::RawFd;

const CAPACITY: usize = 1024;
extern "C" {
    fn bench_tcp_info(fd: i32, bytes: *mut u8, capacity: usize, length: *mut usize) -> i32;
}

pub struct Snapshot {
    errno: i32,
    returned: usize,
    bytes: [u8; CAPACITY],
}

impl Snapshot {
    pub fn capture(fd: RawFd) -> Self {
        let mut s = Self {
            errno: 0,
            returned: 0,
            bytes: [0; CAPACITY],
        };
        s.errno = unsafe { bench_tcp_info(fd, s.bytes.as_mut_ptr(), CAPACITY, &mut s.returned) };
        s
    }

    fn value(&self, f: &Field) -> Option<u64> {
        if self.errno != 0 {
            return None;
        }
        let raw = self
            .bytes
            .get(..self.returned.min(CAPACITY))?
            .get(f.offset..f.offset + f.width)?;
        Some(match f.width {
            1 => raw[0] as u64,
            2 => u16::from_ne_bytes(raw.try_into().ok()?) as u64,
            4 => u32::from_ne_bytes(raw.try_into().ok()?) as u64,
            8 => u64::from_ne_bytes(raw.try_into().ok()?),
            _ => return None,
        })
    }

    fn report(&self) -> Value {
        let fields: Map<String, Value> = FIELDS.iter().map(|f| (f.name.into(), json!({
            "value": self.value(f), "supported": self.value(f).is_some(),
            "kind": if f.cumulative {"cumulative"} else {"instantaneous_or_lifetime_estimate"},
            "unit": f.unit, "offset": f.offset, "width": f.width
        }))).collect();
        // Preserve only bytes actually returned by a successful getsockopt.
        let raw = if self.errno == 0 {
            Some(
                self.bytes[..self.returned.min(CAPACITY)]
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect::<String>(),
            )
        } else {
            None
        };
        json!({"available":self.errno==0,"errno":if self.errno==0 {None}else{Some(self.errno)},
            "requested_len":CAPACITY,"returned_len":if self.errno==0 {Some(self.returned)}else{None},
            "buffer_truncated":self.errno==0 && self.returned>CAPACITY,
            "raw_native_hex":raw,"fields":fields})
    }
}

struct Field {
    name: &'static str,
    offset: usize,
    width: usize,
    cumulative: bool,
    unit: &'static str,
}
macro_rules! f {
    ($name:ident,$off:expr,$width:expr,$cum:expr,$unit:expr) => {
        Field {
            name: stringify!($name),
            offset: $off,
            width: $width,
            cumulative: $cum,
            unit: $unit,
        }
    };
}
// Stable Linux UAPI tcp_info prefix through tcpi_total_rto_time (248 bytes).
// This is not libc::tcp_info's build-header size. Each field is independently
// gated by the returned kernel length; newer suffix bytes remain in the raw record.
const FIELDS: &[Field] = &[
    f!(tcpi_state, 0, 1, false, "enum"),
    f!(tcpi_ca_state, 1, 1, false, "enum"),
    f!(tcpi_retransmits, 2, 1, false, "current_RTO_retry_count"),
    f!(tcpi_probes, 3, 1, false, "current_probe_count"),
    f!(tcpi_backoff, 4, 1, false, "backoff_exponent"),
    f!(tcpi_options, 5, 1, false, "bitmask"),
    f!(tcpi_rto, 8, 4, false, "us"),
    f!(tcpi_ato, 12, 4, false, "us"),
    f!(tcpi_snd_mss, 16, 4, false, "bytes"),
    f!(tcpi_rcv_mss, 20, 4, false, "bytes"),
    f!(tcpi_unacked, 24, 4, false, "segments"),
    f!(tcpi_sacked, 28, 4, false, "segments"),
    f!(tcpi_lost, 32, 4, false, "segments"),
    f!(tcpi_retrans, 36, 4, false, "segments"),
    f!(tcpi_pmtu, 60, 4, false, "IP_MTU_bytes"),
    f!(tcpi_rcv_ssthresh, 64, 4, false, "bytes"),
    f!(tcpi_rtt, 68, 4, false, "us"),
    f!(tcpi_rttvar, 72, 4, false, "us"),
    f!(tcpi_snd_ssthresh, 76, 4, false, "segments"),
    f!(tcpi_snd_cwnd, 80, 4, false, "segments"),
    f!(tcpi_advmss, 84, 4, false, "bytes"),
    f!(tcpi_reordering, 88, 4, false, "segments"),
    f!(tcpi_rcv_rtt, 92, 4, false, "us"),
    f!(tcpi_rcv_space, 96, 4, false, "bytes"),
    f!(tcpi_total_retrans, 100, 4, true, "segments"),
    f!(tcpi_pacing_rate, 104, 8, false, "bytes_per_second"),
    f!(tcpi_max_pacing_rate, 112, 8, false, "bytes_per_second"),
    f!(tcpi_bytes_acked, 120, 8, true, "TCP_payload_bytes"),
    f!(tcpi_bytes_received, 128, 8, true, "TCP_payload_bytes"),
    f!(tcpi_segs_out, 136, 4, true, "segments"),
    f!(tcpi_segs_in, 140, 4, true, "segments"),
    f!(tcpi_notsent_bytes, 144, 4, false, "bytes"),
    f!(tcpi_min_rtt, 148, 4, false, "lifetime_min_us"),
    f!(tcpi_data_segs_in, 152, 4, true, "segments"),
    f!(tcpi_data_segs_out, 156, 4, true, "segments"),
    f!(tcpi_delivery_rate, 160, 8, false, "bytes_per_second"),
    f!(tcpi_busy_time, 168, 8, true, "us"),
    f!(tcpi_rwnd_limited, 176, 8, true, "us"),
    f!(tcpi_sndbuf_limited, 184, 8, true, "us"),
    f!(tcpi_delivered, 192, 4, true, "segments"),
    f!(tcpi_delivered_ce, 196, 4, true, "segments"),
    f!(tcpi_bytes_sent, 200, 8, true, "TCP_payload_bytes"),
    f!(tcpi_bytes_retrans, 208, 8, true, "TCP_payload_bytes"),
    f!(tcpi_dsack_dups, 216, 4, true, "segments"),
    f!(tcpi_reord_seen, 220, 4, true, "events"),
    f!(tcpi_rcv_ooopack, 224, 4, true, "segments"),
    f!(tcpi_snd_wnd, 228, 4, false, "peer_advertised_scaled_bytes"),
    f!(tcpi_rcv_wnd, 232, 4, false, "local_advertised_scaled_bytes"),
    f!(tcpi_total_rto, 240, 2, true, "events"),
    f!(tcpi_total_rto_recoveries, 242, 2, true, "events"),
    f!(tcpi_total_rto_time, 244, 4, true, "ms"),
];

pub fn report(start: &Snapshot, end: &Snapshot) -> Value {
    let deltas: Map<String, Value> = FIELDS
        .iter()
        .filter(|f| f.cumulative)
        .map(|f| {
            let (value, status) = match (start.value(f), end.value(f)) {
                (Some(a), Some(b)) if b >= a => (Some(b - a), "available"),
                (Some(_), Some(_)) => (None, "counter_decreased_or_wrapped"),
                _ => (None, "unavailable_at_one_or_both_snapshots"),
            };
            (
                f.name.into(),
                json!({"value":value,"status":status,"unit":f.unit}),
            )
        })
        .collect();
    let mut kernel = std::mem::MaybeUninit::<libc::utsname>::uninit();
    let release = if unsafe { libc::uname(kernel.as_mut_ptr()) } == 0 {
        let kernel = unsafe { kernel.assume_init() };
        Some(
            unsafe { std::ffi::CStr::from_ptr(kernel.release.as_ptr()) }
                .to_string_lossy()
                .into_owned(),
        )
    } else {
        None
    };
    json!({"schema":1,"platform":"linux_TCP_INFO","kernel_release":release,
        "abi_version":Value::Null,"decoded_prefix_bytes":248,
        "native_byte_order":if cfg!(target_endian="little") {"little"}else{"big"},
        "scope":"local socket snapshots outside warm wall/CPU boundaries; before final acknowledgment/close",
        "start":start.report(),"end":end.report(),"cumulative_deltas":deltas})
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot(n: usize) -> Snapshot {
        Snapshot {
            errno: 0,
            returned: n,
            bytes: [0; CAPACITY],
        }
    }
    #[test]
    fn unsupported_and_truncated_are_not_zero() {
        let unsupported = Snapshot {
            errno: libc::ENOPROTOOPT,
            returned: 0,
            bytes: [0; CAPACITY],
        };
        let r = report(&unsupported, &snapshot(104));
        assert_eq!(r["start"]["errno"], libc::ENOPROTOOPT);
        assert!(r["start"]["returned_len"].is_null());
        assert!(r["cumulative_deltas"]["tcpi_total_retrans"]["value"].is_null());
        let short = snapshot(103).report();
        assert!(short["fields"]["tcpi_total_retrans"]["value"].is_null());
        assert_eq!(
            snapshot(104).report()["fields"]["tcpi_total_retrans"]["value"],
            0
        );
        assert!(snapshot(71).report()["fields"]["tcpi_rtt"]["value"].is_null());
        assert_eq!(snapshot(72).report()["fields"]["tcpi_rtt"]["value"], 0);
        assert_eq!(snapshot(CAPACITY + 1).report()["buffer_truncated"], true);
    }
    #[test]
    fn cumulative_delta_is_not_an_instantaneous_delta() {
        let mut a = snapshot(248);
        let mut b = snapshot(248);
        a.bytes[100..104].copy_from_slice(&7u32.to_ne_bytes());
        b.bytes[100..104].copy_from_slice(&10u32.to_ne_bytes());
        b.bytes[32..36].copy_from_slice(&2u32.to_ne_bytes());
        let r = report(&a, &b);
        assert_eq!(r["cumulative_deltas"]["tcpi_total_retrans"]["value"], 3);
        assert!(r["cumulative_deltas"].get("tcpi_lost").is_none());
        assert_eq!(r["end"]["fields"]["tcpi_lost"]["value"], 2);
        assert_eq!(
            report(&b, &a)["cumulative_deltas"]["tcpi_total_retrans"]["status"],
            "counter_decreased_or_wrapped"
        );
        assert!(report(&b, &a)["cumulative_deltas"]["tcpi_total_retrans"]["value"].is_null());
        assert!(
            report(&snapshot(103), &b)["cumulative_deltas"]["tcpi_total_retrans"]["value"]
                .is_null()
        );
    }
    #[test]
    fn invalid_descriptor_has_no_fields() {
        let r = Snapshot::capture(-1).report();
        assert_eq!(r["available"], false);
        assert!(r["fields"]["tcpi_total_retrans"]["value"].is_null());
    }
    #[test]
    fn native_widths_and_newer_suffix_are_preserved() {
        let mut s = snapshot(256);
        s.bytes[120..128].copy_from_slice(&0x123456789abcdef0u64.to_ne_bytes());
        s.bytes[240..242].copy_from_slice(&513u16.to_ne_bytes());
        s.bytes[248..256].fill(0xab);
        let r = s.report();
        assert_eq!(
            r["fields"]["tcpi_bytes_acked"]["value"],
            0x123456789abcdef0u64
        );
        assert_eq!(r["fields"]["tcpi_total_rto"]["value"], 513);
        assert!(r["raw_native_hex"]
            .as_str()
            .unwrap()
            .ends_with("abababababababab"));
        assert_eq!(r["raw_native_hex"].as_str().unwrap().len(), 512);
        assert!(snapshot(241).report()["fields"]["tcpi_total_rto"]["value"].is_null());
    }
    #[test]
    #[cfg(target_os = "linux")]
    #[ignore = "requires permitted AF_INET loopback sockets; run separately before a diagnostic campaign"]
    fn bounded_loopback_control_both_roles() {
        use std::{
            io::{Read, Write},
            net::{TcpListener, TcpStream},
            os::fd::AsRawFd,
            time::Duration,
        };
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let mut client =
            TcpStream::connect_timeout(&listener.local_addr().unwrap(), Duration::from_secs(1))
                .unwrap();
        let (mut server, _) = listener.accept().unwrap();
        for s in [&client, &server] {
            s.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
            s.set_write_timeout(Some(Duration::from_secs(1))).unwrap();
        }
        let a = Snapshot::capture(client.as_raw_fd());
        let b = Snapshot::capture(server.as_raw_fd());
        client.write_all(&[17; 64]).unwrap();
        let mut bytes = [0; 64];
        server.read_exact(&mut bytes).unwrap();
        assert_eq!(bytes, [17; 64]);
        server.write_all(&[29; 64]).unwrap();
        client.read_exact(&mut bytes).unwrap();
        assert_eq!(bytes, [29; 64]);
        for (start, fd) in [(&a, client.as_raw_fd()), (&b, server.as_raw_fd())] {
            let r = report(start, &Snapshot::capture(fd));
            assert_eq!(r["start"]["available"], true);
            assert_eq!(r["end"]["available"], true);
            assert!(r["start"]["returned_len"].as_u64().unwrap() >= 104);
            assert!(r["cumulative_deltas"]["tcpi_total_retrans"]["value"]
                .as_u64()
                .is_some());
            if let Some(n) = r["cumulative_deltas"]["tcpi_bytes_received"]["value"].as_u64() {
                assert!(n >= 64);
            }
        }
    }
}
