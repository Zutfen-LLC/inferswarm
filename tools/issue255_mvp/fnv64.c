/* The pinned RPC FNV-1a cache filename, streaming rather than Python byte loops. */
#include <stdint.h>
#include <stdio.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 3;
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    unsigned char b[1048576];
    size_t n;
    while ((n = fread(b, 1, sizeof b, f)))
        for (size_t i = 0; i < n; ++i) h = (h ^ b[i]) * UINT64_C(0x100000001b3);
    if (ferror(f)) return 4;
    fclose(f);
    printf("%016llx\n", (unsigned long long)h);
    return 0;
}
