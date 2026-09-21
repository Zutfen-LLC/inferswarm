# Incident record — authorized_keys damage on inferswarm01 (2026-09-20)

During R8-H Phase 0 staging, while attempting to establish a one-time
02->01 transfer trust, the controller executed a second authorized_keys
edit through double-nested SSH quoting. A mis-aimed sed plus a
`head -1` truncation replaced hermes@inferswarm01's authorized_keys
with a single garbage line, removing the controller's authorization.

Impact: no inbound SSH to hermes@inferswarm01 for the controller or any
fleet node for the duration (no node-to-node trust existed). No other
system state was modified; the model bytes, repos, and services on 01
were untouched and verified intact after repair.

Recovery: operator console repair 2026-09-20 (sudo tee, single
controller key line, chown/chmod normalized, chattr +i immutable flag
applied). Controller reconnect verified (hostname/id/sudo/key-count/
lsattr) immediately after.

Remediation (all implemented same day):
- skill ssh-trust-and-access-recovery: two pitfall entries + mandatory
  scripts/ak_safe_swap.sh (stage-file swap, checksum both sides,
  independent reconnect probe) as the ONLY sanctioned edit path;
- standing memory rule: skill load + operator pre-approval before any
  trust edit; controller-relay streaming is the default for transfers;
- inferswarm01 authorized_keys now immutable (chattr +i);
- the transfer was re-planned as controller-relay streaming
  (ssh src sudo cat | ssh dst cat), requiring zero trust changes.

This incident is retained as campaign evidence per issue #234 Phase 0
item 1 (record exact host state) and the fleet's negative-result
discipline.
