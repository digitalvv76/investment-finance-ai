# Phone Notification Intensity Guide

## Pushover App (Primary Emergency Channel)

### iOS
1. **Settings > Notifications > Pushover**
   - Enable "Critical Alerts" — bypasses DND & silent mode
   - Sound: set to "Alarm" or a custom loud tone
   - Banner Style: Persistent
2. **Pushover App > Settings**
   - Vibration: ON
   - Always Play Alert Sound: ON (even when ringer is silent)

### Android
1. **Settings > Apps > Pushover > Notifications**
   - Emergency Alerts channel: Importance = Urgent (bypass DND)
   - Sound: choose a long, loud alarm tone
   - Vibration: ON (max strength)
   - Enable "Override Do Not Disturb"
2. **Pushover App > Settings**
   - Notification Sound: set per priority level
   - High Priority: continuous vibration

---

## Telegram App (Secondary Channel)

### iOS
1. **Settings > Notifications > Telegram**
   - Enable Sounds + Badges
   - Sound: choose a distinct loud tone
2. **Telegram > Your Bot Chat > Mute = OFF**

### Android
1. **Settings > Apps > Telegram > Notifications**
   - Importance: Urgent
   - Sound: choose a loud, long alarm sound
   - Vibration: ON (long pattern if available)
2. **Telegram > Your Bot Chat > Notifications > Custom**
   - Sound: custom loud tone
   - Vibration: ON
   - Override DND: YES

---

## Extreme: Tasker Automation (Android)

Tasker can detect `[TAG:CRITICAL]` in Telegram messages and trigger:
- Play full-volume alarm ringtone
- Flash screen / flashlight
- Auto-reply to confirm receipt

Profile trigger: Notification Event > App: Telegram > Title: `*TAG:CRITICAL*`
Task: Play Ringtone (max volume) + Vibrate Pattern (max)

---

## Code Changes Made

| Setting | Before | After |
|---------|--------|-------|
| Pushover sound | `siren` | `spacealarm` (most jarring) |
| Pushover retry | every 60s | every 30s |
| Telegram push count | 3 messages | 5 messages |
| Telegram interval | 500ms | 300ms |
