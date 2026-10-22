// Puzzle solver for both Shovey editions. All rules run in the shipped Ziran
// engine through a thin wrapper (classic_api.zi or island_api.zi); this file
// only searches. Build once per edition with -DSHOVEY_CLASSIC or
// -DSHOVEY_ISLAND (see build.sh).
//
//   solve  [options] BOARDHEX          prints the action string or "unsolved"
//   verify [--level N] BOARDHEX ROUTE   exits 0 only when ROUTE wins
//
// The wrapper encodes every behavior-relevant field of a game as a fixed
// state vector. States are stored as a compact difference from the start
// vector in an arena, deduplicated by open-addressing hash sets, and linked
// to their parent so a route can be rebuilt. Three searches run in turn
// until one wins, each within its share of the time limit:
//
//   bfs        exact breadth-first search over single actions. It returns a
//              shortest route; when it exhausts every reachable state, the
//              board is proven unsolvable and the later searches are skipped.
//   greedy     best-first search over macro actions, ordered by the
//              wrapper's goal estimate (see below).
//   macro-bfs  breadth-first search over macro actions.
//
// A macro action is any action other than a free walk, taken from any cell
// Shovey can reach by free walks. A free walk is a move after which the
// engine's state vector differs only in Shovey's cell (and facing, when the
// wrapper keeps one); it is detected by running the engine, never assumed.
// Every state whose Shovey region has already been expanded is skipped, so
// rooms full of crates collapse to their crate layouts. A region is keyed by
// its smallest walker; were free walks ever one-way, two different regions
// could share that key, so the macro searches prove nothing when they fail.
// Every route they find is the engine's own sequence of moves, and solve_all
// replays it with verify.
//
// Route letters: '0'..'3' press left, up, right, down; Classic adds 'f' to
// fire and 't' for one tick of the autonomous moving block (ground 29). The
// block runs on a timer and Shovey may act any number of times between ticks,
// so a tick is an optional action wherever it is taken.
#define _POSIX_C_SOURCE 200809L
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

#if defined(SHOVEY_CLASSIC)
#include "classic_api.h"
#define API(name) ClassicApi##name
static const char EDITION[] = "classic";
static const char LETTERS[] = "0123ft";
#elif defined(SHOVEY_ISLAND)
#include "island_api.h"
#define API(name) IslandApi##name
static const char EDITION[] = "island";
static const char LETTERS[] = "0123";
#else
#error "Define SHOVEY_CLASSIC or SHOVEY_ISLAND"
#endif

#define ACTIONS ((int)(sizeof LETTERS - 1))
#define NO_PARENT UINT32_MAX
#define CELLS 240
#define WALKERS (CELLS * 8)

typedef struct {
    int level;
    uint64_t max_states;
    uint64_t max_bytes;
    double seconds;
    double bfs_share;
    double greedy_share;
    int weight;
    const char *only;
    const char *prefix;
    bool repair;
} Options;

typedef enum { STOP_NONE, STOP_SOLVED, STOP_EXHAUSTED, STOP_STATES, STOP_MEMORY, STOP_TIME } Stop;

static const char *StopName(Stop stop) {
    switch (stop) {
    case STOP_SOLVED: return "solved";
    case STOP_EXHAUSTED: return "exhausted";
    case STOP_STATES: return "state-limit";
    case STOP_MEMORY: return "memory-limit";
    case STOP_TIME: return "time-limit";
    default: return "none";
    }
}

static void *Resize(void *data, uint64_t bytes) {
    void *resized = realloc(data, bytes);
    if (!resized && bytes) { fprintf(stderr, "out of memory\n"); exit(3); }
    return resized;
}

static double Now(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec + (double)now.tv_nsec / 1e9;
}

// ---------------------------------------------------------------------------
// State vectors and keys

static int state_size, player_byte, facing_byte, facings;
static uint8_t *root_vector;   // start state; keys are differences from it
static uint8_t *work_vector;   // decoded state being expanded
static uint8_t *next_vector;   // encoded successor
static uint8_t *key_buffer;    // compressed successor

static void Encode(uint8_t *vector) {
    if (!API(Encode)(vector)) {
        fprintf(stderr, "state value does not fit the solver encoding\n");
        exit(3);
    }
}

// Difference encoding: (skip, value) pairs for each byte unlike the start
// vector, where skip counts unchanged bytes since the previous pair; a skip
// byte of 255 advances 255 bytes and carries no value. It is canonical, so
// equal states always have equal keys.
static int Compress(const uint8_t *vector, uint8_t *out) {
    int length = 0, position = 0;
    for (int at = 0; at < state_size; at++) {
        if (vector[at] == root_vector[at]) continue;
        int skip = at - position;
        while (skip >= 255) { out[length++] = 255; skip -= 255; }
        out[length++] = (uint8_t)skip;
        out[length++] = vector[at];
        position = at + 1;
    }
    if (length > 0xffff) { fprintf(stderr, "state key too long\n"); exit(3); }
    return length;
}

static void Decompress(const uint8_t *key, int length, uint8_t *vector) {
    memcpy(vector, root_vector, (size_t)state_size);
    int position = 0;
    for (int at = 0; at < length;) {
        uint8_t skip = key[at++];
        if (skip == 255) { position += 255; continue; }
        position += skip;
        vector[position++] = key[at++];
    }
}

static uint32_t Hash(const uint8_t *data, int length) {
    uint64_t hash = 0x9e3779b97f4a7c15ull ^ (uint64_t)length;
    int at = 0;
    for (; at + 8 <= length; at += 8) {
        uint64_t word;
        memcpy(&word, data + at, 8);
        hash = (hash ^ word) * 0xff51afd7ed558ccdull;
        hash ^= hash >> 32;
    }
    uint64_t tail = 0;
    memcpy(&tail, data + at, (size_t)(length - at));
    hash = (hash ^ tail) * 0xc4ceb9fe1a85ec53ull;
    hash ^= hash >> 29;
    return (uint32_t)hash;
}

// A walker is Shovey's cell and, when the wrapper keeps one, facing.
static int WalkerOf(const uint8_t *vector) {
    return vector[player_byte] * facings + (facing_byte >= 0 ? vector[facing_byte] : 0);
}

static void SetWalker(uint8_t *vector, int walker) {
    vector[player_byte] = (uint8_t)(walker / facings);
    if (facing_byte >= 0) vector[facing_byte] = (uint8_t)(walker % facings);
}

// Whether after differs from before only in the walker bytes.
static bool FreeWalk(uint8_t *before, const uint8_t *after) {
    uint8_t player = before[player_byte], facing = facing_byte >= 0 ? before[facing_byte] : 0;
    before[player_byte] = after[player_byte];
    if (facing_byte >= 0) before[facing_byte] = after[facing_byte];
    bool free = memcmp(before, after, (size_t)state_size) == 0;
    before[player_byte] = player;
    if (facing_byte >= 0) before[facing_byte] = facing;
    return free;
}

// ---------------------------------------------------------------------------
// Hash sets of keys

typedef struct {
    uint8_t *arena;
    uint64_t arena_used, arena_capacity;
    uint64_t *key;     // arena offset << 16 | key length
    uint32_t *hash;
    uint64_t count, capacity;
    uint32_t *table;   // entry + 1, 0 when empty
    uint64_t table_capacity;
} Set;

static void SetRehash(Set *set, uint64_t capacity) {
    free(set->table);
    set->table = calloc(capacity, sizeof *set->table);
    if (!set->table) { fprintf(stderr, "out of memory\n"); exit(3); }
    set->table_capacity = capacity;
    for (uint64_t entry = 0; entry < set->count; entry++) {
        uint64_t slot = set->hash[entry] & (capacity - 1);
        while (set->table[slot]) slot = (slot + 1) & (capacity - 1);
        set->table[slot] = (uint32_t)(entry + 1);
    }
}

static void SetClear(Set *set) {
    free(set->arena); free(set->key); free(set->hash); free(set->table);
    memset(set, 0, sizeof *set);
    SetRehash(set, 1u << 16);
}

static uint64_t SetBytes(const Set *set) {
    return set->arena_used + set->count * 12 + set->table_capacity * 4;
}

static const uint8_t *SetKey(const Set *set, uint64_t entry, int *length) {
    *length = (int)(set->key[entry] & 0xffff);
    return set->arena + (set->key[entry] >> 16);
}

// Adds a key unless present. Returns the new entry, or -1 when present.
static int64_t SetAdd(Set *set, const uint8_t *key, int length) {
    uint32_t hash = Hash(key, length);
    uint64_t slot = hash & (set->table_capacity - 1);
    while (set->table[slot]) {
        uint64_t entry = set->table[slot] - 1;
        if (set->hash[entry] == hash && (int)(set->key[entry] & 0xffff) == length &&
            memcmp(set->arena + (set->key[entry] >> 16), key, (size_t)length) == 0) return -1;
        slot = (slot + 1) & (set->table_capacity - 1);
    }
    uint64_t entry = set->count;
    if (entry + 1 >= NO_PARENT) { fprintf(stderr, "entry index overflow\n"); exit(3); }
    if (entry == set->capacity) {
        set->capacity = set->capacity * 3 / 2 + 4096;
        set->key = Resize(set->key, set->capacity * sizeof *set->key);
        set->hash = Resize(set->hash, set->capacity * sizeof *set->hash);
    }
    if (set->arena_used + (uint64_t)length > set->arena_capacity) {
        set->arena_capacity = (set->arena_used + (uint64_t)length) * 3 / 2 + 65536;
        set->arena = Resize(set->arena, set->arena_capacity);
    }
    memcpy(set->arena + set->arena_used, key, (size_t)length);
    set->key[entry] = set->arena_used << 16 | (uint64_t)length;
    set->hash[entry] = hash;
    set->arena_used += (uint64_t)length;
    set->count++;
    set->table[slot] = (uint32_t)(entry + 1);
    if (set->count * 4 > set->table_capacity * 3) SetRehash(set, set->table_capacity * 2);
    return (int64_t)entry;
}

// ---------------------------------------------------------------------------
// Search nodes: every state found, with how it was reached

static Set states;             // node keys, in creation order
static Set closed;             // macro searches: keys of expanded regions
static uint32_t *node_parent;
static uint8_t *node_action;
static uint16_t *node_start;   // macro searches: walker the action started from
static uint32_t *node_depth;
static uint64_t node_capacity;

static uint64_t *heap;         // priority << 32 | node, smallest first
static uint64_t heap_count, heap_capacity;

static void ClearSearch(void) {
    SetClear(&states);
    SetClear(&closed);
    heap_count = 0;
}

static uint64_t MemoryUsed(void) {
    return SetBytes(&states) + SetBytes(&closed) + states.count * 11 + heap_count * 8;
}

// Adds a state. Returns its node, or -1 when it was already known.
static int64_t AddNode(const uint8_t *key, int length, uint32_t parent, int action, int start, uint32_t depth) {
    int64_t node = SetAdd(&states, key, length);
    if (node < 0) return -1;
    if (states.capacity > node_capacity) {
        node_capacity = states.capacity;
        node_parent = Resize(node_parent, node_capacity * sizeof *node_parent);
        node_action = Resize(node_action, node_capacity * sizeof *node_action);
        node_start = Resize(node_start, node_capacity * sizeof *node_start);
        node_depth = Resize(node_depth, node_capacity * sizeof *node_depth);
    }
    node_parent[node] = parent;
    node_action[node] = (uint8_t)action;
    node_start[node] = (uint16_t)start;
    node_depth[node] = depth;
    return node;
}

static void LoadNode(uint64_t node, uint8_t *vector) {
    int length;
    const uint8_t *key = SetKey(&states, node, &length);
    Decompress(key, length, vector);
}

static void HeapPush(uint64_t entry) {
    if (heap_count == heap_capacity) {
        heap_capacity = heap_capacity * 3 / 2 + 4096;
        heap = Resize(heap, heap_capacity * sizeof *heap);
    }
    uint64_t at = heap_count++;
    while (at > 0) {
        uint64_t parent = (at - 1) / 2;
        if (heap[parent] <= entry) break;
        heap[at] = heap[parent];
        at = parent;
    }
    heap[at] = entry;
}

static uint64_t HeapPop(void) {
    uint64_t top = heap[0], last = heap[--heap_count];
    uint64_t at = 0;
    for (;;) {
        uint64_t child = at * 2 + 1;
        if (child >= heap_count) break;
        if (child + 1 < heap_count && heap[child + 1] < heap[child]) child++;
        if (last <= heap[child]) break;
        heap[at] = heap[child];
        at = child;
    }
    if (heap_count) heap[at] = last;
    return top;
}

// A growable route string.
typedef struct { char *text; size_t length, capacity; } Route;

static void RouteAdd(Route *route, char letter) {
    if (route->length + 2 > route->capacity) {
        route->capacity = route->capacity * 2 + 256;
        route->text = Resize(route->text, route->capacity);
    }
    route->text[route->length++] = letter;
    route->text[route->length] = 0;
}

// ---------------------------------------------------------------------------
// Shovey regions

// Edges leave a region: an action other than a free walk, from a walker.
typedef struct { uint16_t walker; uint8_t action; } Edge;

static uint16_t region_queue[WALKERS];
static uint16_t region_from[WALKERS];
static uint8_t region_move[WALKERS];
static uint32_t region_mark[WALKERS];
static uint32_t region_epoch;
static int region_count;
static Edge region_edges[WALKERS * ACTIONS];
static int region_edge_count;
static uint8_t *region_vector;

// Visits every walker reachable from vector by free walks, recording how
// each was first reached and every other action. Returns true, with
// *winner set, as soon as an action wins.
static bool Region(const uint8_t *vector, Edge *winner) {
    memcpy(region_vector, vector, (size_t)state_size);
    API(Decode)(region_vector);
    region_epoch++;
    region_count = 0;
    region_edge_count = 0;
    int start = WalkerOf(vector);
    region_queue[region_count++] = (uint16_t)start;
    region_mark[start] = region_epoch;
    for (int at = 0; at < region_count; at++) {
        int walker = region_queue[at];
        SetWalker(region_vector, walker);
        API(SetWalker)(walker);
        for (int action = 0; action < ACTIONS; action++) {
            // Actions that ignore Shovey's position run from the start only.
            if (at > 0 && API(WalkerFree)(action)) continue;
            int reached = action < 4 ? API(PlainStep)(action) : -1;
            if (reached >= 0) goto walked;
            API(Reset)();
            if (!API(Act)(action)) {
                // A rejected action changes at most the facing.
                if (facing_byte < 0) continue;
                reached = API(Walker)();
            } else {
                if (API(Lost)()) continue;
                Edge edge = {(uint16_t)walker, (uint8_t)action};
                if (API(Won)()) { *winner = edge; return true; }
                Encode(next_vector);
                if (!FreeWalk(region_vector, next_vector)) {
                    region_edges[region_edge_count++] = edge;
                    continue;
                }
                reached = WalkerOf(next_vector);
            }
        walked:
            if (region_mark[reached] == region_epoch) continue;
            region_mark[reached] = region_epoch;
            region_from[reached] = (uint16_t)walker;
            region_move[reached] = (uint8_t)action;
            region_queue[region_count++] = (uint16_t)reached;
        }
    }
    return false;
}

// Appends the free walk from the last Region's start to walker.
static void WalkTo(Route *route, int walker) {
    char steps[WALKERS];
    int count = 0;
    while (walker != region_queue[0]) {
        steps[count++] = LETTERS[region_move[walker]];
        walker = region_from[walker];
    }
    while (count > 0) RouteAdd(route, steps[--count]);
}

// ---------------------------------------------------------------------------
// Searches

typedef struct {
    Stop stop;
    Route route;
    uint64_t expanded;
} Result;

static bool OverLimits(const Options *options, double deadline, Result *result) {
    if (Now() > deadline) { result->stop = STOP_TIME; return true; }
    if (MemoryUsed() > options->max_bytes) { result->stop = STOP_MEMORY; return true; }
    if (states.count >= options->max_states) { result->stop = STOP_STATES; return true; }
    return false;
}

// The route to node, then action: every action stored on the way.
static void SingleRoute(Route *route, uint64_t node, int action) {
    uint64_t length = 0;
    for (uint64_t at = node; node_parent[at] != NO_PARENT; at = node_parent[at]) length++;
    char *steps = Resize(NULL, length + 1);
    uint64_t at = length;
    for (uint64_t step = node; node_parent[step] != NO_PARENT; step = node_parent[step]) {
        steps[--at] = LETTERS[node_action[step]];
    }
    for (uint64_t index = 0; index < length; index++) RouteAdd(route, steps[index]);
    RouteAdd(route, LETTERS[action]);
    free(steps);
}

static Result BreadthFirst(const Options *options, double deadline) {
    Result result = {STOP_NONE, {NULL, 0, 0}, 0};
    ClearSearch();
    AddNode(key_buffer, 0, NO_PARENT, 0, 0, 0);
    for (uint64_t node = 0;; node++) {
        if (node >= states.count) { result.stop = STOP_EXHAUSTED; break; }
        if ((result.expanded & 1023) == 0 && OverLimits(options, deadline, &result)) break;
        result.expanded++;
        LoadNode(node, work_vector);
        API(Decode)(work_vector);
        for (int action = 0; action < ACTIONS; action++) {
            API(Reset)();
            int accepted = API(Act)(action);
            if (API(Lost)()) continue;
            if (API(Won)()) {
                result.stop = STOP_SOLVED;
                SingleRoute(&result.route, node, action);
                return result;
            }
            Encode(next_vector);
            // The macro searches trust these wrapper promises; check them on
            // every state this exact search sees.
            bool turned_only = FreeWalk(work_vector, next_vector) &&
                next_vector[player_byte] == work_vector[player_byte];
            if (API(Walker)() != WalkerOf(next_vector) || (!accepted && !turned_only)) {
                fprintf(stderr, "the %s wrapper broke its walker contract\n", EDITION);
                exit(3);
            }
            AddNode(key_buffer, Compress(next_vector, key_buffer), (uint32_t)node, action, 0, node_depth[node] + 1);
        }
    }
    return result;
}

// Rebuilds a macro route: each step walks freely to its start walker in the
// parent state, then takes its action; the final step is the winning edge.
static void MacroRoute(Route *route, uint64_t node, Edge winner) {
    uint64_t length = 1;
    for (uint64_t at = node; node_parent[at] != NO_PARENT; at = node_parent[at]) length++;
    uint64_t *path = Resize(NULL, length * sizeof *path);
    uint64_t at = length;
    for (uint64_t step = node;; step = node_parent[step]) {
        path[--at] = step;
        if (node_parent[step] == NO_PARENT) break;
    }
    Edge unused;
    for (uint64_t index = 0; index < length; index++) {
        LoadNode(path[index], work_vector);
        Region(work_vector, &unused);
        bool last = index + 1 == length;
        int start = last ? winner.walker : node_start[path[index + 1]];
        int action = last ? winner.action : node_action[path[index + 1]];
        WalkTo(route, start);
        RouteAdd(route, LETTERS[action]);
    }
    free(path);
}

// Lower is better: the estimate, weighted against the macro depth.
static uint64_t Priority(uint32_t depth, int weight) {
    uint64_t priority = (uint64_t)API(Estimate)() * (uint64_t)weight + depth;
    return priority > 0xffffffffull ? 0xffffffffull : priority;
}

static int ComparePriority(const void *left, const void *right) {
    uint64_t a = *(const uint64_t *)left, b = *(const uint64_t *)right;
    return (a > b) - (a < b);
}

// Best-first (greedy) when ordered, else breadth-first, over macro actions.
static Result MacroSearch(const Options *options, double deadline, bool ordered, bool focused) {
    Result result = {STOP_NONE, {NULL, 0, 0}, 0};
    ClearSearch();
    AddNode(key_buffer, 0, NO_PARENT, 0, 0, 0);
    if (ordered) {
        API(Decode)(root_vector);
        HeapPush(Priority(0, options->weight) << 32);
    }
    uint64_t head = 0;
    for (;;) {
        uint64_t node;
        if (ordered) {
            if (heap_count == 0) { result.stop = STOP_EXHAUSTED; break; }
            node = HeapPop() & 0xffffffffull;
        } else {
            if (head >= states.count) { result.stop = STOP_EXHAUSTED; break; }
            node = head++;
        }
        if ((result.expanded & 15) == 0 && OverLimits(options, deadline, &result)) break;
        LoadNode(node, work_vector);
        Edge winner;
        if (Region(work_vector, &winner)) {
            result.stop = STOP_SOLVED;
            MacroRoute(&result.route, node, winner);
            return result;
        }
        // Skip regions already expanded from another of their walkers.
        int smallest = region_queue[0];
        for (int at = 1; at < region_count; at++) {
            if (region_queue[at] < smallest) smallest = region_queue[at];
        }
        SetWalker(work_vector, smallest);
        if (SetAdd(&closed, key_buffer, Compress(work_vector, key_buffer)) < 0) continue;
        SetWalker(work_vector, region_queue[0]);
        result.expanded++;
        API(Decode)(work_vector);
#if defined(SHOVEY_CLASSIC)
        if (ordered) API(Focus)();
#endif
        for (int index = 0; index < region_edge_count; index++) {
            Edge edge = region_edges[index];
            API(SetWalker)(edge.walker);
            API(Reset)();
            uint32_t cost = 1;
#if defined(SHOVEY_CLASSIC)
            if (ordered) cost = (uint32_t)API(ActionCost)(edge.action);
#endif
            // Extra effort goes to crate pushes off the objective routes;
            // they stay available for necessary detours and staging moves.
            uint32_t depth = node_depth[node] + cost;
            API(Act)(edge.action);
            // A state the wrapper proves unwinnable is never stored.
            if (API(Dead)()) continue;
            Encode(next_vector);
            int64_t added = AddNode(key_buffer, Compress(next_vector, key_buffer), (uint32_t)node,
                edge.action, edge.walker, depth);
            if (added >= 0 && ordered) {
                HeapPush(Priority(depth, options->weight) << 32 | (uint64_t)added);
                static int best = 1 << 30;
                if (getenv("TRACE") && API(Estimate)() < best) {
                    best = API(Estimate)();
                    fprintf(stderr, "best %d remaining %d depth %u vector ", best, API(Remaining)(), depth);
                    for (int i = 0; i < state_size; i++) fprintf(stderr, "%02x", next_vector[i]);
                    fprintf(stderr, "\n");
                }
            }
        }
        // Keep a small set of promising continuations in the first attempt
        // instead of filling the frontier with spare-crate rearrangements.
        // The caller retries without this bound before leaving the phase.
        if (focused && heap_count > 512) {
            qsort(heap, (size_t)heap_count, sizeof *heap, ComparePriority);
            heap_count = 128; /* A sorted prefix is also a valid min-heap. */
        }
    }
    return result;
}

// One goal at a time, as a person plays: a best-first macro search from the
// current state collects up to CHAIN_WAYS different states with one more goal
// finished (a ball sunk, a plate held, an apple eaten), and the chain goes on
// from the most promising, falling back to the next way when one leads into a
// dead end. Each search keeps states as differences from its own root.
// Running out of ways proves nothing; every route it finds is the engine's
// own moves.
#define CHAIN_WAYS 4

typedef struct { uint8_t *vector; Route route; bool won; } Way;

static int ChainWays(const Options *options, double deadline, int goal, Way *ways) {
    int found = 0;
    ClearSearch();
    AddNode(key_buffer, 0, NO_PARENT, 0, 0, 0);
    API(Decode)(root_vector);
    HeapPush(Priority(0, options->weight) << 32);
    uint64_t goal_nodes[CHAIN_WAYS];
    Edge goal_edges[CHAIN_WAYS];
    Result limits = {STOP_NONE, {NULL, 0, 0}, 0};
    while (found < CHAIN_WAYS && heap_count > 0) {
        if ((limits.expanded & 15) == 0 && OverLimits(options, deadline, &limits)) break;
        uint64_t node = HeapPop() & 0xffffffffull;
        LoadNode(node, work_vector);
        Edge winner;
        if (Region(work_vector, &winner)) {
            ways[found].vector = NULL;
            ways[found].won = true;
            goal_nodes[found] = node;
            goal_edges[found++] = winner;
            continue;
        }
        int smallest = region_queue[0];
        for (int at = 1; at < region_count; at++) {
            if (region_queue[at] < smallest) smallest = region_queue[at];
        }
        SetWalker(work_vector, smallest);
        if (SetAdd(&closed, key_buffer, Compress(work_vector, key_buffer)) < 0) continue;
        SetWalker(work_vector, region_queue[0]);
        limits.expanded++;
        API(Decode)(work_vector);
#if defined(SHOVEY_CLASSIC)
        API(Focus)();
#endif
        for (int index = 0; index < region_edge_count && found < CHAIN_WAYS; index++) {
            Edge edge = region_edges[index];
            API(SetWalker)(edge.walker);
            API(Reset)();
            uint32_t cost = 1;
#if defined(SHOVEY_CLASSIC)
            cost = (uint32_t)API(ActionCost)(edge.action);
#endif
            uint32_t depth = node_depth[node] + cost;
            API(Act)(edge.action);
            if (API(Dead)()) continue;
            Encode(next_vector);
            if (API(Progress)() < goal) {
                ways[found].vector = Resize(NULL, (size_t)state_size);
                memcpy(ways[found].vector, next_vector, (size_t)state_size);
                ways[found].won = false;
                goal_nodes[found] = node;
                goal_edges[found++] = edge;
                continue;
            }
            int64_t added = AddNode(key_buffer, Compress(next_vector, key_buffer), (uint32_t)node,
                edge.action, edge.walker, depth);
            if (added >= 0) HeapPush(Priority(depth, options->weight) << 32 | (uint64_t)added);
        }
    }
    // Routes are rebuilt only now: rebuilding replays regions on the way.
    for (int at = 0; at < found; at++) {
        ways[at].route = (Route){NULL, 0, 0};
        MacroRoute(&ways[at].route, goal_nodes[at], goal_edges[at]);
    }
    return found;
}

static bool Chain(const Options *options, double deadline, Route *route, int depth) {
    if (depth > 64 || Now() >= deadline) return false;
    API(Decode)(root_vector);
    int goal = API(Progress)();
    Way ways[CHAIN_WAYS];
    int count = ChainWays(options, deadline, goal > 0 ? goal : 0, ways);
    bool solved = false;
    uint8_t *here = Resize(NULL, (size_t)state_size);
    memcpy(here, root_vector, (size_t)state_size);
    for (int at = 0; at < count && !solved; at++) {
        size_t mark = route->length;
        for (size_t step = 0; step < ways[at].route.length; step++) RouteAdd(route, ways[at].route.text[step]);
        if (ways[at].won) {
            solved = true;
        } else {
            memcpy(root_vector, ways[at].vector, (size_t)state_size);
            solved = Chain(options, deadline, route, depth + 1);
            memcpy(root_vector, here, (size_t)state_size);
        }
        if (!solved) {
            route->length = mark;
            if (route->text) route->text[mark] = 0;
        }
    }
    for (int at = 0; at < count; at++) {
        free(ways[at].vector);
        free(ways[at].route.text);
    }
    free(here);
    return solved;
}

static Result ChainSearch(const Options *options, double deadline) {
    Result result = {STOP_NONE, {NULL, 0, 0}, 0};
    uint8_t *start = Resize(NULL, (size_t)state_size);
    memcpy(start, root_vector, (size_t)state_size);
    result.stop = Chain(options, deadline, &result.route, 0) ? STOP_SOLVED :
        Now() >= deadline ? STOP_TIME : STOP_EXHAUSTED;
    memcpy(root_vector, start, (size_t)state_size);
    free(start);
    return result;
}

// ---------------------------------------------------------------------------
// Commands

static int Load(const char *hex, int level) {
    if (!API(Load)((uint8_t *)hex, level)) {
        fprintf(stderr, "the %s engine rejected the board\n", EDITION);
        return 0;
    }
    state_size = API(StateSize)();
    player_byte = API(PlayerByte)();
    facing_byte = API(FacingByte)();
    facings = API(Facings)();
    if (facings < 1 || facings > WALKERS / CELLS || (facings > 1) != (facing_byte >= 0)) {
        fprintf(stderr, "the %s wrapper reports an unsupported facing layout\n", EDITION);
        return 0;
    }
    root_vector = Resize(NULL, (size_t)state_size);
    work_vector = Resize(NULL, (size_t)state_size);
    next_vector = Resize(NULL, (size_t)state_size);
    region_vector = Resize(NULL, (size_t)state_size);
    key_buffer = Resize(NULL, (size_t)state_size * 2 + 16);
    Encode(root_vector);
    return 1;
}

static int Solve(const char *hex, const Options *options) {
    if (!Load(hex, options->level)) return 2;
    const char *prefix = options->prefix ? options->prefix : "";
    size_t prefix_length = 0;
    for (size_t step = 0; prefix[step]; step++) {
        const char *action = strchr(LETTERS, prefix[step]);
        if (!action) { fprintf(stderr, "invalid prefix action\n"); return 2; }
        if (API(Won)()) continue;
        API(Act)((int32_t)(action - LETTERS));
        if (API(Lost)() || (!API(Won)() && API(Dead)())) {
            if (!options->repair) { fprintf(stderr, "prefix fails at step %zu\n", step + 1); return 1; }
            API(Decode)(root_vector);
            fprintf(stderr, "repair checkpoint %zu/%zu\n", prefix_length, strlen(prefix));
            break;
        }
        prefix_length = step + 1;
        Encode(root_vector);
    }
    Encode(root_vector);
    double start = Now();
    const char *method = "none";
    char phases[256] = "";
    uint64_t states_seen = 0, expanded = 0;
    Result result = {API(Won)() ? STOP_SOLVED : STOP_NONE, {NULL, 0, 0}, 0};
    // Combine exact short searches with goal-focused planning. Spare crates
    // otherwise consume the whole budget before the useful pushes are tried.
    struct { const char *name; double share; } plan[4] = {
        {"bfs", options->bfs_share * 0.75}, {"chain", 0.25},
        {"greedy", options->greedy_share * 0.75},
        {"macro-bfs", (1.0 - options->bfs_share - options->greedy_share) * 0.75}};
    double deadline = start;
    for (int index = 0; index < 4 && result.stop != STOP_SOLVED; index++) {
        if (options->only && strcmp(options->only, plan[index].name) != 0) continue;
        deadline += options->seconds * (options->only ? 1.0 : plan[index].share);
        if (index == 3 && !options->only) deadline = start + options->seconds;
        if (deadline <= Now()) continue;
        method = plan[index].name;
        if (index == 0) result = BreadthFirst(options, deadline);
        else if (strcmp(method, "chain") == 0) result = ChainSearch(options, deadline);
        else {
#if defined(SHOVEY_CLASSIC)
            if (strcmp(method, "greedy") == 0) {
                double focus_deadline = Now() + (deadline - Now()) * 0.5;
                result = MacroSearch(options, focus_deadline, true, true);
                if (result.stop != STOP_SOLVED && Now() < deadline) {
                    states_seen += states.count;
                    expanded += result.expanded;
                    result = MacroSearch(options, deadline, true, false);
                }
            } else
#endif
            result = MacroSearch(options, deadline, strcmp(method, "greedy") == 0, false);
        }
        states_seen += states.count;
        expanded += result.expanded;
        size_t used = strlen(phases);
        snprintf(phases + used, sizeof phases - used, "%s%s:%s", used ? "," : "", method, StopName(result.stop));
        // An exhausted breadth-first search has seen every reachable state.
        if (index == 0 && result.stop == STOP_EXHAUSTED) break;
    }
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    double seconds = Now() - start;
    bool solved = result.stop == STOP_SOLVED;
    printf("%.*s%s\n", solved ? (int)prefix_length : 0, prefix,
        solved ? (result.route.text ? result.route.text : "") : "unsolved");
    fprintf(stderr, "stats {\"edition\":\"%s\",\"solved\":%s,\"method\":\"%s\",\"length\":%zu,"
        "\"states\":%llu,\"expanded\":%llu,\"seconds\":%.3f,\"phases\":\"%s\",\"stop\":\"%s\","
        "\"max_rss_mb\":%.1f}\n",
        EDITION, solved ? "true" : "false", method, solved ? prefix_length + result.route.length : (size_t)0,
        (unsigned long long)states_seen, (unsigned long long)expanded, seconds, phases,
        StopName(result.stop), (double)usage.ru_maxrss / 1024.0);
    return solved ? 0 : 1;
}

static int Verify(const char *hex, const char *route, int level) {
    if (!Load(hex, level)) return 2;
    for (size_t step = 0; route[step]; step++) {
        if (!strchr(LETTERS, route[step])) {
            fprintf(stderr, "step %zu: '%c' is not a %s action\n", step + 1, route[step], EDITION);
            return 1;
        }
    }
    uint8_t *debug_vector = Resize(NULL, (size_t)state_size);
    int debug_remaining = API(Remaining)();
    for (size_t step = 0; route[step]; step++) {
        const char *letter = strchr(LETTERS, route[step]);
        if (!letter) {
            fprintf(stderr, "step %zu: '%c' is not a %s action\n", step + 1, route[step], EDITION);
            return 1;
        }
        if (API(Won)()) {
            break; /* Gameplay and the editor ignore input after a win. */
        }
        API(Act)((int32_t)(letter - LETTERS));
        if (API(Lost)()) {
            fprintf(stderr, "step %zu: Shovey lost\n", step + 1);
            return 1;
        }
        if (API(Remaining)() != debug_remaining) {
            debug_remaining = API(Remaining)();
            if (!API(Encode)(debug_vector)) return 3;
            fprintf(stderr, "goal step %zu remaining %d objects", step + 1, debug_remaining);
            for (int at = 0; at < CELLS; at++) {
                int object = debug_vector[CELLS + at];
                if (object == 9 || (object >= 1 && object <= 3)) fprintf(stderr, " %d:%d", at, object);
            }
            fprintf(stderr, " plates");
            for (int y = 2; y <= 10; y++) fprintf(stderr, " %d", debug_vector[CELLS + y * 20 + 18] == 9);
            fprintf(stderr, "\n");
        }
    }
    if (!API(Won)()) {
        fprintf(stderr, "route ends without winning (%d remaining)\n", API(Remaining)());
        return 1;
    }
    return 0;
}

static void Usage(void) {
    fprintf(stderr,
        "usage: shovey-solve-%s solve [--level N] [--seconds S] [--max-states N] [--max-mb N] [--prefix ROUTE]\n"
        "           [--bfs-share F] [--greedy-share F] [--weight W] [--only bfs|greedy|macro-bfs|chain] BOARDHEX\n"
        "       shovey-solve-%s verify [--level N] BOARDHEX ROUTE\n"
        "Route letters: %s\n", EDITION, EDITION, LETTERS);
}

int main(int argc, char **argv) {
    Options options = {.level = 1, .max_states = 30000000, .max_bytes = 1000ull << 20,
        .seconds = 120.0, .bfs_share = 0.15, .greedy_share = 0.5, .weight = 4, .only = NULL};
    if (argc < 2) { Usage(); return 2; }
    const char *mode = argv[1];
    const char *positional[2] = {NULL, NULL};
    int count = 0;
    for (int at = 2; at < argc; at++) {
        const char *arg = argv[at];
        if (arg[0] == '-' && arg[1] == '-') {
            if (at + 1 >= argc) { Usage(); return 2; }
            const char *value = argv[++at];
            if (strcmp(arg, "--level") == 0) options.level = atoi(value);
            else if (strcmp(arg, "--max-states") == 0) options.max_states = strtoull(value, NULL, 10);
            else if (strcmp(arg, "--max-mb") == 0) options.max_bytes = strtoull(value, NULL, 10) << 20;
            else if (strcmp(arg, "--seconds") == 0) options.seconds = atof(value);
            else if (strcmp(arg, "--bfs-share") == 0) options.bfs_share = atof(value);
            else if (strcmp(arg, "--greedy-share") == 0) options.greedy_share = atof(value);
            else if (strcmp(arg, "--weight") == 0) options.weight = atoi(value);
            else if (strcmp(arg, "--only") == 0) options.only = value;
            else if (strcmp(arg, "--prefix") == 0) options.prefix = value;
            else if (strcmp(arg, "--repair") == 0) { options.prefix = value; options.repair = true; }
            else { Usage(); return 2; }
            continue;
        }
        if (count == 2) { Usage(); return 2; }
        positional[count++] = arg;
    }
    if (strcmp(mode, "solve") == 0 && count == 1) return Solve(positional[0], &options);
    if (strcmp(mode, "verify") == 0 && count == 2) return Verify(positional[0], positional[1], options.level);
    Usage();
    return 2;
}
