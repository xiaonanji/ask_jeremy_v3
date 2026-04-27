# Disable Data Source selector after conversation starts

## Context
Users should only be able to select a data source for an empty conversation. Once messages exist, the selector should be locked.

## Change
In `frontend/src/App.tsx`, add `activeSession.messages.length > 0` to the `disabled` prop of the Data Source `<select>`.

**Current** (line ~1035):
```
disabled={isUpdatingDatabase || isUpdatingModel || isSending}
```

**New:**
```
disabled={isUpdatingDatabase || isUpdatingModel || isSending || activeSession.messages.length > 0}
```

## Verification
1. Start a new empty session — Data Source dropdown should be enabled.
2. Send a message — Data Source dropdown should become disabled.
3. Switch to another empty session — dropdown should be enabled again.
