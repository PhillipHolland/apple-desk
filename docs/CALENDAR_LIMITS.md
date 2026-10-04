# Calendar limits

This CLI talks to Calendar.app with JXA. It does not use EventKit.

## Display alarm

Calendar's scripting definition includes a display alarm on an event, with a trigger interval in minutes (negative means before the start). `grok-calendar alarm --uid EVENTUID --minutes 15` plans one display alarm 15 minutes before the start.

Without `--force` the command is a dry-run. It checks the arguments and does not call Calendar.app. `--force` adds that one display alarm on the existing JXA path. Sound alarms, mail alarms, and open-file alarms are not created. There is no command to delete an alarm.

## Move between calendars

Not available. The event class has no calendar property, and the event does not respond to `move`. This CLI does not copy the event onto another calendar and delete the original. `update` changes fields on the event's current calendar only.

## Attendees and RSVP

`show` may include `attendeeCount`. It does not print attendee names, RSVP names, participation status, or email addresses. Those names are omitted unless you explicitly ask, and there is no command that dumps them. The CLI does not send invites or propose a new time.
