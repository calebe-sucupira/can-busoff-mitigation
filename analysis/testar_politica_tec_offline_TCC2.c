#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "throttle_policy.h"

typedef struct {
    const char *label;
    uint16_t tec;
    bool enabled;
    bool bus_off;
    bool tx_pending;
    unsigned expected;
} scenario_t;

static unsigned count_accepted(const scenario_t *scenario)
{
    bool has_last = false;
    uint32_t last = 0;
    unsigned accepted = 0;
    throttle_mode_t mode = throttle_mode_from_tec(scenario->tec);

    for (uint32_t sequence = 0; sequence < 1000; ++sequence) {
        bool allowed = throttle_can_submit_update(
            sequence, last, has_last,
            scenario->tx_pending, scenario->bus_off,
            mode, scenario->enabled
        );
        if (allowed) {
            last = sequence;
            has_last = true;
            ++accepted;
        }
    }
    return accepted;
}

int main(void)
{
    const scenario_t scenarios[] = {
        {"Referencia TEC=95",    95, false, false, false, 1000},
        {"Adaptativo TEC=95",     95, true,  false, false, 1000},
        {"Adaptativo TEC=96",     96, true,  false, false,  500},
        {"Adaptativo TEC=127",   127, true,  false, false,  500},
        {"Adaptativo TEC=128",   128, true,  false, false,  250},
        {"Adaptativo TEC=255",   255, true,  false, false,  250},
        {"Referencia TEC=128",   128, false, false, false, 1000},
        {"Referencia BUS_OFF",   256, false, true,  false,    0},
        {"Adaptativo BUS_OFF",   256, true,  true,  false,    0},
        {"Adaptativo TX pendente", 96, true, false, true,     0},
    };

    int failures = 0;
    const unsigned count = sizeof scenarios / sizeof scenarios[0];
    printf("Testes com 1.000 atualizacoes sintéticas de 10 ms (10 s)\n");
    printf("Apenas decisao de submissao; nenhum controlador CAN e acessado.\n\n");
    for (unsigned i = 0; i < count; ++i) {
        unsigned actual = count_accepted(&scenarios[i]);
        bool pass = actual == scenarios[i].expected;
        printf("%-25s esperado=%4u observado=%4u %s\n",
               scenarios[i].label, scenarios[i].expected, actual,
               pass ? "OK" : "FALHOU");
        if (!pass) {
            ++failures;
        }
    }
    return failures ? 1 : 0;
}
