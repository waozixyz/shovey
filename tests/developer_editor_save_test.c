/* Exercise the developer editor's real save state without opening a display. */
#include "tools/editor/editor.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#undef main

static void load(void) {
    editor_LoadOriginals();
    editor_LoadUnlinked();
    editor_LoadLevels();
    editor_LoadDrafts();
}

static void glm_result(const uint8_t *candidate, const uint8_t *proof_board, const char *route) {
    glm_busy = true;
    glm_place = current;
    memcpy(glm_base, editor_Board(current).data, HEX);
    FILE *file = fopen("backup/editor-drafts/001.glm-result", "wb");
    assert(file);
    assert(fwrite(candidate, 1, HEX, file) == HEX);
    fclose(file);
    if (route) {
        file = fopen("backup/editor-drafts/001.glm-proof", "wb");
        assert(file);
        assert(fwrite(proof_board, 1, HEX, file) == HEX);
        fprintf(file, "\n%s", route);
        fclose(file);
    } else {
        remove("backup/editor-drafts/001.glm-proof");
    }
    editor_PollActions(actions_polled + 500);
    assert(!glm_busy);
}

int main(int argc, char **argv) {
    /* Starting sprites face up in either presentation; recorded movement
       directions keep their existing board-relative meaning. */
    ShoveyGame facing = {0};
    facing.direction = 1;
    facing.light_from[13] = 4;
    assert(shovey_board_PlayerSprite(&facing, false) == SPRITE_PLAYER + 1);
    assert(shovey_board_PlayerSprite(&facing, true) == SPRITE_PLAYER + 2);
    int animals[] = {SHOVEY_CHICKEN, SHOVEY_TURTLE, SHOVEY_CRAB, SHOVEY_FISH};
    int sprites[] = {SPRITE_DOG, SPRITE_TURTLE, SPRITE_CRAB, SPRITE_FISH};
    for (int i = 0; i < 4; i++) {
        assert(shovey_board_KindSprite(&facing, animals[i], 13, 0, false) == sprites[i] + 1);
        assert(shovey_board_KindSprite(&facing, animals[i], 13, 0, true) == sprites[i] + 2);
    }
    facing.moves = 1;
    for (int direction = 0; direction < 4; direction++) {
        facing.direction = direction;
        facing.light_from[13] = direction;
        assert(shovey_board_PlayerSprite(&facing, true) == SPRITE_PLAYER + direction);
        assert(shovey_board_KindSprite(&facing, SHOVEY_CHICKEN, 13, 0, true) == SPRITE_DOG + direction);
    }
    load();
    if (argc == 3 && strcmp(argv[1], "recover") == 0) {
        editor_Open(atoi(argv[2]));
        assert(editor_Proven() || editor_Solved());
        editor_AutoSave();
        if (save_state != 2) {
            fprintf(stderr, "Save failed: %.*s\n", save_message_length, save_message);
            return 1;
        }
        printf("Recovered level %d, saved with its existing %d-move win\n", current, route_length);
        return 0;
    }
    assert(level_count == 2 && mapping_ok);
    editor_Open(1);
    assert(editor_Solved() && save_state == 2 && !check_wanted);
    /* Editor history survives auto-saving; reset returns to the opened board. */
    int original = editor_KindAt(editor_Board(1), SHOVEY_CELLS * 2 + 13);
    editor_Remember(true);
    editor_SetKind(editor_Board(1), SHOVEY_CELLS * 2 + 13, 57);
    editor_Edited();
    editor_UndoEdit();
    assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS * 2 + 13) == original);
    editor_RedoEdit();
    assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS * 2 + 13) == 57);
    editor_ResetEdit();
    assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS * 2 + 13) == original);
    editor_UndoEdit();
    assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS * 2 + 13) == 57);
    editor_ResetEdit();
    editor_StartCheck();
    assert(editor_Solved() && check_state != 1);
    /* Cosmetic edits reuse the existing route and save all three layers. */
    palette_tab = 2;
    editor_Paint(13, 512 + 57);
    editor_StartCheck();
    assert(editor_Solved() && route_length == 1);
    editor_AutoSave();
    assert(save_state == 2);
    editor_Open(2);
    editor_Open(1);
    assert(editor_Solved() && save_state == 2 && !check_wanted);
    editor_ApproveEdit();
    assert(editor_Approved(1));
    editor_Remember(true);
    editor_SetKind(editor_Board(1), SHOVEY_CELLS * 2 + 13, 59);
    editor_Edited();
    assert(!editor_Approved(1));
    editor_UndoEdit();
    assert(editor_Approved(1));
    /* Change the route, play the new win, and save without a solver search. */
    editor_SetKind(editor_Board(1), 14, 0);
    editor_SetKind(editor_Board(1), 15, 7);
    editor_SetKind(editor_Board(1), SHOVEY_CELLS + 15, 0);
    editor_Edited();
    editor_StartPlay();
    editor_PlayAct(2);
    editor_PlayAct(2);
    assert(play.won && editor_Proven() && editor_Solved() && !check_wanted);
    editor_AutoSave();
    assert(save_state == 2 && route_length == 2);
    /* Clear process-local proof, as happens when the application restarts. */
    proof_length = 0;
    check_state = 0;
    save_state = 0;
    load();
    editor_Open(1);
    assert(editor_Solved() && save_state == 2 && !check_wanted);
    /* GLM files cannot replace an authored level without an exact winning proof. */
    uint8_t before[HEX], candidate[HEX];
    memcpy(before, editor_Board(1).data, HEX);
    memcpy(candidate, before, HEX);
    editor_SetKind((Slice){candidate, HEX}, SHOVEY_CELLS * 2 + 15, 59);
    glm_result(candidate, candidate, NULL);
    assert(memcmp(before, editor_Board(1).data, HEX) == 0);
    glm_result(candidate, before, "22");  /* A proof for a different board. */
    assert(memcmp(before, editor_Board(1).data, HEX) == 0);
    glm_result(candidate, candidate, "0");  /* A claimed win that does not win. */
    assert(memcmp(before, editor_Board(1).data, HEX) == 0);
    assert(editor_Proven() && proof_length == 2 && proof_route[0] == '2' && proof_route[1] == '2');
    glm_result(candidate, candidate, "22");
    assert(memcmp(candidate, editor_Board(1).data, HEX) == 0);
    assert(editor_Proven() && editor_Solved() && !check_wanted);
    editor_UndoEdit();
    assert(memcmp(before, editor_Board(1).data, HEX) == 0);
    editor_RedoEdit();
    assert(memcmp(candidate, editor_Board(1).data, HEX) == 0);
    puts("Developer editor: saves, recovered wins, verified GLM results and undo/redo passed");
    return 0;
}
