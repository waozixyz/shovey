/* Real star pushes, observed by the shipped board animation code. */
#include "shovey_board.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#undef main

static BoardEffect *merge(void) {
    BoardEffect *found = NULL;
    for (int i = 0; i < BOARD_EFFECTS; i++) {
        if (board_effects[i].kind == 5) {
            assert(!found);
            found = &board_effects[i];
        }
    }
    return found;
}

int main(void) {
    char board[480];
    memset(board, '0', sizeof board);
    board[1] = 'a';
    board[26] = '1'; board[27] = '3';
    board[28] = '1'; board[29] = '3';
    ShoveyGame loaded;
    String data = {.data = (const uint8_t *)board, .length = sizeof board};
    assert(!engine_ShoveyLoadData(&loaded, 1, data));
    board[28] = board[29] = '0';
    board[50] = '1'; board[51] = '3';
    assert(!engine_ShoveyLoadData(&loaded, 1, data));
    board[50] = board[51] = '0';
    board[30] = '1'; board[31] = '3';
    assert(engine_ShoveyLoadData(&loaded, 1, data));
    board[26] = board[27] = board[30] = board[31] = '0';
    board[22] = board[24] = '1'; board[23] = board[25] = '3';
    assert(engine_ShoveyLoadData(&loaded, 1, data)); /* Row boundaries do not touch. */
    for (int direction = 0; direction < 4; direction++) {
        int meeting = 100;
        int mover = engine_ShoveyNeighbor(meeting, (direction + 2) % 4);
        int player = engine_ShoveyNeighbor(mover, (direction + 2) % 4);
        int partner = engine_ShoveyNeighbor(meeting, direction);
        ShoveyGame initial = {.level = 1, .player = player};
        initial.objects[mover] = initial.objects[partner] = 19;
        ShoveyGame game = initial;
        board_seen = false;
        shovey_board_BoardEffectsNotice(&game, 10.0);
        assert(!merge());
        assert(engine_ShoveyMove(&game, direction));
        assert(!game.objects[meeting] && !game.objects[partner]);
        shovey_board_BoardEffectsNotice(&game, 10.1);
        assert(merge() && merge()->at == meeting && merge()->stars == (1 << direction));
        assert(merge()->start == 10.1);
        shovey_board_BoardEffectsNotice(&game, 10.2);
        assert(merge()->start == 10.1); /* No replay on an unchanged frame. */
        game = initial;
        shovey_board_BoardEffectsNotice(&game, 10.3);
        assert(!merge()); /* Undo/restart clears the old pulse. */

        /* A push can join three stars; capture the whole group in one pulse. */
        int side = (direction + 1) % 4;
        int extra = engine_ShoveyNeighbor(meeting, side);
        game = initial;
        game.objects[extra] = 19;
        board_seen = false;
        shovey_board_BoardEffectsNotice(&game, 11.0);
        assert(engine_ShoveyMove(&game, direction));
        shovey_board_BoardEffectsNotice(&game, 11.1);
        assert(merge() && merge()->stars == ((1 << direction) | (1 << side)));

        /* Moving a star without contact does not animate a disappearance. */
        game = initial;
        game.objects[partner] = 0;
        board_seen = false;
        shovey_board_BoardEffectsNotice(&game, 12.0);
        assert(engine_ShoveyMove(&game, direction));
        shovey_board_BoardEffectsNotice(&game, 12.1);
        assert(!merge() && game.objects[meeting] == 19);
    }
    puts("Local star-merge tests: four push directions, group joins, no false pulse, and undo/restart passed");
    return 0;
}
