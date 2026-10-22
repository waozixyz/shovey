/* Exercise the developer editor's real save state without opening a display. */
#include "tools/editor/editor.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
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
    if (argc == 2 && strcmp(argv[1], "status") == 0) {
        editor_Open(1);
        assert(editor_Solved() && !editor_NeedsRepair());
        editor_SetKind(editor_Board(1), 14, 0);
        editor_SetKind(editor_Board(1), 15, 7);
        editor_Edited();
        memcpy(check_board, editor_Board(1).data, HEX);
        check_level = current;
        check_state = 3;
        check_wanted = false;
        editor_RememberCheckStatus();
        editor_Open(2);
        editor_Open(1);
        assert(check_state == 3 && editor_Checked() && !check_wanted);
        assert(editor_NeedsRepair());
        FILE *fingerprint = fopen("build/solver/fingerprint", "wb");
        assert(fingerprint);
        fputs("updated-solver", fingerprint);
        fclose(fingerprint);
        editor_Open(1);
        assert(check_state == 0 && check_wanted && !editor_NeedsRepair());
        remove("build/solver/fingerprint");
        editor_SetKind(editor_Board(1), SHOVEY_CELLS * 2 + 14, 57);
        editor_Edited();
        assert(!editor_RestoreCheckStatus() && check_wanted);
        editor_SetKind(editor_Board(1), 13, 0);
        editor_Edited();
        editor_StartCheck();
        assert(check_state == 4 && editor_NeedsRepair());
        editor_Open(1);
        assert(check_state == 4 && !check_wanted);
        uint8_t pretty[HEX];
        memcpy(pretty, editor_Board(1).data, HEX);
        editor_SetKind((Slice){pretty, HEX}, SHOVEY_CELLS * 2 + 14, 59);
        glm_mode = 2;
        glm_result(pretty, pretty, NULL);
        assert(memcmp(pretty, editor_Board(1).data, HEX) == 0);
        assert(check_state == 4 && !check_wanted && !editor_Proven());
        editor_SetKind((Slice){pretty, HEX}, SHOVEY_CELLS + 15, 14);
        assert(!editor_PrettifyOnly(editor_Board(1), (Slice){pretty, HEX}));
        editor_SetKind((Slice){pretty, HEX}, SHOVEY_CELLS + 15, 0);
        editor_SetKind((Slice){pretty, HEX}, 15, 131);
        assert(!editor_PrettifyOnly(editor_Board(1), (Slice){pretty, HEX}));
        puts("Completed check status survives reopening only for the same board; Fix it stays hidden for verified wins");
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "update") == 0) {
        editor_Open(1);
        assert(editor_Solved() && saved_approval_ready);
        server_configured = server_verified = true;
        published_places[0] = approved_places[0] = true;
        memcpy(published_boards, editor_Board(1).data, HEX);
        memcpy(approved_boards, editor_Board(1).data, HEX);
        /* Move home beyond the saved route. Update must check the new board
           instead of publishing the still-valid saved older board. */
        editor_SetKind(editor_Board(1), 14, 0);
        editor_SetKind(editor_Board(1), 15, 7);
        editor_Edited();
        proof_length = check_state = 0;
        assert(saved_approval_ready && editor_UpdateAvailable());
        editor_UpdateEdit();
        assert(check_state == 1 && editor_Checked());
        assert(action_message_length == 0 && !editor_NeedsRepair());
        assert(access("backup/editor-drafts/001.approval-request", F_OK) != 0);
        int64_t started = check_started;
        sleep(1);
        editor_UpdateEdit();
        assert(check_started == started); /* A second click keeps the search. */
        for (int i = 0; i < 10 && check_state == 1; i++) {
            editor_PollCheck();
            if (check_state == 1) sleep(1);
        }
        assert(editor_Solved());
        editor_AutoSave();
        assert(save_state == 2 && editor_ApprovalMatches(1));
        assert(memcmp(approved_boards, published_boards, HEX) != 0);
        FILE *request = fopen("backup/editor-drafts/001.approval-request", "rb");
        assert(request);
        uint8_t requested[HEX];
        assert(fread(requested, 1, HEX, request) == HEX);
        fclose(request);
        assert(memcmp(requested, editor_Board(1).data, HEX) == 0);
        memcpy(publish_message, "Publishing…", strlen("Publishing…"));
        publish_message_length = strlen("Publishing…");
        assert(!editor_UpdateAvailable());
        puts("Update checks the latest draft, reuses an active search and queues only its verified board");
        return 0;
    }
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
    /* Every low score is green; high scores stay red even for waiting places.
       Adjacent scores shift gently across the 50/70/90 boundaries. */
    Color last = editor_SimilarityColor(0);
    for (int score = 0; score <= 100; score++) {
        Color color = editor_SimilarityColor(score);
        if (score < 50) assert(color.g > color.r && color.g > color.b);
        if (score >= 90) assert(color.r > 2 * color.g && color.r > 2 * color.b);
        assert(abs((int)color.r - last.r) <= 8);
        assert(abs((int)color.g - last.g) <= 8);
        assert(abs((int)color.b - last.b) <= 8);
        last = color;
    }
    Color waiting = editor_LevelCardColor(73, 99);
    assert(waiting.r > 2 * waiting.g && waiting.r > 2 * waiting.b);
    /* Canonical approvals color published levels even without local markers.
       Opening the map refreshes approvals made after this process started. */
    assert(!editor_Approved(23));
    editor_ToggleSelector();
    assert(selector_open && editor_Approved(21) && editor_Approved(22) && editor_Approved(23));
    assert(!editor_Approved(20) && !editor_Approved(24));
    editor_ToggleSelector();
    assert(!selector_open);
    remove("backup/editor-drafts/orientation");
    editor_LoadOrientation();
    assert(boards_landscape);
    editor_RotateBoards();
    assert(!boards_landscape);
    boards_landscape = true;
    editor_LoadOrientation();
    assert(!boards_landscape);
    editor_RotateBoards();
    boards_landscape = false;
    editor_LoadOrientation();
    assert(boards_landscape);
    boards_landscape = false; /* The following fixtures exercise portrait cells. */
    editor_Open(1);
    assert(editor_Solved() && save_state == 2 && !check_wanted);
    /* Approval still accepts the saved win after a later unproven draft. */
    uint8_t saved_win[HEX];
    memcpy(saved_win, editor_SavedBoard(1).data, HEX);
    editor_SetKind(editor_Board(1), 14, 0);
    editor_Edited();
    proof_length = 0; check_state = 0;
    assert(saved_approval_ready && editor_ApprovalAvailable());
    editor_ApproveEdit();
    assert(editor_Approved(1));
    assert(memcmp(approved_boards, saved_win, HEX) == 0);
    assert(editor_KindAt(editor_Board(1), 14) == 0);
    memcpy(editor_Board(1).data, saved_win, HEX);
    approved_places[0] = false;
    remove("backup/editor-drafts/001.approved");
    remove("backup/editor-drafts/001.approval-request");
    remove("backup/editor-drafts/001.hex");
    editor_Open(1);
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
    /* When a reference exists, Reset copies every original layer, rather
       than the draft that happened to be open. Undo restores that draft. */
    uint8_t before_reset[HEX], reset_reference[HEX];
    memcpy(before_reset, editor_Board(1).data, HEX);
    memcpy(editor_Original(1).data, before_reset, HEX);
    original_found[1] = true;
    editor_SetKind(editor_Original(1), 15, 9);
    editor_SetKind(editor_Original(1), SHOVEY_CELLS + 15, 99);
    editor_SetKind(editor_Original(1), SHOVEY_CELLS * 2 + 15, 57);
    memcpy(reset_reference, editor_Original(1).data, HEX);
    editor_ResetEdit();
    assert(memcmp(editor_Board(1).data, reset_reference, HEX) == 0);
    editor_UndoEdit();
    assert(memcmp(editor_Board(1).data, before_reset, HEX) == 0);
    editor_RedoEdit();
    assert(memcmp(editor_Board(1).data, reset_reference, HEX) == 0);
    editor_UndoEdit();
    original_found[1] = false;
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
    /* The same control can retry publication without rechecking its proof. */
    proof_length = 0;
    check_state = 0;
    memcpy(published_boards, approved_boards, HEX);
    published_places[0] = true;
    assert(!editor_ApprovalAvailable());
    editor_ApproveEdit();
    assert(!editor_ApprovalAvailable());
    /* A failure elsewhere cannot reenable a level already up to date. */
    memcpy(publish_message, "Update failed. Retry.", 21);
    publish_message_length = 21;
    assert(!editor_ApprovalAvailable());
    published_places[0] = false;
    assert(editor_ApprovalAvailable());
    editor_ApproveEdit();
    assert(editor_Approved(1) && check_state == 0 && proof_length == 0);
    editor_Remember(true);
    editor_SetKind(editor_Board(1), SHOVEY_CELLS * 2 + 13, 59);
    editor_Edited();
    assert(editor_Approved(1) && !editor_ApprovalMatches(1));
    editor_UndoEdit();
    assert(editor_Approved(1) && editor_ApprovalMatches(1));
    editor_RedoEdit();
    editor_StartCheck();
    assert(editor_Solved() && editor_Approved(1) && !editor_ApprovalMatches(1));
    editor_AutoSave();
    /* A queued approval has never been published: later saves still need
       an explicit approval, rather than silently replacing that request. */
    assert(save_state == 2 && !editor_ApprovalMatches(1));
    published_places[0] = true;
    editor_AutoSave();
    assert(save_state == 2 && editor_ApprovalMatches(1));
    /* Change the route, play the new win, and save without a solver search. */
    editor_SetKind(editor_Board(1), 14, 0);
    editor_SetKind(editor_Board(1), 15, 7);
    editor_SetKind(editor_Board(1), SHOVEY_CELLS + 15, 0);
    editor_Edited();
    editor_StartPlay();
    editor_PlayAct(2);
    editor_PlayAct(2);
    assert(play.won && editor_Proven() && editor_Solved() && !check_wanted);
    /* Completed play teaches a reusable route even after the latest proof
       is replaced or removed by later editing. */
    remove("backup/editor-drafts/001.proof");
    proof_length = 0;
    check_state = 0;
    assert(editor_RestoreLearnedRoute() && editor_Solved());
    assert(route_length == 2 && route[0] == '2' && route[1] == '2');
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
    glm_repair = true;
    glm_result(candidate, candidate, "22");
    assert(action_message_length == 14 && memcmp(action_message, "Repair applied", 14) == 0);
    glm_repair = false;
    assert(memcmp(candidate, editor_Board(1).data, HEX) == 0);
    assert(editor_Proven() && editor_Solved() && !check_wanted);
    editor_UndoEdit();
    assert(memcmp(before, editor_Board(1).data, HEX) == 0);
    editor_RedoEdit();
    assert(memcmp(candidate, editor_Board(1).data, HEX) == 0);
    /* A worker's short progress labels do not mark the request finished.
       Completed GLM feedback survives polling an unchanged publish status. */
    FILE *status = fopen("backup/editor-drafts/publish-status", "wb");
    assert(status); fputs("Published", status); fclose(status);
    editor_PollActions(actions_polled + 500);
    glm_busy = true; glm_place = current;
    glm_started = actions_polled;
    status = fopen("backup/editor-drafts/001.glm-status", "wb");
    assert(status); fputs("Checking variation…", status); fclose(status);
    status = fopen("backup/editor-drafts/001.glm-state", "wb");
    assert(status); fputs("working", status); fclose(status);
    editor_PollActions(actions_polled + 500);
    assert(glm_busy);
    status = fopen("backup/editor-drafts/001.glm-state", "wb");
    assert(status); fputs("error", status); fclose(status);
    editor_PollActions(actions_polled + 500);
    assert(!glm_busy);
    editor_ActionMessage((String){"Variation applied", 17});
    editor_PollActions(actions_polled + 500);
    assert(action_message_length == 17 && memcmp(action_message, "Variation applied", 17) == 0);
    for (int color = 0; color < 4; color++) {
        int kind = SHOVEY_OPEN_GATE + color;
        int sprite = color == 0 ? SPRITE_GATE_OPEN : SPRITE_COLORED_GATE + (color - 1) * 4 + 1;
        assert(editor_PrivateSprite(kind) == sprite);
        assert(shovey_board_KindSprite(&facing, kind, -1, 0, false) == sprite);
    }
    palette_tab = 1;
    int walls[] = {12, 14, 95, 96, 97, 98, 127, 128, 129, 130};
    for (int i = 0; i < 10; i++) {
        int material = walls[i];
        editor_SetKind(editor_Board(1), 26, 0);
        editor_SetKind(editor_Board(1), SHOVEY_CELLS + 26, material);
        editor_Paint(26, SHOVEY_DOOR);
        assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS + 26) == material);
        ShoveyGame opened = {0};
        opened.ground[26] = SHOVEY_DOOR_OPEN;
        int floor = engine_ShoveyWallFloor(material);
        int floor_sprite = floor == 0 ? 0 : SPRITE_MATERIAL_FLOOR + floor - 99;
        assert(shovey_board_KindSprite(&opened, material, 26, 0, false) == floor_sprite);
        editor_Paint(26, 9);
        assert(editor_KindAt(editor_Board(1), SHOVEY_CELLS + 26) == 0);
    }
    for (int color = 0; color < 5; color++) {
        int wall = color == 0 ? 14 : SHOVEY_MOSS_WALL + color - 1;
        int button = color == 0 ? 13 : SHOVEY_MOSS_BUTTON + color - 1;
        ShoveyGame moss = {0};
        moss.ground[26] = wall;
        moss.ground[27] = button;
        moss.objects[27] = 9;
        int floor_sprite = color == 0 ? 0 : SPRITE_MATERIAL_FLOOR + color - 1;
        assert(shovey_board_KindSprite(&moss, wall, 26, 0, false) == floor_sprite);
    }
    /* A changed board has an Update action even before its proof is ready.
       A saved, proven board updates without starting another solver run. */
    remove("backup/editor-drafts/001.hex");
    load();
    editor_Open(1);
    assert(editor_Solved());
    approved_places[0] = true;
    memcpy(approved_boards, editor_Board(1).data, HEX);
    memcpy(published_boards, editor_Board(1).data, HEX);
    server_configured = true;
    server_verified = true;
    published_places[0] = true;
    publish_message_length = 0;
    assert(!editor_NeedsUpdate(1));
    editor_SetKind((Slice){published_boards, HEX}, SHOVEY_CELLS + 13, 99);
    editor_SetKind((Slice){published_boards, HEX}, SHOVEY_CELLS * 2 + 13, 57);
    assert(editor_NeedsUpdate(1) && editor_UpdateAvailable());
    assert(editor_DifferenceCount(1) == 1);  /* Count cells, not changed layers. */
    assert(editor_DifferenceAt(1, 13) && !editor_DifferenceAt(1, 14));
    published_places[0] = false;
    assert(!editor_NeedsUpdate(1)); /* First publication always says Approve. */
    published_places[0] = true;
    editor_UpdateEdit();
    assert(editor_Solved() && check_state != 1);
    proof_length = 0;
    check_state = 0;
    assert(editor_UpdateAvailable());
    playing = true;
    assert(!editor_UpdateAvailable());
    playing = false;
    check_state = 1;
    assert(editor_UpdateAvailable());
    editor_UpdateEdit();
    assert(editor_Solved() && check_state != 1 && !check_wanted);
    proof_length = 0;
    check_state = 0;
    /* Solution state has its own message even while a publishing message exists. */
    editor_ActionMessage((String){"Published", 9});
    check_level = current;
    memcpy(check_board, editor_Board(current).data, HEX);
    check_state = 1;
    String solution = editor_SolutionText();
    assert(solution.length >= 8 && memcmp(solution.data, "Checking", 8) == 0);
    check_state = 3;
    solution = editor_SolutionText();
    assert(solution.length == 17 && memcmp(solution.data, "No solution found", 17) == 0);
    check_state = 0;
    solution = editor_SolutionText();
    assert(solution.length == 11 && memcmp(solution.data, "Not checked", 11) == 0);
    puts("Developer editor: saves, recovered wins, verified GLM results and undo/redo passed");
    return 0;
}
