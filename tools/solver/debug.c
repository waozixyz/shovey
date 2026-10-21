#include <stdio.h>
#include "solver.h"
#include "island_levels.h"
int main(void) {
    int number=119; String board=island_levels_IslandLevelData(number);
    solver_SolverStart(true,board,solver_SolverDefaultLimits()); solver_board.data=NULL; solver_board.length=0;
    while(solver_SolverStatus()==SOLVER_RUNNING) solver_SolverRun(20000);
    printf("status=%d search=%d states=%lld route=%d\n",solver_SolverStatus(),solver_search,(long long)solver_SolverStates(),solver_route_length);
}
