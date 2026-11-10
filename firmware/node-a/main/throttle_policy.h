#ifndef THROTTLE_POLICY_H
#define THROTTLE_POLICY_H

#include <stdbool.h>
#include <stdint.h>

#define THROTTLE_BASE_PERIOD_US 10000U

typedef enum {
    THROTTLE_NORMAL = 0,
    THROTTLE_ALERT,
    THROTTLE_CRITICAL
} throttle_mode_t;

static inline throttle_mode_t throttle_mode_from_tec(uint16_t tec)
{
    if (tec >= 128) {
        return THROTTLE_CRITICAL;
    }
    if (tec >= 96) {
        return THROTTLE_ALERT;
    }
    return THROTTLE_NORMAL;
}

static inline uint32_t throttle_period_us(throttle_mode_t mode,
                                          bool enabled)
{
    if (!enabled) {
        return THROTTLE_BASE_PERIOD_US;
    }
    switch (mode) {
        case THROTTLE_NORMAL:   return THROTTLE_BASE_PERIOD_US;
        case THROTTLE_ALERT:    return 2U * THROTTLE_BASE_PERIOD_US;
        case THROTTLE_CRITICAL: return 4U * THROTTLE_BASE_PERIOD_US;
        default:                return 4U * THROTTLE_BASE_PERIOD_US;
    }
}

static inline uint32_t throttle_update_stride(throttle_mode_t mode,
                                               bool enabled)
{
    return throttle_period_us(mode, enabled) / THROTTLE_BASE_PERIOD_US;
}

static inline bool throttle_can_submit_update(uint32_t sequence,
                                               uint32_t last_accepted_sequence,
                                               bool has_last_accepted,
                                               bool tx_pending,
                                               bool bus_off,
                                               throttle_mode_t mode,
                                               bool enabled)
{
    if (tx_pending || bus_off) {
        return false;
    }
    if (!has_last_accepted) {
        return true;
    }
    return (uint32_t)(sequence - last_accepted_sequence) >=
           throttle_update_stride(mode, enabled);
}

#endif
