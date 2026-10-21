#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "solvebench.h"
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(int argc, char **argv) {
    int island = atoi(argv[1]), from = atoi(argv[2]), to = atoi(argv[3]), only = argc > 4 ? atoi(argv[4]) : -1;
    for (int level = from; level <= to; level++) {
        long long w0 = BenchWork(); double t = now();
        int status = BenchSolve(island, level, only);
        printf("%s %d status %d search %d states %lld route %d work %lld %.3fs\n", island ? "island" : "classic", level, status, BenchSearch(), (long long)BenchStates(), BenchRouteLength(), (long long)(BenchWork()-w0), now()-t);
        fflush(stdout);
    }
}
