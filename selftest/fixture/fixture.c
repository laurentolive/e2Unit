/* Functions used by the e2Unit self tests (some are deliberately wrong). */
#include <stdbool.h>
#include <stdint.h>

int32_t fx_add(int32_t a, int32_t b);
int16_t fx_clamp_bug(int16_t x);
uint32_t fx_count(void);
float fx_scale(float x, float k);
bool fx_is_neg(int8_t x);
uint8_t fx_inc_u8(uint8_t x);
uint32_t fx_hang(uint32_t x);
int32_t fx_load(uint32_t addr);

int32_t fx_add(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

/* specified as clamp to [-1000, 1000]: wrong above 1000 */
int16_t fx_clamp_bug(int16_t x)
{
    if (x < -1000) {
        return -1000;
    }
    return (x > 1000) ? 1001 : x;
}

/* static state: must restart from 1 after a runner reset */
static uint32_t counter;
uint32_t fx_count(void)
{
    return ++counter;
}

float fx_scale(float x, float k)
{
    return x * k;
}

bool fx_is_neg(int8_t x)
{
    return x < 0;
}

uint8_t fx_inc_u8(uint8_t x)
{
    return (uint8_t)(x + 1u);
}

/* never returns when x != 0 */
uint32_t fx_hang(uint32_t x)
{
    volatile uint32_t v = x;
    while (v != 0u) {
    }
    return v;
}

/* reads any address: faults on unmapped memory */
int32_t fx_load(uint32_t addr)
{
    return *(volatile const int32_t *)(uintptr_t)addr;
}
