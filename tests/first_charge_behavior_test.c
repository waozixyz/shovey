/* Replay real engine moves through the board effect observer. */
#include "shovey_board.h"
#include <assert.h>
#include <stdio.h>
#undef main

static int charge_effects(void) {
    int count = 0;
    for (int i = 0; i < BOARD_EFFECTS; i++) count += board_effects[i].kind == 4;
    return count;
}

static void first_charge_feedback(void) {
    ShoveyGame start = {.level = 1, .player = 13};
    start.ground[14] = start.ground[15] = 27;
    ShoveyGame game = start;
    board_seen = false;
    shovey_board_BoardEffectsNotice(&game, 10.0);
    assert(charge_effects() == 0);
    assert(engine_ShoveyMove(&game, 2));
    assert(!game.lost && (game.powers & SHOVEY_CHARGED));
    shovey_board_BoardEffectsNotice(&game, 10.1);
    assert(charge_effects() == 1);
    assert(board_effects[0].at == 14 && board_effects[0].start == 10.1);
    shovey_board_BoardEffectsNotice(&game, 10.2);
    assert(charge_effects() == 1 && board_effects[0].start == 10.1);

    /* The next touch still loses and replaces the pickup with the fatal shock. */
    assert(engine_ShoveyMove(&game, 2) && game.lost);
    shovey_board_BoardEffectsNotice(&game, 10.3);
    assert(charge_effects() == 0);
    assert(shovey_board_ShockProgress(&game, 10.3) == 0.0f);

    /* Undo/restart clears the burst; a fresh touch can show it again. */
    game = start;
    shovey_board_BoardEffectsNotice(&game, 10.4);
    assert(charge_effects() == 0);
    assert(engine_ShoveyMove(&game, 2));
    shovey_board_BoardEffectsNotice(&game, 10.5);
    assert(charge_effects() == 1);

    /* A second accepted move before drawing must not hide the pickup. */
    game = start;
    shovey_board_BoardEffectsNotice(&game, 11.0);
    assert(engine_ShoveyMove(&game, 2));
    assert(engine_ShoveyMove(&game, 3));
    shovey_board_BoardEffectsNotice(&game, 11.1);
    assert(charge_effects() == 1 && !game.lost);

    /* Loading an already charged save, or another level, is not a new touch. */
    board_seen = false;
    shovey_board_BoardEffectsNotice(&game, 12.0);
    assert(charge_effects() == 0);
    game.level++;
    game.moves++;
    shovey_board_BoardEffectsNotice(&game, 12.1);
    assert(charge_effects() == 0);
    board_seen = false;
}

int main(void) {
    first_charge_feedback();
    puts("Local first-charge tests: pickup, second-touch loss, restart, skipped frames and loaded saves passed");
    return 0;
}
