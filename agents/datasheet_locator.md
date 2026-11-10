# Datasheet locator

Goal: reduce cost by selecting only the useful pages of a datasheet.

## Input
A datasheet PDF and the MPN.

## Steps
1. Confirm the PDF matches the MPN (exact part, package, suffix). Record revision and date.
2. Check whether a newer revision exists from the manufacturer. If yes, use it and say so.
3. From the table of contents (or page headers if there is none), return the pages for:
   pinout, absolute maximum ratings, recommended operating conditions, electrical
   characteristics, application circuit and component selection, layout guidelines.

## Output
```json
{ "mpn": "...", "revision": "...", "date": "...", "source_url": "...",
  "sections": { "pinout": [3, 4], "absolute_maximum": [5], "...": [] } }
```
