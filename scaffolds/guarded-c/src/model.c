/* SPDX-License-Identifier: MIT */
#include "model.h"
#include <string.h>
int fx_model_apply(fx_model *model, fx_arena *scratch, unsigned cancel_after)
{
    size_t mark = scratch->used;
    int status = FX_NO_MEMORY;
    unsigned char *values = fx_arena_take(scratch, 16 * sizeof(int), _Alignof(int));
    unsigned char *sum_bytes = values ? fx_arena_take(scratch, sizeof(int), _Alignof(int)) : NULL;
    if (!sum_bytes) goto cleanup;
    int sum = 0;
    for (unsigned i = 0; i < 16; i++) {
        if (cancel_after && i >= cancel_after) {
            status = FX_CANCELLED;
            goto cleanup;
        }
        int value = (int)i;
        /* Byte storage + memcpy avoids aliasing typed objects over a char array. */
        memcpy(values + i * sizeof(int), &value, sizeof value);
        memcpy(&value, values + i * sizeof(int), sizeof value);
        sum += value;
    }
    /* Commit only after success; persistent state owns no scratch pointers. */
    memcpy(sum_bytes, &sum, sizeof sum);
    memcpy(&model->value, sum_bytes, sizeof model->value);
    model->runs++;
    status = FX_OK;
cleanup:
    fx_arena_rewind(scratch, mark);
    return status;
}
