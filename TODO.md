# TODO

* store /proc on disk again for multi-process use; add status for 'idle' agents (awaiting user input)
  - /proc agent never really goes away, unless deleted; make sure crashes are handled gracefully somehow (liveness check)

* cron system


# Later

- add 'fork' for a continue under a new /proc. Sort 'top' by most recent, with a clear separator on 'active'/'very recently active' ones

* executable permission system for tools/CLIs .READONLY, .ONLY_PASSED_FILES, .NETWORK, .TIMELIMIT, .TOKENLIMIT, .COSTLIMIT, .MODEL

* new runtime: claude code

* jq command, sed

* pipe

* stream redirects to file

* bug: avoid print in tools