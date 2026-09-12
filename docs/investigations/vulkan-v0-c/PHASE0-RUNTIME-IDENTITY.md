# V0-C Phase-0 runtime identity addendum

This addendum is frozen before any V0-C model execution. It instantiates the
runtime-binary hash required by `METHODOLOGY.md` from a clean local build on the
selected proving host.

- llama.cpp source commit: `8ea290247c87ced2ab245b056ffe96dbcf90d36c`.
- Configure command: `cmake -S /home/zutfen/.cache/v0c-llama.cpp -B /home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON`.
- Build command: `cmake --build /home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan --target llama-cli -j4`.
- `llama-cli` SHA-256:
  `5a8f5edec3cafce77e371b082f4dd52f07d38a72704a652063f6255a018c36ec`.
- The accepted V0-A `llama-cli` hash is intentionally not reused: binary bytes
  are build-context outputs, while V0-C binds its own exact source and binary
  identity before its first execution. The V0-A source identity and all accepted
  evidence remain unchanged.

The first canonical run must refuse to proceed if source commit, model hash,
model size, executable hash, BDF, selector, full offload proof, or frozen plan
digest differs from this methodology and its addendum.
