// SPDX-License-Identifier: MIT
// The launcher appends the actual production audit function from window_sdl.c.
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void input_audit_event(const SDL_Event *event);

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    SDL_Event event = {0};
    if (!strcmp(argv[1], "flood")) {
        event.type = SDL_EVENT_MOUSE_MOTION;
        for (int i = 0; i < 1024; i++) input_audit_event(&event);
        return 0;
    }
    // Unrelated text must neither appear in the log nor spend the pointer budget.
    event.type = SDL_EVENT_TEXT_INPUT;
    event.text.text = "SHOULD_NEVER_BE_LOGGED";
    for (int i = 0; i < 1024; i++) input_audit_event(&event);
    const SDL_EventType keys[] = {SDL_EVENT_KEY_DOWN, SDL_EVENT_KEY_UP};
    for (unsigned i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
        memset(&event, 0, sizeof event);
        event.type = keys[i]; event.key.scancode = SDL_SCANCODE_A;
        input_audit_event(&event);
    }
    const SDL_EventType focus[] = {SDL_EVENT_WINDOW_FOCUS_GAINED, SDL_EVENT_WINDOW_FOCUS_LOST};
    for (unsigned i = 0; i < sizeof(focus) / sizeof(focus[0]); i++) {
        event.type = focus[i];
        input_audit_event(&event);
    }
    const SDL_EventType fingers[] = {SDL_EVENT_FINGER_DOWN, SDL_EVENT_FINGER_MOTION,
                                    SDL_EVENT_FINGER_UP, SDL_EVENT_FINGER_CANCELED};
    for (unsigned i = 0; i < sizeof(fingers) / sizeof(fingers[0]); i++) {
        memset(&event, 0, sizeof event);
        event.type = fingers[i]; event.tfinger.windowID = 99;
        event.tfinger.touchID = 123; event.tfinger.fingerID = 456;
        event.tfinger.x = .25f; event.tfinger.y = .75f; event.tfinger.pressure = .5f;
        input_audit_event(&event);
    }
    memset(&event, 0, sizeof event);
    event.type = SDL_EVENT_MOUSE_MOTION; event.motion.windowID = 99;
    event.motion.which = SDL_TOUCH_MOUSEID; event.motion.x = 320; event.motion.y = 540;
    input_audit_event(&event);
    const SDL_EventType buttons[] = {SDL_EVENT_MOUSE_BUTTON_DOWN, SDL_EVENT_MOUSE_BUTTON_UP};
    for (unsigned i = 0; i < sizeof(buttons) / sizeof(buttons[0]); i++) {
        memset(&event, 0, sizeof event);
        event.type = buttons[i]; event.button.windowID = 99; event.button.which = 17;
        event.button.button = SDL_BUTTON_LEFT; event.button.x = 320; event.button.y = 540;
        input_audit_event(&event);
    }
    return 0;
}
