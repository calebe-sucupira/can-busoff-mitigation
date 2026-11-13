#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_twai.h"
#include "esp_twai_onchip.h"
#include "throttle_policy.h"

#define TWAI_TX_GPIO           21
#define TWAI_RX_GPIO           22
#define CAN_BITRATE            125000
#define CAN_ID_UPDATE          0x100
#define UPDATE_PERIOD_MS       10
#define MONITOR_PERIOD_MS      1
#define HEARTBEAT_MS           100
#define PENDING_WARN_MS        200
#define RECOVER_RETRY_MS       100
#define APP_CORE               1
#define FW_BUILD_TAG           "node-a-throttling-v1.3-busoff-trace"
#define TX_WAKE_UPDATE         (1UL << 0)
#define TX_WAKE_DONE           (1UL << 1)
#define TX_WAKE_MODE           (1UL << 2)

#ifndef ENABLE_THROTTLING
#define ENABLE_THROTTLING       0
#endif

#if configTICK_RATE_HZ < 1000
#error "CONFIG_FREERTOS_HZ precisa ser >= 1000 para monitoramento de 1 ms"
#endif

#if UPDATE_PERIOD_MS * 1000U != THROTTLE_BASE_PERIOD_US
#error "Periodo do produtor e periodo-base do throttling inconsistentes"
#endif

typedef struct {
    uint32_t sequence;
    uint32_t generated_ms;
    uint64_t generated_us;
} update_t;

typedef enum {
    EVENT_TX_DONE,
    EVENT_TX_REJECTED,
    EVENT_STATE_CHANGE,
    EVENT_ERROR,
    EVENT_RECOVERY,
    EVENT_PENDING_WARNING,
    EVENT_SAMPLE
} event_type_t;

typedef struct {
    event_type_t type;
    uint64_t timestamp_us;
    union {
        struct {
            uint32_t sequence;
            uint64_t generated_us;
            uint64_t submitted_us;
            uint32_t skipped_before;
            bool success;
            esp_err_t result;
        } tx;
        struct {
            twai_error_state_t old_state;
            twai_error_state_t new_state;
        } state;
        struct {
            uint32_t flags;
        } error;
        struct {
            esp_err_t result;
        } recovery;
        struct {
            uint32_t tec;
            uint32_t rec;
            uint32_t tec_peak;
            uint32_t rec_peak;
            uint32_t bus_errors;
            uint32_t produced;
            uint32_t submitted;
            uint32_t tx_ok;
            uint32_t tx_failed;
            uint32_t rejected;
            uint32_t skipped_before;
            uint32_t lost_events;
            uint32_t update_queue_len;
            bool tx_pending;
            twai_error_state_t state;
            throttle_mode_t mode;
        } sample;
    };
} node_event_t;

static twai_node_handle_t twai_node;
static QueueHandle_t event_queue;
static QueueHandle_t update_queue;
static TaskHandle_t transmitter_task_handle;

static uint8_t inflight_payload[8];
static twai_frame_t inflight_frame;
static uint64_t inflight_generated_us;
static uint64_t inflight_submitted_us;
static uint32_t inflight_sequence;

static atomic_bool tx_pending = ATOMIC_VAR_INIT(false);
static atomic_bool controller_bus_off = ATOMIC_VAR_INIT(false);
static atomic_int current_mode = ATOMIC_VAR_INIT(THROTTLE_NORMAL);
static atomic_uint produced_count = ATOMIC_VAR_INIT(0);
static atomic_uint submitted_count = ATOMIC_VAR_INIT(0);
static atomic_uint tx_success_count = ATOMIC_VAR_INIT(0);
static atomic_uint tx_failed_count = ATOMIC_VAR_INIT(0);
static atomic_uint rejected_count = ATOMIC_VAR_INIT(0);
static atomic_uint skipped_count = ATOMIC_VAR_INIT(0);
static atomic_uint event_lost_count = ATOMIC_VAR_INIT(0);

static const char *can_state_name(twai_error_state_t state)
{
    switch (state) {
        case TWAI_ERROR_ACTIVE: return "ACTIVE";
        case TWAI_ERROR_WARNING: return "WARNING";
        case TWAI_ERROR_PASSIVE: return "PASSIVE";
        case TWAI_ERROR_BUS_OFF: return "BUS_OFF";
        default: return "UNKNOWN";
    }
}

static const char *mode_name(throttle_mode_t mode)
{
    switch (mode) {
        case THROTTLE_NORMAL: return "NORMAL";
        case THROTTLE_ALERT: return "ALERT";
        case THROTTLE_CRITICAL: return "CRITICAL";
        default: return "UNKNOWN";
    }
}

static void send_event_from_task(const node_event_t *event)
{
    if (xQueueSend(event_queue, event, 0) != pdTRUE) {
        atomic_fetch_add(&event_lost_count, 1);
    }
}

static void send_event_from_isr(const node_event_t *event, BaseType_t *woken)
{
    if (xQueueSendFromISR(event_queue, event, woken) != pdTRUE) {
        atomic_fetch_add(&event_lost_count, 1);
    }
}

static bool tx_done_callback(twai_node_handle_t handle,
                             const twai_tx_done_event_data_t *edata,
                             void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_TX_DONE,
        .timestamp_us = (uint64_t)esp_timer_get_time(),
    };

    event.tx.sequence = inflight_sequence;
    event.tx.generated_us = inflight_generated_us;
    event.tx.submitted_us = inflight_submitted_us;
    event.tx.success = edata->is_tx_success;

    if (edata->is_tx_success) {
        atomic_fetch_add(&tx_success_count, 1);
    } else {
        atomic_fetch_add(&tx_failed_count, 1);
    }

    BaseType_t woken = pdFALSE;
    send_event_from_isr(&event, &woken);
    atomic_store(&tx_pending, false);
    if (transmitter_task_handle != NULL) {
        xTaskNotifyFromISR(transmitter_task_handle, TX_WAKE_DONE, eSetBits, &woken);
    }
    return woken == pdTRUE;
}

static bool state_change_callback(twai_node_handle_t handle,
                                  const twai_state_change_event_data_t *edata,
                                  void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_STATE_CHANGE,
        .timestamp_us = (uint64_t)esp_timer_get_time(),
    };
    event.state.old_state = edata->old_sta;
    event.state.new_state = edata->new_sta;
    if (edata->new_sta == TWAI_ERROR_BUS_OFF) {
        atomic_store(&controller_bus_off, true);
    }
    BaseType_t woken = pdFALSE;
    send_event_from_isr(&event, &woken);
    return woken == pdTRUE;
}

static bool error_callback(twai_node_handle_t handle,
                           const twai_error_event_data_t *edata,
                           void *user_ctx)
{
    node_event_t event = {
        .type = EVENT_ERROR,
        .timestamp_us = (uint64_t)esp_timer_get_time(),
    };
    event.error.flags = edata->err_flags.val;
    BaseType_t woken = pdFALSE;
    send_event_from_isr(&event, &woken);
    return woken == pdTRUE;
}

static void producer_task(void *arg)
{
    TickType_t last_wake = xTaskGetTickCount();
    uint32_t sequence = 0;

    for (;;) {
        uint64_t now_us = (uint64_t)esp_timer_get_time();
        update_t update = {
            .sequence = sequence++,
            .generated_ms = (uint32_t)(now_us / 1000ULL),
            .generated_us = now_us,
        };
        xQueueOverwrite(update_queue, &update);
        atomic_fetch_add(&produced_count, 1);
        xTaskNotify(transmitter_task_handle, TX_WAKE_UPDATE, eSetBits);
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(UPDATE_PERIOD_MS));
    }
}

static void transmitter_task(void *arg)
{
    uint64_t last_pending_warning_us = 0;
    bool has_last_accepted_sequence = false;
    uint32_t last_accepted_sequence = 0;

    for (;;) {
        uint32_t notifications = 0;
        xTaskNotifyWait(0, UINT32_MAX, &notifications, pdMS_TO_TICKS(100));

        uint64_t now_us = (uint64_t)esp_timer_get_time();
        bool pending = atomic_load(&tx_pending);
        if (pending &&
            now_us - inflight_submitted_us >= PENDING_WARN_MS * 1000ULL &&
            now_us - last_pending_warning_us >= PENDING_WARN_MS * 1000ULL) {
            node_event_t warning = {
                .type = EVENT_PENDING_WARNING,
                .timestamp_us = now_us,
            };
            warning.tx.sequence = inflight_sequence;
            send_event_from_task(&warning);
            last_pending_warning_us = now_us;
        }

        // Somente novas producoes abrem oportunidades de transmissao.
        if ((notifications & TX_WAKE_UPDATE) == 0) {
            continue;
        }

        update_t update;
        if (xQueuePeek(update_queue, &update, 0) != pdTRUE) {
            continue;
        }

        throttle_mode_t mode = (throttle_mode_t)atomic_load(&current_mode);
        bool bus_off = atomic_load(&controller_bus_off);
        if (!throttle_can_submit_update(update.sequence, last_accepted_sequence,
                                        has_last_accepted_sequence, pending,
                                        bus_off, mode, ENABLE_THROTTLING != 0)) {
            continue;
        }
        if (xQueueReceive(update_queue, &update, 0) != pdTRUE) {
            continue;
        }

        memcpy(&inflight_payload[0], &update.sequence, sizeof(update.sequence));
        memcpy(&inflight_payload[4], &update.generated_ms,
               sizeof(update.generated_ms));

        inflight_sequence = update.sequence;
        inflight_generated_us = update.generated_us;
        inflight_submitted_us = (uint64_t)esp_timer_get_time();

        atomic_store(&tx_pending, true);
        esp_err_t result = twai_node_transmit(twai_node, &inflight_frame, 0);
        node_event_t event = {
            .type = EVENT_TX_REJECTED,
            .timestamp_us = inflight_submitted_us,
        };
        event.tx.sequence = update.sequence;
        event.tx.generated_us = update.generated_us;
        event.tx.submitted_us = inflight_submitted_us;
        event.tx.result = result;

        if (result == ESP_OK) {
            uint32_t gap = has_last_accepted_sequence
                ? update.sequence - last_accepted_sequence - 1U
                : update.sequence;
            event.tx.skipped_before = gap;
            atomic_fetch_add(&skipped_count, gap);
            last_accepted_sequence = update.sequence;
            has_last_accepted_sequence = true;
            atomic_fetch_add(&submitted_count, 1);
        } else {
            atomic_store(&tx_pending, false);
            atomic_fetch_add(&rejected_count, 1);
            send_event_from_task(&event);
        }
    }
}

static void monitor_task(void *arg)
{
    TickType_t last_wake = xTaskGetTickCount();
    uint64_t last_log_us = 0;
    uint64_t last_recovery_attempt_us = 0;
    uint32_t peak_tec = 0;
    uint32_t peak_rec = 0;
    uint8_t reported_tec_markers = 0;
    twai_error_state_t last_state = TWAI_ERROR_ACTIVE;
    throttle_mode_t last_mode = THROTTLE_NORMAL;
    bool recovery_requested = false;

    for (;;) {
        twai_node_status_t status;
        twai_node_record_t record;
        if (twai_node_get_info(twai_node, &status, &record) == ESP_OK) {
            uint64_t now_us = (uint64_t)esp_timer_get_time();
            throttle_mode_t mode = throttle_mode_from_tec(status.tx_error_count);
            throttle_mode_t previous_mode =
                (throttle_mode_t)atomic_exchange(&current_mode, mode);
            bool is_bus_off = status.state == TWAI_ERROR_BUS_OFF;
            bool was_bus_off = atomic_exchange(&controller_bus_off, is_bus_off);
            if ((previous_mode != mode || was_bus_off != is_bus_off) &&
                transmitter_task_handle != NULL) {
                xTaskNotify(transmitter_task_handle, TX_WAKE_MODE, eSetBits);
            }

            if (status.state == TWAI_ERROR_BUS_OFF) {
                if (!recovery_requested &&
                    (last_recovery_attempt_us == 0 ||
                     now_us - last_recovery_attempt_us >= RECOVER_RETRY_MS * 1000ULL)) {
                    last_recovery_attempt_us = now_us;
                    esp_err_t result = twai_node_recover(twai_node);
                    recovery_requested = result == ESP_OK;
                    node_event_t event = {
                        .type = EVENT_RECOVERY,
                        .timestamp_us = (uint64_t)esp_timer_get_time(),
                    };
                    event.recovery.result = result;
                    send_event_from_task(&event);
                }
            } else {
                recovery_requested = false;
            }

            if (status.tx_error_count > peak_tec) {
                peak_tec = status.tx_error_count;
            }
            if (status.rx_error_count > peak_rec) {
                peak_rec = status.rx_error_count;
            }
            // Um unico SAMPLE extra na primeira observacao de cada marco.
            const uint32_t markers[] = {160, 192, 224, 240};
            uint8_t marker_mask = 0;
            for (unsigned i = 0; i < sizeof(markers) / sizeof(markers[0]); i++) {
                if (status.tx_error_count >= markers[i]) {
                    marker_mask |= (uint8_t)(1U << i);
                }
            }
            bool new_tec_marker = (marker_mask & (uint8_t)~reported_tec_markers) != 0;
            reported_tec_markers |= marker_mask;
            bool state_changed = status.state != last_state || mode != last_mode;
            bool heartbeat = last_log_us == 0 ||
                             now_us - last_log_us >= HEARTBEAT_MS * 1000ULL;
            if (state_changed || heartbeat || new_tec_marker) {
                node_event_t event = {
                    .type = EVENT_SAMPLE,
                    .timestamp_us = now_us,
                };
                event.sample.tec = status.tx_error_count;
                event.sample.rec = status.rx_error_count;
                event.sample.tec_peak = peak_tec;
                event.sample.rec_peak = peak_rec;
                event.sample.bus_errors = record.bus_err_num;
                event.sample.produced = atomic_load(&produced_count);
                event.sample.submitted = atomic_load(&submitted_count);
                event.sample.tx_ok = atomic_load(&tx_success_count);
                event.sample.tx_failed = atomic_load(&tx_failed_count);
                event.sample.rejected = atomic_load(&rejected_count);
                event.sample.skipped_before = atomic_load(&skipped_count);
                event.sample.lost_events = atomic_load(&event_lost_count);
                event.sample.update_queue_len = uxQueueMessagesWaiting(update_queue);
                event.sample.tx_pending = atomic_load(&tx_pending);
                event.sample.state = status.state;
                event.sample.mode = mode;
                send_event_from_task(&event);
                last_log_us = now_us;
                peak_tec = 0;
                peak_rec = 0;
            }
            last_state = status.state;
            last_mode = mode;
        }
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(MONITOR_PERIOD_MS));
    }
}

static void event_task(void *arg)
{
    node_event_t event;
    for (;;) {
        if (xQueueReceive(event_queue, &event, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        switch (event.type) {
            case EVENT_SAMPLE:
                printf("DATA,%llu,SAMPLE,-1,%u,%u,%s,%s,tec_peak=%lu;rec_peak=%lu;errors=%lu;produced=%lu;submitted=%lu;tx_ok=%lu;tx_failed=%lu;rejected=%lu;gap=%lu;pending=%u;qlen=%lu;lost=%lu\n",
                       (unsigned long long)event.timestamp_us,
                       (unsigned)event.sample.tec,
                       (unsigned)event.sample.rec,
                       can_state_name(event.sample.state),
                       mode_name(event.sample.mode),
                       (unsigned long)event.sample.tec_peak,
                       (unsigned long)event.sample.rec_peak,
                       (unsigned long)event.sample.bus_errors,
                       (unsigned long)event.sample.produced,
                       (unsigned long)event.sample.submitted,
                       (unsigned long)event.sample.tx_ok,
                       (unsigned long)event.sample.tx_failed,
                       (unsigned long)event.sample.rejected,
                       (unsigned long)event.sample.skipped_before,
                       (unsigned)event.sample.tx_pending,
                       (unsigned long)event.sample.update_queue_len,
                       (unsigned long)event.sample.lost_events);
                break;
            case EVENT_TX_REJECTED:
                printf("DATA,%llu,TX_REJECTED,%lu,-1,-1,-,-,wait_us=%llu;gap=%lu;result=%s\n",
                       (unsigned long long)event.timestamp_us,
                       (unsigned long)event.tx.sequence,
                       (unsigned long long)(event.tx.submitted_us - event.tx.generated_us),
                       (unsigned long)event.tx.skipped_before,
                       esp_err_to_name(event.tx.result));
                break;
            case EVENT_TX_DONE:
                printf("DATA,%llu,%s,%lu,-1,-1,-,-,latency_us=%llu;wait_us=%llu\n",
                       (unsigned long long)event.timestamp_us,
                       event.tx.success ? "TX_SUCCESS" : "TX_FAILED",
                       (unsigned long)event.tx.sequence,
                       (unsigned long long)(event.timestamp_us - event.tx.generated_us),
                       (unsigned long long)(event.tx.submitted_us - event.tx.generated_us));
                break;
            case EVENT_STATE_CHANGE:
                printf("DATA,%llu,STATE_CHANGE,-1,-1,-1,-,-,%s->%s\n",
                       (unsigned long long)event.timestamp_us,
                       can_state_name(event.state.old_state),
                       can_state_name(event.state.new_state));
                break;
            case EVENT_ERROR:
                printf("DATA,%llu,ERROR,-1,-1,-1,-,-,flags=0x%08lx\n",
                       (unsigned long long)event.timestamp_us,
                       (unsigned long)event.error.flags);
                break;
            case EVENT_RECOVERY:
                printf("DATA,%llu,RECOVERY_REQUEST,-1,-1,-1,-,-,result=%s\n",
                       (unsigned long long)event.timestamp_us,
                       esp_err_to_name(event.recovery.result));
                break;
            case EVENT_PENDING_WARNING:
                printf("DATA,%llu,PENDING_WARNING,%lu,-1,-1,-,-,pending_over_200ms\n",
                       (unsigned long long)event.timestamp_us,
                       (unsigned long)event.tx.sequence);
                break;
        }
    }
}

void app_main(void)
{
    event_queue = xQueueCreate(128, sizeof(node_event_t));
    update_queue = xQueueCreate(1, sizeof(update_t));
    ESP_ERROR_CHECK(event_queue && update_queue ? ESP_OK : ESP_ERR_NO_MEM);

    twai_onchip_node_config_t config = {
        .io_cfg = {
            .tx = TWAI_TX_GPIO,
            .rx = TWAI_RX_GPIO,
            .quanta_clk_out = -1,
            .bus_off_indicator = -1,
        },
        .bit_timing = { .bitrate = CAN_BITRATE },
        .tx_queue_depth = 1,
        .fail_retry_cnt = -1,
    };
    ESP_ERROR_CHECK(twai_new_node_onchip(&config, &twai_node));

    inflight_frame = (twai_frame_t){
        .header.id = CAN_ID_UPDATE,
        .buffer = inflight_payload,
        .buffer_len = sizeof(inflight_payload),
    };
    twai_event_callbacks_t callbacks = {
        .on_tx_done = tx_done_callback,
        .on_state_change = state_change_callback,
        .on_error = error_callback,
    };
    ESP_ERROR_CHECK(twai_node_register_event_callbacks(twai_node, &callbacks, NULL));
    ESP_ERROR_CHECK(twai_node_enable(twai_node));

    ESP_LOGI("NODE_A", "%s | TWAI %d bit/s, throttling=%d, rates=100/50/25 Hz",
             FW_BUILD_TAG, CAN_BITRATE, ENABLE_THROTTLING);
    esp_log_level_set("*", ESP_LOG_NONE);

    BaseType_t rc;
    rc = xTaskCreatePinnedToCore(event_task, "event_task", 4096, NULL,
                                 3, NULL, APP_CORE);
    configASSERT(rc == pdPASS);
    rc = xTaskCreatePinnedToCore(monitor_task, "monitor_task", 4096, NULL,
                                 6, NULL, APP_CORE);
    configASSERT(rc == pdPASS);
    rc = xTaskCreatePinnedToCore(transmitter_task, "transmitter_task", 4096,
                                 NULL, 5, &transmitter_task_handle, APP_CORE);
    configASSERT(rc == pdPASS);
    rc = xTaskCreatePinnedToCore(producer_task, "producer_task", 4096,
                                 NULL, 4, NULL, APP_CORE);
    configASSERT(rc == pdPASS);
}