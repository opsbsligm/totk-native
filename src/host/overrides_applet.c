/* Host side of applet, telemetry, NFC and error-display functions the game reaches.
 * Ported from MacNativeGames games/totk/runtime/applet_host.c @b75be8c (MIT): client-side SDK code (PlayReport
 * encoding, keyboard presets, diag logging) runs unchanged; only the calls that would talk to system services are
 * taken here. */
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#include "host.h"
#include "native_amiibo.h"
#include "../runtime/hle.h"

/* ---------- nn::oe / nn::applet ---------- */
static float balance[2] = {1.0f, 1.0f};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t message_cv = PTHREAD_COND_INITIALIZER;
static uint32_t messages[32];
static unsigned head, tail;
static uint64_t start_ns;
__attribute__((constructor)) static void started(void) { start_ns = runtime_now_ns(); }

void runtime_oe_push_message(uint32_t message) {
    pthread_mutex_lock(&lock);
    if (tail - head < 32) { messages[tail++ % 32] = message; pthread_cond_broadcast(&message_cv); }
    pthread_mutex_unlock(&lock);
}
static void get_balance(float *l, float *r) {
    pthread_mutex_lock(&lock);
    if (l) *l = balance[0];
    if (r) *r = balance[1];
    pthread_mutex_unlock(&lock);
}
static int64_t total_active_time(void) { return (int64_t)(runtime_now_ns() - start_ns); }   /* TimeSpan in ns */
static void inactivity_extended(unsigned char on) { (void)on; }   /* the host never sleeps the console */
static void finish_startup_logo(void) { fprintf(stderr, "[totk] game finished startup logo\n"); }
/* The executable was launched directly: no predecessor in an ExecuteProgram chain (-1 keeps the normal path). */
static int previous_program_index(void) { return -1; }
/* A stable, nonzero resource id for this process's one application. */
static uint64_t applet_resource_user_id(void) { return 1; }
static unsigned char try_pop_launch_parameter(uint64_t *size, void *buffer, uint64_t capacity) {
    (void)buffer; (void)capacity;
    if (size) *size = 0;
    return 0;
}
static unsigned char try_pop(uint32_t *out) {
    pthread_mutex_lock(&lock);
    int ok = head != tail;
    if (ok && out) *out = messages[head++ % 32];
    pthread_mutex_unlock(&lock);
    return (unsigned char)ok;
}
int runtime_core_away(void);
void runtime_core_back(int *away);
static uint32_t pop(void) {
    __attribute__((cleanup(runtime_core_back))) int away = runtime_core_away();   /* blocks like a Horizon wait */
    pthread_mutex_lock(&lock);
    while (head == tail) pthread_cond_wait(&message_cv, &lock);
    uint32_t m = messages[head++ % 32];
    pthread_mutex_unlock(&lock);
    return m;
}
HLE_FUNC("_ZN2nn2oe24SetExpectedVolumeBalanceEff", set_balance) {   /* float arguments: v0, v1 */
    float l, r;
    memcpy(&l, &c->v[0], 4);
    memcpy(&r, &c->v[1], 4);
    if (l < 0 || l > 1 || r < 0 || r > 1) runtime_fail("volume balance out of range");
    pthread_mutex_lock(&lock);
    balance[0] = l; balance[1] = r;
    pthread_mutex_unlock(&lock);
}

/* ---------- nn::prepo: play reports are not transmitted (no Nintendo servers) ---------- */
static uint64_t reports;
static unsigned report_save(const void *report) {
    (void)report;
    if (!(reports++ % 100)) fprintf(stderr, "[totk] play report kept local (not transmitted), count %llu\n", (unsigned long long)reports);
    return 0;
}
static unsigned report_save_uid(const void *report, const void *uid) { (void)uid; return report_save(report); }
static unsigned immediate_transmission(void) { return 0; }
static unsigned connection_status(void *report, const char *a, const char *b, const char *c) { (void)report; (void)a; (void)b; (void)c; return 0; }

/* ---------- nn::nfp: local, read-only virtual figure reader ---------- */
static pthread_mutex_t nfp_events_lock=PTHREAD_MUTEX_INITIALIZER;
static void *nfp_activate,*nfp_deactivate;
static void nfp_sync_events(void) {
    pthread_mutex_lock(&nfp_events_lock);
    NdAmiiboSnapshot state;nd_amiibo_snapshot(&state);
    int level=(state.state==2 || state.state==4)?1:state.state==3?-1:0;
    // These are manual-reset levels. A replacement must withdraw the old level;
    // stale/recycled kernel handles must never be revived by a host callback.
    hle_update_system_event_pair(nfp_activate,nfp_deactivate,level);
    pthread_mutex_unlock(&nfp_events_lock);
}
static void nfp_notify(int activated) {(void)activated;nfp_sync_events();}
static int nfp_valid(const void *h) {uint64_t id=0;if(h) memcpy(&id,h,8);return id==1;}
static unsigned nfp_initialize(void) {nd_amiibo_set_notify(nfp_notify);nd_amiibo_initialize(1);return 0;}
static unsigned nfp_finalize(void) {
    pthread_mutex_lock(&nfp_events_lock);nfp_activate=nfp_deactivate=NULL;pthread_mutex_unlock(&nfp_events_lock);
    nd_amiibo_initialize(0);return 0;
}
static int nfp_get_state(void) {NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);return s.initialized;}
static unsigned nfp_list(void *handles,int *count,int max) {
    if(count) *count=0;
    if(!nfp_get_state()) return ND_NFP_NOT_FOUND;
    if(max>0 && handles) {uint64_t id=1;guest_prepare_write(handles,8);memcpy(handles,&id,8);if(count) *count=1;}
    return 0;
}
static unsigned nfp_attach_availability(void *event) {
    if(!event) return ND_NFP_NOT_FOUND;
    hle_bind_system_event(event,0);hle_signal_system_event(event);return 0;
}
static unsigned nfp_attach_activate(void *event,const void *h) {
    if(!event || !nfp_valid(h)) return ND_NFP_NOT_FOUND;
    hle_bind_system_event(event,0);
    pthread_mutex_lock(&nfp_events_lock);nfp_activate=event;pthread_mutex_unlock(&nfp_events_lock);
    nfp_sync_events();return 0;
}
static unsigned nfp_attach_deactivate(void *event,const void *h) {
    if(!event || !nfp_valid(h)) return ND_NFP_NOT_FOUND;
    hle_bind_system_event(event,0);
    pthread_mutex_lock(&nfp_events_lock);nfp_deactivate=event;pthread_mutex_unlock(&nfp_events_lock);nfp_sync_events();return 0;
}
static int nfp_device_state(const void *h) {NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);return nfp_valid(h)?s.state:5;}
static unsigned nfp_start(const void *h) {
    if(!nfp_valid(h)) return ND_NFP_NOT_FOUND;
    // The ability wheel may destroy its SystemEvents between detection attempts.
    pthread_mutex_lock(&nfp_events_lock);void *activate=nfp_activate,*deactivate=nfp_deactivate;pthread_mutex_unlock(&nfp_events_lock);
    if(activate) hle_bind_system_event(activate,0);
    if(deactivate) hle_bind_system_event(deactivate,0);
    unsigned result=nd_amiibo_start();nfp_sync_events();return result;
}
static unsigned nfp_stop(const void *h) {if(!nfp_valid(h)) return ND_NFP_NOT_FOUND;unsigned result=nd_amiibo_stop();nfp_sync_events();return result;}
static unsigned nfp_mount(const void *h,unsigned model,unsigned target) {(void)model;(void)target;return nfp_valid(h)?nd_amiibo_mount():ND_NFP_NOT_FOUND;}
static unsigned nfp_unmount(const void *h) {return nfp_valid(h)?nd_amiibo_unmount():ND_NFP_NOT_FOUND;}
static unsigned nfp_npad(unsigned *out,const void *h) {if(!out || !nfp_valid(h)) return ND_NFP_NOT_FOUND;*out=0;return 0;}
static unsigned nfp_tag(void *out,const void *h) {if(!nfp_valid(h)) return ND_NFP_NOT_FOUND;guest_prepare_write(out,0x58);return nd_amiibo_tag_info(out,0x58);}
static unsigned nfp_model(void *out,const void *h) {if(!nfp_valid(h)) return ND_NFP_NOT_FOUND;guest_prepare_write(out,0x40);return nd_amiibo_model_info(out,0x40);}

/* ---------- nn::err ---------- */
static void show_error(uint32_t result) {
    fprintf(stderr, "[totk] game error dialog: %04u-%04u (result %#x)\n", 2000 + (result & 0x1ff), (result >> 9) & 0x1fff, result);
}

HLE_NATIVE("_ZN2nn6applet23GetPreviousProgramIndexEv", previous_program_index, 'w')
HLE_NATIVE("_ZN2nn6applet23GetAppletResourceUserIdEv", applet_resource_user_id, 'x')
HLE_NATIVE("_ZN2nn2am23GetAppletResourceUserIdEv", applet_resource_user_id, 'x')
HLE_NATIVE("_ZN2nn2oe21TryPopLaunchParameterEPmPvm", try_pop_launch_parameter, 'b')
HLE_NATIVE("_ZN2nn2oe24GetExpectedVolumeBalanceEPfS1_", get_balance, 'v')
HLE_NATIVE("_ZN2nn2oe25GetProgramTotalActiveTimeEv", total_active_time, 'x')
HLE_NATIVE("_ZN2nn2oe38SetUserInactivityDetectionTimeExtendedEb", inactivity_extended, 'v')
HLE_NATIVE("_ZN2nn2oe44SetUserInactivityDetectionTimeExtendedUnsafeEb", inactivity_extended, 'v')
HLE_NATIVE("_ZN2nn2oe17FinishStartupLogoEv", finish_startup_logo, 'v')
HLE_NATIVE("_ZN2nn2oe25TryPopNotificationMessageEPj", try_pop, 'b')
HLE_NATIVE("_ZN2nn2oe22PopNotificationMessageEv", pop, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport4SaveEv", report_save, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport4SaveERKNS_7account3UidE", report_save_uid, 'w')
HLE_NATIVE("_ZN2nn5prepo28RequestImmediateTransmissionEv", immediate_transmission, 'w')
HLE_NATIVE("_ZN2nn5prepo27AddInternetConnectionStatusEPNS0_10PlayReportEPKcS4_S4_", connection_status, 'w')
HLE_NATIVE("_ZN2nn3nfp10InitializeEv", nfp_initialize, 'w')
HLE_NATIVE("_ZN2nn3nfp8FinalizeEv", nfp_finalize, 'w')
HLE_NATIVE("_ZN2nn3nfp8GetStateEv", nfp_get_state, 'w')
HLE_NATIVE("_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii", nfp_list, 'w')
HLE_NATIVE("_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE", nfp_attach_availability, 'w')
HLE_NATIVE("_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE", nfp_device_state, 'w')
HLE_NATIVE("_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE", nfp_mount, 'w')
HLE_NATIVE("_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE", nfp_npad, 'w')
HLE_NATIVE("_ZN2nn3nfp19AttachActivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE", nfp_attach_activate, 'w')
HLE_NATIVE("_ZN2nn3nfp21AttachDeactivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE", nfp_attach_deactivate, 'w')
HLE_NATIVE("_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE", nfp_start, 'w')
HLE_NATIVE("_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE", nfp_stop, 'w')
HLE_NATIVE("_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE", nfp_tag, 'w')
HLE_NATIVE("_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE", nfp_model, 'w')
HLE_NATIVE("_ZN2nn3err9ShowErrorENS_6ResultE", show_error, 'v')
HLE_NATIVE("_ZN2nn3nfp7UnmountERKNS0_12DeviceHandleE", nfp_unmount, 'w')
