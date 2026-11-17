/* SPDX-License-Identifier: MIT */
#ifndef FX_MODEL_H
#define FX_MODEL_H
#include "fx_arena.h"
typedef struct { int value; unsigned runs; } fx_model;
enum fx_result { FX_OK, FX_NO_MEMORY, FX_CANCELLED };
int fx_model_apply(fx_model *model, fx_arena *scratch, unsigned cancel_after);
unsigned fx_contract_test(void);
#endif
