use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf};

fn main() {
    println!("cargo:rerun-if-env-changed=STRATA_SOURCE");
    let root = PathBuf::from(
        env::var("STRATA_SOURCE")
            .expect("set STRATA_SOURCE to Strata 45d0493640b43e6264bd6d52da02a0ae5bf061cf"),
    );
    for (file, hash) in [
        (
            "src/worker/wire_sock.cpp",
            "74d79baf1624f15d2031c1f05fbd8abbdfcf33a29644aec32eda02a7087321d8",
        ),
        (
            "src/worker/wire_sock.hpp",
            "f8689347d8fc9812c5f11f93205a1fd740f3c992e781d4f8e4286b06a8b04af9",
        ),
        (
            "include/strata/worker/tls.hpp",
            "4b775ea2761c06258b81c1c45003149c0979329bc761cd34d2cc8fde5df4b470",
        ),
    ] {
        let path = root.join(file);
        assert_eq!(
            format!("{:x}", Sha256::digest(fs::read(&path).expect(file))),
            hash,
            "Strata source drift: {file}"
        );
        println!("cargo:rerun-if-changed={}", path.display());
    }
    cc::Build::new()
        .cpp(true)
        .std("c++20")
        .define("STRATA_WORKER_TLS", None)
        .include(root.join("include"))
        .include(root.join("src/worker"))
        .file(root.join("src/worker/wire_sock.cpp"))
        .file("tcp_shim.cpp")
        .compile("strata_tcp");
    println!("cargo:rustc-link-lib=ssl");
    println!("cargo:rustc-link-lib=crypto");
    println!("cargo:rerun-if-changed=tcp_shim.cpp");
}
