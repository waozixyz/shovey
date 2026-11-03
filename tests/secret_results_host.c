/* A denying host proves the secret branches never draw or access storage. */
#include "ziran_host.h"
#include <stdio.h>
#include <stdlib.h>

static int unexpected(void *context, const char *module, const char *function,
                      const VmHostValue *args, int count, VmHostValue *result) {
    (void)args; (void)count; (void)result;
    (*(int *)context)++;
    fprintf(stderr, "Unexpected secret-result host call: %s:%s\n", module, function);
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 1;
    Bundle *bundle = BundleOpen(argv[1]);
    if (!bundle) return 2;
    size_t count = BundleCapabilityCount(bundle);
    HostBinding *bindings = calloc(count ? count : 1, sizeof(*bindings));
    if (!bindings) { BundleClose(bundle); return 3; }
    int calls = 0, has_result = 0;
    long long result = -1;
    for (size_t i = 0; i < count; i++)
        bindings[i] = (HostBinding){BundleCapabilityModule(bundle, i),
            BundleCapabilityFunction(bundle, i), unexpected, &calls};
    int ok = BundleRun(bundle, bindings, count, &result, &has_result);
    free(bindings);
    BundleClose(bundle);
    if (!ok || !has_result || result || calls) {
        fprintf(stderr, "Secret results local test failed: result=%lld, host calls=%d\n",
                (long long)result, calls);
        return 4;
    }
    return 0;
}
