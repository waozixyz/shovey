#include "classic_api.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc == 3) {
        assert(ClassicApiLoad((uint8_t *)argv[1], 1));
        int pushes = 0, off_path = 0;
        for (int step = 0; argv[2][step] && !ClassicApiWon(); step++) {
            int action = (int)(strchr("0123ft", argv[2][step]) - "0123ft");
            ClassicApiFocus();
            int cost = ClassicApiActionCost(action);
            int at = action < 4 ? engine_ShoveyNeighbor(classic_game.player, action) : -1;
            int crate = at >= 0 && classic_game.objects[at] == 9;
            if (ClassicApiAct(action) && crate) { pushes++; off_path += cost > 1; }
        }
        assert(ClassicApiWon());
        printf("Winning route: %d crate pushes, %d initially off the estimated routes\n", pushes, off_path);
        return 0;
    }
    if (argc == 2) {
        assert(ClassicApiLoad((uint8_t *)argv[1], 1));
        ClassicApiFocus();
        int crates = 0, relevant = 0;
        for (int at = 0; at < 240; at++) if (classic_game.objects[at] == 9) {
            crates++;
            relevant += classic_focus[at];
        }
        printf("Crates on objective routes: %d of %d\n", relevant, crates);
        return 0;
    }
    uint8_t board[1441];
    memset(board, '0', 1440); board[1440] = 0;
    const char *hex = "0123456789abcdef";
    for (int at = 0; at < 240; at++) {
        if (at % 12 == 0 || at % 12 == 11 || at < 12 || at >= 228 || (at / 12 == 2 && at % 12 != 8)) {
            board[480 + at * 2] = '0'; board[481 + at * 2] = 'c';
        }
    }
    int cells[] = {13, 17, 22, 122};
    int kinds[] = {10, 9, 7, 9};
    for (int i = 0; i < 4; i++) {
        board[cells[i] * 2] = hex[kinds[i] >> 4];
        board[cells[i] * 2 + 1] = hex[kinds[i] & 15];
    }
    assert(ClassicApiLoad(board, 1));
    ClassicApiFocus();
    assert(classic_focus[17] && !classic_focus[122]);
    ClassicApiSetWalker(16 * 4);
    ClassicApiReset();
    assert(ClassicApiActionCost(2) == 1);
    ClassicApiSetWalker(123 * 4);
    ClassicApiReset();
    assert(ClassicApiActionCost(0) > 1);
    assert(ClassicApiAct(0));
    assert(classic_game.objects[121] == 9);
    puts("Objective-route crates are preferred; unrelated spare-crate pushes remain available");
    return 0;
}
