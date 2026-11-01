# mode_dispatcher.py

import re

# ===== MODE DETECTORS =====

def detect_panic(text):
    triggers = [
        "panic", "freaking out", "overwhelmed", "can't breathe",
        "losing it", "help me", "please help", "anxiety"
    ]
    return any(t in text.lower() for t in triggers)


def detect_loop(text):
    # cognitive loop language
    patterns = [
        r"why do i always",
        r"this always happens",
        r"i can't stop thinking",
        r"over and over",
        r"stuck in my head"
    ]
    return any(re.search(p, text.lower()) for p in patterns)


def detect_identity_drift(text):
    triggers = [
        "who am i", "i feel lost", "nothing feels real",
        "i don't feel like myself", "disconnected"
    ]
    return any(t in text.lower() for t in triggers)


def detect_symbolic(text):
    triggers = [
        "dream", "symbol", "vision", "strange image",
        "what does this mean"
    ]
    return any(t in text.lower() for t in triggers)


def detect_manipulation(text):
    triggers = [
        "they say i must", "i have to obey",
        "everyone says", "news says",
        "they told me i can't"
    ]
    return any(t in text.lower() for t in triggers)


def detect_story_intake(text):
    triggers = [
        "let me tell you", "i want to record",
        "remember this", "save this story"
    ]
    return any(t in text.lower() for t in triggers)


def detect_isolation(text):
    triggers = [
        "no one understands", "i feel alone",
        "i have nobody", "i can't talk to anyone"
    ]
    return any(t in text.lower() for t in triggers)


# ===== DISPATCH =====

def choose_mode(user_input):
    if detect_panic(user_input):
        return "FIELD_SURGEON"

    if detect_loop(user_input):
        return "REALITY_EDITOR"

    if detect_identity_drift(user_input):
        return "LIMINAL_ANCHOR"

    if detect_symbolic(user_input):
        return "STARWALK"

    if detect_manipulation(user_input):
        return "DEPROGRAMMER"

    if detect_story_intake(user_input):
        return "FIREKEEPER"

    if detect_isolation(user_input):
        return "EXILE_SHEPHERD"

    return "STANDARD"