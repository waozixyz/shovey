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

int main(int argc, char **argv) {
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
    puts("Developer editor saves: live levels, saved proofs, cosmetic edits, played wins and reopening passed");
    return 0;
}
