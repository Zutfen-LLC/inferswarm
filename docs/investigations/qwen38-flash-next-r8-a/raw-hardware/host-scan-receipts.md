# Issue #189 R8-A hardware scan receipts (non-fleet + offline hosts)

Read-only `lspci`/connection attempts while searching for reported-but-unlocated
AMD devices (third Radeon RX 580, RX 6800 XT). Collected 2026-09-14 EDT.

### scan-3090rig.txt
```
ssh: connect to host 3090rig port 22: Connection timed out
```

### scan-autocode.txt
```
ssh: connect to host 10.0.0.21 port 22: No route to host
```

### scan-buildbox.txt
```
=== buildbox ===
00:02.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
```

### scan-cibox3.txt
```
ssh: connect to host 100.109.47.61 port 22: Connection timed out
```

### scan-debian13.txt
```
ssh: connect to host debian13 port 22: Connection timed out
```

### scan-emuweb01.txt
```
ssh: connect to host 10.0.0.172 port 22: No route to host
```

### scan-ezutfen-build.txt
```
ssh: connect to host 10.0.0.120 port 22: No route to host
```

### scan-flowstate.txt
```
ssh: connect to host flowstate port 22: Connection timed out
```

### scan-geekom.txt
```
ssh: connect to host geekom port 22: Connection refused
```

### scan-mcserver.txt
```
ssh: connect to host 10.0.0.175 port 22: No route to host
```

### scan-monomyth-build.txt
```
=== monomyth-build ===
00:02.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
```

### scan-monster.txt
```
ssh: connect to host 100.126.62.115 port 22: Connection timed out
```

### scan-plex-server.txt
```
=== plex ===
00:02.0 VGA compatible controller [0300]: Intel Corporation TigerLake-LP GT2 [Iris Xe Graphics] [8086:9a49] (rev 01)
```

### scan-pm01.txt
```
=== pm01 ===
01:00.1 VGA compatible controller [0300]: Matrox Electronics Systems Ltd. MGA G200eH3 [102b:0538] (rev 02)
```

### scan-pm02.txt
```
ssh: connect to host 10.0.0.11 port 22: No route to host
```

### scan-pm03.txt
```
ssh: connect to host 10.0.0.12 port 22: No route to host
```

### scan-pm04.txt
```
=== pm04 ===
01:00.1 VGA compatible controller [0300]: Matrox Electronics Systems Ltd. MGA G200eH3 [102b:0538] (rev 02)
```

### scan-readynas.txt
```
=== NAS01 ===
none
```

### scan-rproxy.txt
```
=== rproxy ===
00:02.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
```

### scan-transcrypt01.txt
```
ssh: connect to host transcrypt01 port 22: Connection timed out
```
