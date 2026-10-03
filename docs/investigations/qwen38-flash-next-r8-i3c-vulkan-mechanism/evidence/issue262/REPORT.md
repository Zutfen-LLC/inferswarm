# Issue #262 retained pilot report (CPU-only)

## Evidence provenance
- Logical retained root: `/home/hermes/is262-evidence`
- Inventory: `remote-inventory.tsv`, 150 files; SHA-256 `806160f67aeff84d2b4d1531d65e582cd7e599cdf601aad877d70f83924f6038`
- a4_execution_head: `1a0997dbb850e78b6899243b463a27fb8ab4fb56`
- comparator_sha256: `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`
- original_execution_head: `76aaaf69a3920879c1db17c47219f375207fdaf2`
- source_tree: `015c874f0cc0635fa1369650098c0137f9a492f0`
- subject: `{'bdf': '00000000:03:00.0', 'binding': 'historical-A3/A5-subject-reused', 'driver': '610.57.04', 'gpu': 'NVIDIA GeForce RTX 3060', 'gpu_uuid': 'GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55'}`

## Arms
### A1: screening-variable (2 units)
- Unit 1 (`a1-001`): row SHA-256 `3d97a46d7338614463acb8238234e146d7bb0df4e97c167972043d33d8ff8c28`; unit metadata `0dccbbe815f13a6d6761360b568212271c4461956b2cc1ed14648b7a612c298b`; log `4d760a909d1e7b115ef5e247533fb940cf68d37548e125d822373654d0c5f344`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `625435f3d0da3339ae3ccde3fbc4031643bb82b865f16b20f7c7d1c5c495ae00`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `3d97a46d7338614463acb8238234e146d7bb0df4e97c167972043d33d8ff8c28`
  - H2 submission: `serialized`
- Unit 2 (`a1-002`): row SHA-256 `6c126d1e8abf9d180fa2a6d7a067133732a05bbfb1c52bafe60c92b3827af4e6`; unit metadata `9c13869d802402e42cb5cb5c8e77a101cac96830fc773cfca2169a10f0265208`; log `96cf2c9514783480e54b9b131daed60c55894e45b82242284683bba325d845f7`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `4c066fa5690c6e14b8533e3de3066bdcfe0b799b8468376c33768de73ec5e354`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `6c126d1e8abf9d180fa2a6d7a067133732a05bbfb1c52bafe60c92b3827af4e6`
  - H2 submission: `serialized`
### A4: screening-variable (2 units)
- Unit 1 (`a4-001`): row SHA-256 `e4f0faedc53ba6fbe47c82402064db58d829502e2b8f242ed54fd2d31d19d1f3`; unit metadata `6760b587f1ea5b6a8d12799640442b035ec59352e2f8701032ad43068532d50b`; log `a108af4cf076eea12fe62d0d0f6b65164a69da8594203cf26b8c5930f2c98b53`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `1a65b4bfc81a460cd16325569826a67376c697eadbf55ff71fd90c5fdb482654`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `e4f0faedc53ba6fbe47c82402064db58d829502e2b8f242ed54fd2d31d19d1f3`
  - H3: branch `prefer_host`, type `3`, flags `6`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.762.772 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=prefer_host|type=3|flags=0x6`
  - Log line 5407: `0.03.762.791 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`
- Unit 2 (`a4-002`): row SHA-256 `8720366ddd974cc7eaba29c9c03a800ee35dd40b183749b3bd43844da7877627`; unit metadata `b59163bcfd6854ff4884ea2ea13ddfc161d839159da373dd7b4d939aab293088`; log `88d8309c885844e8fad6d9875ad3e80ab99a13203a5755f980c51b208c40cbaf`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `c6b76f2d6e692d076e0055a72ae8b22f89f425784d4620c4048f464aec0a80cf`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `8720366ddd974cc7eaba29c9c03a800ee35dd40b183749b3bd43844da7877627`
  - H3: branch `prefer_host`, type `3`, flags `6`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.884.377 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=prefer_host|type=3|flags=0x6`
  - Log line 5407: `0.03.884.396 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`
### A5: screening-variable (2 units)
- Unit 1 (`a5-001`): row SHA-256 `2dbdb1ad67ad18ffb0ce08ea9f6ef8f9ca1d2ee996d00262050aa9b959f20984`; unit metadata `0a53cdb04b9dbbf54f67e07ba25dfd679b52048601dc24ede9369c020044d3f2`; log `3cd46fdef9535f10ab968239fd497a986f2901dcd3e49bbd43b90a97b9f19995`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `3e122b5dd507f66eb5294c43cfbc4399bd125fdb65790ae5106903db225f08d9`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `2dbdb1ad67ad18ffb0ce08ea9f6ef8f9ca1d2ee996d00262050aa9b959f20984`
  - H3: branch `disable_host_visible`, type `1`, flags `1`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.405.338 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=disable_host_visible|type=1|flags=0x1`
  - Log line 5407: `0.03.405.352 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`
- Unit 2 (`a5-002`): row SHA-256 `b475e19762183e82413cc4776d0fa60aabc3e8aec8bd23eb865b6af315861b0b`; unit metadata `172a82bea979707d6eee76e4cab001c6fe2b67807beeec92e86e1cd257e4bd70`; log `b2ad91358e6b022e544cd282c394a0bbb8e8d8eb2a497e49e8ee570a7792e29b`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `a58baffcb95a360dbe9921776c1b03c0f939fd6239e24271d3095efd0b2eb996`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `b475e19762183e82413cc4776d0fa60aabc3e8aec8bd23eb865b6af315861b0b`
  - H3: branch `disable_host_visible`, type `1`, flags `1`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.409.002 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=disable_host_visible|type=1|flags=0x1`
  - Log line 5407: `0.03.409.016 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`
### BASE: screening-variable (2 units)
- Unit 1 (`base-001`): row SHA-256 `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815`; unit metadata `22a86ebb2e5b3cb1c9da7ac0cfc439c04810bb9079029ac240b9c34a71ebf843`; log `406f845a7f17602c8cd726f0f5aec7ceca7b181b4fa6b2e5d0b655162cb06894`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `6264d7397363f19298916c67d00f8ef9c0282137173a1aa7b9f6ca430ddcacfa`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815`
  - H3: branch `default`, type `1`, flags `1`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.375.370 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=default|type=1|flags=0x1`
  - Log line 5407: `0.03.375.383 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`
- Unit 2 (`base-002`): row SHA-256 `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39`; unit metadata `50b222cdbce72f8a642d57933cc901f05f41a3980bd13de0871fa2b330c93002`; log `aafda92a123b06864168f59295e748e62d446a984362be7583d791208039d987`
  - Binary `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`; request `7a4b8ed63a9b0d1bb22cebd21851c7bae0d0d73d142ad9e324c93a4e245f618a`; raw response `ad83a94992ef7c544b91eb62132b958c5d922f73b5016802d565f5db40372943`; accepted comparison `sha256(concat obs.row0.f32..obs.row7.f32)` = `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39`
  - H3: branch `default`, type `1`, flags `1`, buffer `2`, offset `7004160`, bytes `357580800`, allocation_size `364584960`
  - Log line 5406: `0.03.433.772 I ggml_vk_i260:v1|memory|role=backend|buffer=2|branch=default|type=1|flags=0x1`
  - Log line 5407: `0.03.433.786 I ggml_vk_i260:v1|tensor|name=output.weight|buffer=2|offset=7004160|bytes=357580800|allocation_size=364584960`
  - H2 submission: `normal`

## H2 observed submission paths
A1 serialized; BASE/A5/A4 normal. This is a parsed submission-path observation, not numerical causal proof.

## H3 full-pair contrasts
A5 contrast: **False**; A4 required: **True**; A4 executed: **True**; A4 target-choice contrast: **True**; status: **contrast-observed**. A contrast requires observed target memory type/flags change, not just a branch change, and is necessary but not terminal mechanistic proof.
### BASE vs A5
- Unit 1 vs 1: choice_changed=False; pair SHA-256 `e117420932f29a97d76b466429c1fff315e557a429b616d35d7c90caeeffe334`; row digests `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815` / `2dbdb1ad67ad18ffb0ce08ea9f6ef8f9ca1d2ee996d00262050aa9b959f20984`
- Unit 1 vs 2: choice_changed=False; pair SHA-256 `d892b6881fb7b5ea27851c6e63e79c081760ed6a381a85688e7caf37984128ce`; row digests `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815` / `b475e19762183e82413cc4776d0fa60aabc3e8aec8bd23eb865b6af315861b0b`
- Unit 2 vs 1: choice_changed=False; pair SHA-256 `1e1ec3369dea983da6cd4b98d18e286607cf58dc700aef9853cb16656fedc4aa`; row digests `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39` / `2dbdb1ad67ad18ffb0ce08ea9f6ef8f9ca1d2ee996d00262050aa9b959f20984`
- Unit 2 vs 2: choice_changed=False; pair SHA-256 `1c2d20bed547fc9c2fcf6496a171217628e609d4807a47d090b68764ad23d6dc`; row digests `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39` / `b475e19762183e82413cc4776d0fa60aabc3e8aec8bd23eb865b6af315861b0b`
### BASE vs A4
- Unit 1 vs 1: choice_changed=True; pair SHA-256 `e9de3fd9723644a927fb6e6a4963c64c55f31768509b9c70c8367fc10e935f15`; row digests `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815` / `e4f0faedc53ba6fbe47c82402064db58d829502e2b8f242ed54fd2d31d19d1f3`
- Unit 1 vs 2: choice_changed=True; pair SHA-256 `254da793e47b1715618752f6389cb2a725c57e219336027f468a5e8f4ab6b5b7`; row digests `10dde421202c91277ba23725d717564ca5361af94b1f27ad6743b6e5236e5815` / `8720366ddd974cc7eaba29c9c03a800ee35dd40b183749b3bd43844da7877627`
- Unit 2 vs 1: choice_changed=True; pair SHA-256 `3a8260899e7c07d089425d15c6162dd8fdb9847ea454e266f273e13f429bc53a`; row digests `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39` / `e4f0faedc53ba6fbe47c82402064db58d829502e2b8f242ed54fd2d31d19d1f3`
- Unit 2 vs 2: choice_changed=True; pair SHA-256 `5d51b47a480778503597adb7cf64310f2a98e9e27e965073ddec05b46e7ae815`; row digests `cde61f092d7f6b64548ea9318808661819312f44c76e135af886dce996b85f39` / `8720366ddd974cc7eaba29c9c03a800ee35dd40b183749b3bd43844da7877627`

## H5
Baseline route: `{"mat-vec": {"dims": {"dst": [248320, 1], "src0": [2560, 248320], "src1": [2560, 1]}, "family": "mmv", "indexing64": false, "pipe": "mul_mat_vec_q4_k_f32_f32", "quant_y": false, "route": "mat-vec", "split_k": 0, "types": ["q4_K", "f32", "f32"]}}`; candidate eligible=False; executed=False; reason: output projection dispatched on the vector path (['mmv']); coopmat2 switch does not select this path.

Quarantine: 3 known-defect units excluded; 30 inventoried quarantine files.
- `base-parse-defect-001`: known parser/producer defect, not an accepted unit; obs.meta.json SHA-256 `35678ce410b6a4a3a1b94452323c2d7f946ee85283c1050d7c47b63977627bd3`; server.log SHA-256 `8d2d17f384464afc3d84809a9691712f10368caee949148734b667ee64ef4348`; source `remote-inventory.tsv` (10 files).
- `base-run2-parser-defect-001`: known parser/producer defect, not an accepted unit; obs.meta.json SHA-256 `35678ce410b6a4a3a1b94452323c2d7f946ee85283c1050d7c47b63977627bd3`; server.log SHA-256 `24ceca347fcc0ec327f88d5d68120d174d85b3c656c44abf23f54d1c1f273d00`; source `remote-inventory.tsv` (10 files).
- `base-run3-prefix-law-001`: known parser/producer defect, not an accepted unit; obs.meta.json SHA-256 `35678ce410b6a4a3a1b94452323c2d7f946ee85283c1050d7c47b63977627bd3`; server.log SHA-256 `1337fb7aa4f2daeb6b747faaf0b27215ca69642cbf29c538ee056fc7b97b6309`; source `remote-inventory.tsv` (10 files).

## Interpretation
- h2: serialized/normal observations are retained facts, not a numerical causal conclusion
- h3: target memory-choice contrast is necessary, not terminal mechanism proof
- h5: actual baseline route determines candidate eligibility; H5 is not established by capability alone
- mmv_control: MMV/vector path has no live coopmat2 control
- screening: screening-variable is not terminal causal proof; retain all completed units
