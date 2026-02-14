# TODO

* think: are CLI and tool the same?

* polish create_tool flow

* executable permission system for tools/CLIs .READONLY, .ONLY_PASSED_FILES, .NETWORK, .TIMELIMIT, .TOKENLIMIT, .COSTLIMIT, .MODEL

* interactive agent programs by default for follow up prompting (use sessions for continuation)

* store /proc on disk again for multi-process use; add status for 'idle' agents (awaiting user input)
  - /proc agent never really goes away, unless deleted; make sure crashes are handled gracefully somehow (reference host PID)
  - add 'continue' cli to continue an agent session (print UUID when exiting a program); add 'fork' for a continue under a new /proc. Sort 'top' by most recent, with a clear separator on 'active'/'very recently active' ones


# Later

* new runtime: claude code sdk

* jq command, sed

* pipe

* stream redirects to file

* bug: avoid print in tools

* 
