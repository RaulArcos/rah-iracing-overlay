# Radar and BlindSpot (R4)

## Representation and provenance
- Both skins use the same DOM, existing socket namespaces/events and IDs. Original
  is sharp dark/red; Glass uses shared translucent surfaces and rounded details.
- Radar's white center car and crosshair are schematic. Left/right red soft zones
  come only from `left_alert === true` and `right_alert === true`. Both flags true
  intensify the steady warning. BlindSpot uses bracketed labelled amber tiles,
  red for both sides. No animation, strobes, background dots or copied images.
- The side flags originate in iRacing `CarLeftRight` via the existing provider.
  Ignore `both_alert`, `active` and free-form `message` for safety decisions;
  derive labels from the actual boolean fields. Unknown flags display `?` and
  unavailable, never clear/safe. Known false means only “No side alerts”.
- Legacy limitation: the server sometimes sends false when the SDK field is
  missing. A frontend cannot infer that absence from a valid false payload.
  This slice deliberately preserves the backend contract and documents the limit.

## Distance and bars
- Existing `nearby[].distance_pct` is a **signed fraction of a lap**, not a
  percentage in 0–100 units. The provider wraps completed-lap plus lap progress
  to the nearest half lap and currently selects within 0.035 lap. Positive is
  ahead, negative behind. Each direction selects its nearest valid magnitude;
  inconsistent `relation` text cannot reverse the numeric sign. Zero is labelled
  COINCIDENT in the visible provenance footer, never forced into a
  side/ahead/behind claim.
- Filter invalid/non-finite records independently; accept the wrapped [-0.5,0.5]
  numeric domain. Metadata is inserted through `textContent`, never HTML.
- Estimated meters = abs(distance_pct × track_length_m), marked `~` with visible
  lap-progress provenance. Track length must be a finite positive number derived
  by the existing provider from `WeekendInfo.TrackLength`. Never default it.
  Missing/invalid length gives `-- m`, zero bar fill and an explicit lap-% label
  when a valid nearby record exists. Missing nearby gives `-- m`/No distance data.
- Each vertical bar independently shows proximity over a fixed **100 m** range:
  fill = clamp(100 − estimated meters, 0, 100) percent. Outside range is zero fill,
  not a safety assertion; the numeric distance remains visible. Bar colours are
  amber ahead/coral behind, never green “safe”. They are not throttle/brake.
- This is lap-progress separation, not physical separation or precise collision
  detection. No lateral coordinates, relative velocity, approaching-speed claim,
  predictive TTC, simulator control or new RPC is introduced.

## Lifecycle and geometry
- Initial/null/invalid payload, disconnect and connect_error remove old side
  warnings and distances. Over 3 seconds without an update clears them at the
  next 250 ms watchdog tick; fresh updates restore the representation.
- Existing native defaults remain Radar 320×210, BlindSpot 380×120. No resolution,
  saved position, DPI or input properties changes. Radar combines zones and bars;
  no 14th overlay. Legacy nearby-list remains accessible, nearest values visible.
- Boundary-fixture browser checks use public Flask routes and actual JS/CSS, not
  a live simulator session. Manual live iRacing, OBS transparency and desktop
  sizing checks remain necessary; these widgets are read-only.
