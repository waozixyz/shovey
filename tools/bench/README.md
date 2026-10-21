# Recovered solver probes

These authored probes were recovered from the ignored build directory.
`solvebench.zi` and `main.c` expose a native solver timing driver;
`bench.zi`, `bench2.zi`, `eq.zi` and `vmbench.zi` isolate copying, encoding,
equality and VM work. `steps/` measures work across editor-sized frames.
`t/` contains the small VM host experiments used for those measurements.

Use `make bench` for the maintained story-level benchmark. Build generated
C, bundles and executables under `build/`; keep source probes here.
