#include "classic_api.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void kind(uint8_t *board, int at, int value) {
    static const char hex[] = "0123456789abcdef";
    board[at * 2] = hex[value >> 4];
    board[at * 2 + 1] = hex[value & 15];
}

int main(int argc, char **argv) {
    if (argc == 3) {
        if (!ClassicApiLoad((uint8_t *)argv[1], 1)) return 1;
        for (size_t at = 0; argv[2][at] && !ClassicApiWon(); at++) {
            if (ClassicApiDead()) {
                fprintf(stderr, "Winning route incorrectly pruned before step %zu\n", at + 1);
                return 2;
            }
            const char *action = strchr("0123ft", argv[2][at]);
            if (!action) return 3;
            ClassicApiAct((int)(action - "0123ft"));
        }
        return ClassicApiWon() ? 0 : 4;
    }
    uint8_t board[1441];
    memset(board, '0', 1440); board[1440] = 0;
    kind(board, 13, 10); kind(board, 70, 7);
    assert(ClassicApiLoad(board, 1));
    classic_game.objects[58] = 3;
    classic_game.objects[59] = 2;
    classic_game.ground[60] = 6;
    classic_game.ground[61] = 17;
    assert(!ClassicApiDead());  /* The blue ball can still be painted green. */
    classic_game.ground[61] = 0;
    assert(ClassicApiDead());   /* Spending the last green paint dooms blue. */
    classic_game.objects[59] = 0;
    assert(!ClassicApiDead());
    int doors[] = {14, 92, 104, 105, 107, 110, 113, 116, 117, 118, 119, 120, 121, 123, 124, 125, 126, 127, 128, 129, 130};
    for (size_t at = 0; at < sizeof doors / sizeof doors[0]; at++)
        assert(!classic_api_ClassicApiPermanentWall(doors[at]));
    assert(!classic_api_ClassicApiPermanentWall(62)); /* A bomb can break it. */
    assert(classic_api_ClassicApiPermanentWall(65)); /* Nothing can fill the abyss. */
    puts("Solver: paint resources and dynamic door/crate deadlocks passed");
    return 0;
}
