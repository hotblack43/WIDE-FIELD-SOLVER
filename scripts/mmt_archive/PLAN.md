# MMT archive downloader plan

The user authorizes a standalone downloader and a real download attempt. Keep
all preserved solver runtimes and dependency locks unchanged.

1. Inspect listings, two original FITS headers, adjacent archive JPEG timing
   labels, and manufacturer/observatory documentation before implementation.
2. Test listing normalization, local/UTC timestamp consistency, corrupt bz2 and
   truncated FITS rejection, whole-exposure boundaries, and full-night Moon checks.
3. Implement one standalone Python script with explicit astronomical conventions,
   exhaustive header inventory, bounded HTTP retries, verified resumable downloads,
   byte-preserving decompression, CSV manifests and JSON/CSV selection evidence.
4. Run the tests and a real inventory/download. Respect available disk space;
   report incomplete downloads rather than claiming a complete night.
5. Deliver pinned dependencies, Ubuntu commands, provenance and measured results.
